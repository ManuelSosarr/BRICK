import sqlite3
import datetime as dt
import json
import uuid as _uuid
import base64
import requests as http
import psycopg2
from fastapi import APIRouter, Header, UploadFile, File, Form, HTTPException
from fastapi.responses import Response
from typing import Optional
from app.drawio_parser import parse_drawio

from app.vici_connector import get_connection

router = APIRouter()

# SQLite — solo para campaign_scripts y Burner config keys
DB_PATH       = "C:/Users/sosai/BRICK/vicidial.db"

# PostgreSQL — fuente de verdad para tenants
PG_DSN        = "postgresql://dialflow:dialflow@localhost:5432/dialflow"
AUTH_BASE_URL = "http://localhost:8001"


# ─── PostgreSQL helper ────────────────────────────────────────────────────────

def _pg():
    """Short-lived psycopg2 connection. Caller must close."""
    return psycopg2.connect(PG_DSN)


def _pg_list_tenants() -> list[dict]:
    """
    Read tenants from PostgreSQL. Returns ONE row per tenant with
    campaign_ids as an array — never one row per campaign.
    """
    conn = _pg()
    cur  = conn.cursor()
    cur.execute("""
        SELECT t.subdomain,
               t.name,
               t.status,
               v.campaign_ids
        FROM   tenants t
        LEFT JOIN vicidial_configs v ON v.tenant_id = t.id
        ORDER  BY t.name
    """)
    rows = cur.fetchall()
    cur.close(); conn.close()

    result = []
    for subdomain, name, status, campaign_ids in rows:
        # str() guard — PostgreSQL enum may return enum object in some drivers
        active = str(status).lower() in ("trial", "active")
        camps  = campaign_ids or []
        if isinstance(camps, str):
            try: camps = json.loads(camps)
            except: camps = []
        result.append({
            "tenant_id":    subdomain,
            "tenant_name":  name,
            "role":         "client",
            "campaign_ids": camps,   # array — frontend decides how to display
            "active":       active,
        })
    return result


def _pg_assigned_campaigns() -> set:
    """Return the set of campaign IDs already assigned to any tenant."""
    conn = _pg()
    cur  = conn.cursor()
    cur.execute("SELECT campaign_ids FROM vicidial_configs")
    rows = cur.fetchall()
    cur.close(); conn.close()
    assigned = set()
    for (campaign_ids,) in rows:
        camps = campaign_ids or []
        if isinstance(camps, str):
            try: camps = json.loads(camps)
            except: camps = []
        for cid in camps:
            assigned.add(str(cid))
    return assigned


# ─── SQLite helper — solo para scripts ────────────────────────────────────────

def _init_scripts(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS campaign_scripts (
            campaign_id TEXT PRIMARY KEY,
            script      TEXT NOT NULL DEFAULT '',
            updated_at  TEXT
        )
    """)


# ─── Tenants CRUD — ahora desde PostgreSQL ───────────────────────────────────

@router.get("/tenants")
def admin_list_tenants():
    try:
        return _pg_list_tenants()
    except Exception as e:
        return {"error": f"PostgreSQL no disponible: {str(e)}"}


@router.post("/tenants/{tenant_id}/toggle")
def admin_toggle_tenant(tenant_id: str):
    """
    Toggle tenant active/suspended en PostgreSQL.
    tenant_id = subdomain (e.g. 'bossbuy').
    """
    try:
        conn = _pg()
        cur  = conn.cursor()
        cur.execute("SELECT status FROM tenants WHERE subdomain=%s", (tenant_id,))
        row = cur.fetchone()
        if not row:
            cur.close(); conn.close()
            return {"ok": False, "error": f"Tenant '{tenant_id}' no encontrado"}
        new_status = "suspended" if row[0] in ("trial", "active") else "active"
        cur.execute("UPDATE tenants SET status=%s WHERE subdomain=%s", (new_status, tenant_id))
        conn.commit()
        cur.close(); conn.close()
        return {"ok": True, "tenant_id": tenant_id, "active": new_status == "active"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.delete("/tenants/{tenant_id}")
def admin_delete_tenant(tenant_id: str):
    """
    Elimina tenant de PostgreSQL. Cascadea a users, configs, leads, etc.
    tenant_id = subdomain.
    """
    try:
        conn = _pg()
        cur  = conn.cursor()
        cur.execute("DELETE FROM tenants WHERE subdomain=%s", (tenant_id,))
        conn.commit()
        deleted = cur.rowcount
        cur.close(); conn.close()
        return {"ok": deleted > 0, "tenant_id": tenant_id}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─── ViciDial campaigns no asignados ─────────────────────────────────────────

@router.get("/vici/campaigns/unassigned")
def admin_vici_unassigned():
    try:
        assigned = _pg_assigned_campaigns()
    except Exception as e:
        return {"error": f"PostgreSQL no disponible: {str(e)}", "campaigns": []}

    try:
        conn = get_connection()
        cur  = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT campaign_id, campaign_name, active FROM vicidial_campaigns ORDER BY campaign_name"
        )
        all_campaigns = cur.fetchall()
        cur.close(); conn.close()
    except Exception as e:
        return {"error": str(e), "campaigns": []}

    unassigned = [
        {
            "campaign_id":   c["campaign_id"],
            "campaign_name": c["campaign_name"],
            "active":        c["active"] == "Y",
        }
        for c in all_campaigns
        if c["campaign_id"] not in assigned
    ]
    return {"campaigns": unassigned}


# ─── Sync — registrar tenant nuevo en BRICK ──────────────────────────────────

SYNC_DAYS = ["thu", "fri", "sat", "sun"]

def _next_sync_day() -> str:
    """Round-robin: cuenta tenants existentes y asigna el siguiente día."""
    conn = _pg()
    cur  = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM vicidial_configs")
    count = cur.fetchone()[0]
    cur.close(); conn.close()
    return SYNC_DAYS[count % 4]


def _pg_update_vicidial_config(tenant_uuid: str, campaign_ids: list, campaign_list_map: dict, sync_day: str):
    """Escribe/actualiza campaign_ids, campaign_list_map y sync_day en vicidial_configs.
    MERGE: nunca sobreescribe campaign_ids existentes — solo agrega nuevas campañas.
    """
    conn = _pg()
    cur  = conn.cursor()
    cur.execute("SELECT id, campaign_ids, campaign_list_map FROM vicidial_configs WHERE tenant_id=%s", (tenant_uuid,))
    row = cur.fetchone()
    if row:
        # Merge: conservar campañas existentes + agregar las nuevas
        existing_ids  = row[1] or []
        existing_map  = row[2] or {}
        merged_ids    = list(dict.fromkeys(existing_ids + campaign_ids))  # preserva orden, elimina dupes
        merged_map    = {**existing_map, **campaign_list_map}             # nuevas listas sobreescriben solo si se pasan
        cur.execute("""
            UPDATE vicidial_configs
            SET campaign_ids=%s, campaign_list_map=%s, sync_day=%s, updated_at=NOW()
            WHERE tenant_id=%s
        """, (json.dumps(merged_ids), json.dumps(merged_map), sync_day, tenant_uuid))
    else:
        cur.execute("""
            INSERT INTO vicidial_configs
                (id, tenant_id, api_url, api_user, api_pass,
                 campaign_ids, campaign_list_map, sync_day, is_active, created_at, updated_at)
            VALUES
                (gen_random_uuid(), %s, '', '', '',
                 %s, %s, %s, true, NOW(), NOW())
        """, (tenant_uuid, json.dumps(campaign_ids), json.dumps(campaign_list_map), sync_day))
    conn.commit()
    cur.close(); conn.close()


@router.post("/tenants/sync")
def admin_sync_tenant(payload: dict, authorization: Optional[str] = Header(None)):
    """
    Registra un tenant de ViciDial en BRICK.
    - Crea auth tenant + admin user en 8001 (PostgreSQL).
    - Guarda campaign_list_map y sync_day en vicidial_configs.
    """
    tenant_name    = str(payload.get("tenant_name",     "")).strip()
    subdomain      = str(payload.get("subdomain",       "")).strip().lower()
    admin_email    = str(payload.get("admin_email",     "")).strip()
    admin_password = str(payload.get("admin_password",  "")).strip()
    admin_first    = str(payload.get("admin_first_name","")).strip()
    admin_last     = str(payload.get("admin_last_name", "")).strip()
    campaigns      = payload.get("campaigns", [])  # [{campaign_id, list_ids: []}]

    if not all([tenant_name, subdomain, admin_email, admin_password, admin_first, admin_last]):
        return {"ok": False, "error": "Faltan campos requeridos"}
    if not campaigns:
        return {"ok": False, "error": "Selecciona al menos una campaña"}

    campaign_ids = [
        str(c.get("campaign_id", "")).strip().upper()
        for c in campaigns
        if c.get("campaign_id")
    ]
    # {"IBFEO": ["806", "807"], ...}
    campaign_list_map = {
        str(c.get("campaign_id", "")).strip().upper(): [str(l).strip() for l in c.get("list_ids", []) if l]
        for c in campaigns
        if c.get("campaign_id")
    }

    # Auto-asignar sync_day antes de crear (round-robin sobre tenants existentes)
    try:
        sync_day = _next_sync_day()
    except Exception:
        sync_day = "thu"

    # ── Crear tenant + admin user en 8001 ────────────────────────────────────
    try:
        auth_resp = http.post(
            f"{AUTH_BASE_URL}/api/tenants",
            json={
                "name":             tenant_name,
                "subdomain":        subdomain,
                "industry":         "rei",
                "primary_color":    "#2563EB",
                "max_seats":        10,
                "campaign_ids":     campaign_ids,
                "admin_email":      admin_email,
                "admin_password":   admin_password,
                "admin_first_name": admin_first,
                "admin_last_name":  admin_last,
            },
            headers={"Authorization": authorization or ""},
            timeout=15,
        )
        if auth_resp.status_code not in (200, 201):
            return {"ok": False, "error": f"Auth error: {auth_resp.text}"}
    except Exception as e:
        return {"ok": False, "error": f"No se pudo conectar al auth backend: {str(e)}"}

    # ── Guardar campaign_list_map + sync_day en vicidial_configs ─────────────
    try:
        tenant_uuid = auth_resp.json().get("id")
        if tenant_uuid:
            _pg_update_vicidial_config(tenant_uuid, campaign_ids, campaign_list_map, sync_day)
    except Exception as e:
        # No es fatal — tenant creado, config se puede editar luego
        return {
            "ok":               True,
            "tenant_name":      tenant_name,
            "subdomain":        subdomain,
            "sync_day":         sync_day,
            "campaigns_synced": [{"campaign_id": cid} for cid in campaign_ids],
            "warning":          f"Tenant creado pero no se pudo guardar campaign_list_map: {str(e)}",
        }

    return {
        "ok":               True,
        "tenant_name":      tenant_name,
        "subdomain":        subdomain,
        "sync_day":         sync_day,
        "campaigns_synced": [{"campaign_id": cid, "list_ids": campaign_list_map.get(cid, [])} for cid in campaign_ids],
    }


# ─── Scripts — se quedan en SQLite (son config de BRICK, no de auth) ─────────

def _init_script_library(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS scripts (
            id         TEXT PRIMARY KEY,
            name       TEXT NOT NULL,
            file_type  TEXT NOT NULL DEFAULT 'drawio',
            content    TEXT NOT NULL DEFAULT '',
            created_at TEXT,
            updated_at TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS script_assignments (
            script_id   TEXT NOT NULL,
            campaign_id TEXT NOT NULL,
            PRIMARY KEY (script_id, campaign_id)
        )
    """)


# ── List all scripts in library ───────────────────────────────────────────────
@router.get("/scripts/library")
def admin_list_scripts():
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    _init_script_library(cur)
    conn.commit()
    cur.execute("SELECT id, name, file_type, created_at, updated_at FROM scripts ORDER BY created_at DESC")
    rows = cur.fetchall()
    result = []
    for (sid, name, file_type, created_at, updated_at) in rows:
        cur.execute("SELECT campaign_id FROM script_assignments WHERE script_id=?", (sid,))
        campaigns = [r[0] for r in cur.fetchall()]
        result.append({
            "id":         sid,
            "name":       name,
            "file_type":  file_type,
            "campaigns":  campaigns,
            "created_at": created_at,
            "updated_at": updated_at,
        })
    conn.close()
    return result


# ── Import a new script (drawio/xml/pdf/jpg/png) ──────────────────────────────
@router.post("/scripts/library/import")
async def admin_import_script(
    file: UploadFile = File(...),
    name: str = Form(...),
):
    content_bytes = await file.read()
    filename = (file.filename or "").lower()

    if filename.endswith(".json"):
        try:
            script_dict = json.loads(content_bytes.decode("utf-8"))
        except Exception:
            return {"ok": False, "error": "JSON inválido"}
        content   = json.dumps(script_dict, ensure_ascii=False)
        file_type = "drawio"
    elif filename.endswith(".drawio") or filename.endswith(".xml"):
        try:
            xml_str = content_bytes.decode("utf-8")
        except Exception:
            return {"ok": False, "error": "Archivo no es UTF-8 válido"}
        try:
            script_dict = parse_drawio(xml_str)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        content   = json.dumps(script_dict, ensure_ascii=False)
        file_type = "drawio"
    elif filename.endswith(".pdf"):
        content   = base64.b64encode(content_bytes).decode("utf-8")
        file_type = "pdf"
    elif filename.endswith(".jpg") or filename.endswith(".jpeg"):
        content   = base64.b64encode(content_bytes).decode("utf-8")
        file_type = "jpg"
    elif filename.endswith(".png"):
        content   = base64.b64encode(content_bytes).decode("utf-8")
        file_type = "png"
    else:
        return {"ok": False, "error": "Formato no soportado. Use .drawio, .xml, .pdf, .jpg o .png"}

    script_id = str(_uuid.uuid4())
    now       = dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    _init_script_library(cur)
    cur.execute(
        "INSERT INTO scripts (id, name, file_type, content, created_at, updated_at) VALUES (?,?,?,?,?,?)",
        (script_id, name.strip(), file_type, content, now, now),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "id": script_id, "name": name.strip(), "file_type": file_type}


# ── Serve raw bytes for PDF/image scripts ─────────────────────────────────────
@router.get("/scripts/library/{script_id}/content")
def admin_script_raw_content(script_id: str):
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    _init_script_library(cur)
    cur.execute("SELECT file_type, content FROM scripts WHERE id=?", (script_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Script no encontrado")
    file_type, content = row
    media = {
        "pdf": "application/pdf",
        "jpg": "image/jpeg",
        "png": "image/png",
    }.get(file_type, "application/octet-stream")
    return Response(content=base64.b64decode(content), media_type=media)


# ── Assign / update campaign assignments ──────────────────────────────────────
@router.put("/scripts/library/{script_id}/assign")
def admin_assign_script(script_id: str, payload: dict):
    campaign_ids = [str(c).strip().upper() for c in payload.get("campaign_ids", []) if c]
    now  = dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    _init_script_library(cur)
    cur.execute("DELETE FROM script_assignments WHERE script_id=?", (script_id,))
    for cid in campaign_ids:
        cur.execute(
            "INSERT OR IGNORE INTO script_assignments (script_id, campaign_id) VALUES (?,?)",
            (script_id, cid),
        )
    cur.execute("UPDATE scripts SET updated_at=? WHERE id=?", (now, script_id))
    conn.commit()
    conn.close()
    return {"ok": True, "script_id": script_id, "campaigns": campaign_ids}


# ── Delete a script and its assignments ───────────────────────────────────────
@router.delete("/scripts/library/{script_id}")
def admin_delete_script(script_id: str):
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    _init_script_library(cur)
    cur.execute("DELETE FROM script_assignments WHERE script_id=?", (script_id,))
    cur.execute("DELETE FROM scripts WHERE id=?", (script_id,))
    conn.commit()
    deleted = cur.rowcount
    conn.close()
    return {"ok": deleted > 0}


# ── All ViciDial campaigns (for assignment UI) ────────────────────────────────
@router.get("/vici/campaigns/all")
def admin_vici_all_campaigns():
    try:
        conn = get_connection()
        cur  = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT campaign_id, campaign_name, active FROM vicidial_campaigns ORDER BY campaign_name"
        )
        rows = cur.fetchall()
        cur.close(); conn.close()
    except Exception as e:
        return {"error": str(e), "campaigns": []}
    return {"campaigns": [
        {"campaign_id": c["campaign_id"], "campaign_name": c["campaign_name"], "active": c["active"] == "Y"}
        for c in rows
    ]}


@router.get("/scripts/{campaign_id}")
def admin_get_script(campaign_id: str):
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    _init_script_library(cur)
    _init_scripts(cur)
    conn.commit()

    # Check new library — most recently updated script assigned to this campaign
    cur.execute("""
        SELECT s.id, s.name, s.file_type, s.content
        FROM   scripts s
        JOIN   script_assignments sa ON sa.script_id = s.id
        WHERE  sa.campaign_id = ?
        ORDER  BY s.updated_at DESC
        LIMIT  1
    """, (campaign_id.upper(),))
    row = cur.fetchone()
    if row:
        sid, name, file_type, content = row
        conn.close()
        if file_type == "drawio":
            return {"campaign_id": campaign_id.upper(), "script": content,
                    "script_id": sid, "script_name": name, "file_type": "drawio"}
        else:
            return {"campaign_id": campaign_id.upper(), "script": None,
                    "script_id": sid, "script_name": name, "file_type": file_type,
                    "content_url": f"/api/admin/scripts/library/{sid}/content"}

    # Fallback: old campaign_scripts table
    cur.execute(
        "SELECT script, updated_at FROM campaign_scripts WHERE campaign_id=?",
        (campaign_id.upper(),),
    )
    row = cur.fetchone()
    conn.close()
    if row:
        return {"campaign_id": campaign_id.upper(), "script": row[0],
                "updated_at": row[1], "file_type": "drawio"}
    return {"campaign_id": campaign_id.upper(), "script": "", "updated_at": None, "file_type": "drawio"}


@router.put("/scripts/{campaign_id}")
def admin_save_script(campaign_id: str, payload: dict):
    script = str(payload.get("script", ""))
    now    = dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn   = sqlite3.connect(DB_PATH)
    cur    = conn.cursor()
    _init_scripts(cur)
    cur.execute(
        "INSERT OR REPLACE INTO campaign_scripts (campaign_id, script, updated_at) VALUES (?,?,?)",
        (campaign_id.upper(), script, now),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "campaign_id": campaign_id.upper(), "updated_at": now}


@router.post("/scripts/{campaign_id}/import-drawio")
async def admin_import_drawio(campaign_id: str, file: UploadFile = File(...)):
    """
    Recibe un archivo .drawio, lo parsea y guarda el script en SQLite.
    El JSON guardado tiene el mismo formato que ReactFlow usa — compatible con Agent.tsx.
    """
    content = await file.read()
    try:
        xml_str = content.decode("utf-8")
    except Exception:
        return {"ok": False, "error": "El archivo no es UTF-8 válido"}

    try:
        script_dict = parse_drawio(xml_str)
    except ValueError as e:
        return {"ok": False, "error": str(e)}

    # Guardar en formato ReactFlow-compatible que Agent.tsx ya entiende
    # { nodes: [{id, data: ScriptNode}], edges: [] }
    # Pero también guardamos el dict plano — Agent.tsx acepta ambos formatos
    script_json = json.dumps(script_dict, ensure_ascii=False)
    now = dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    _init_scripts(cur)
    cur.execute(
        "INSERT OR REPLACE INTO campaign_scripts (campaign_id, script, updated_at) VALUES (?,?,?)",
        (campaign_id.upper(), script_json, now),
    )
    conn.commit()
    conn.close()

    return {
        "ok":          True,
        "campaign_id": campaign_id.upper(),
        "nodes":       len(script_dict),
        "updated_at":  now,
        "preview":     {k: v["section"] for k, v in script_dict.items()},
    }
