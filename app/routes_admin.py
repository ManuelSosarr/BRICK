import sqlite3
import datetime as dt
import requests as http
from fastapi import APIRouter, Header
from typing import Optional
from app.vici_connector import get_connection

router = APIRouter()

DB_PATH       = "C:/Users/sosai/BRICK/vicidial.db"
AUTH_BASE_URL = "http://localhost:8001"


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _init_tenants(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tenants (
            tenant_id   TEXT PRIMARY KEY,
            tenant_name TEXT NOT NULL,
            campaign_id TEXT,
            role        TEXT DEFAULT 'client',
            active      INTEGER DEFAULT 1
        )
    """)
    # auto-migrate from burner_tenants if exists
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='burner_tenants'")
    if cur.fetchone():
        cur.execute("SELECT tenant_id, tenant_name, campaign_id, active FROM burner_tenants")
        for r in cur.fetchall():
            cur.execute(
                "INSERT OR IGNORE INTO tenants (tenant_id, tenant_name, campaign_id, active) VALUES (?,?,?,?)", r
            )
    cur.execute(
        "INSERT OR IGNORE INTO tenants (tenant_id, tenant_name, campaign_id) VALUES ('bossbuy','BossBuy','IBFEO')"
    )


def _init_scripts(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS campaign_scripts (
            campaign_id TEXT PRIMARY KEY,
            script      TEXT NOT NULL DEFAULT '',
            updated_at  TEXT
        )
    """)


# ─── Tenants CRUD ─────────────────────────────────────────────────────────────

@router.get("/tenants")
def admin_list_tenants():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    _init_tenants(cur)
    conn.commit()
    cur.execute("SELECT tenant_id, tenant_name, role, campaign_id, active FROM tenants ORDER BY role DESC, tenant_name")
    rows = cur.fetchall()
    conn.close()
    return [
        {"tenant_id": r[0], "tenant_name": r[1], "role": r[2], "campaign_id": r[3], "active": bool(r[4])}
        for r in rows
    ]


@router.post("/tenants/{tenant_id}/toggle")
def admin_toggle_tenant(tenant_id: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT active FROM tenants WHERE tenant_id=?", (tenant_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return {"ok": False, "error": f"Tenant '{tenant_id}' no encontrado"}
    new_active = 0 if row[0] == 1 else 1
    cur.execute("UPDATE tenants SET active=? WHERE tenant_id=?", (new_active, tenant_id))
    conn.commit()
    conn.close()
    return {"ok": True, "tenant_id": tenant_id, "active": bool(new_active)}


@router.delete("/tenants/{tenant_id}")
def admin_delete_tenant(tenant_id: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM tenants WHERE tenant_id=?", (tenant_id,))
    conn.commit()
    deleted = cur.rowcount
    conn.close()
    return {"ok": deleted > 0, "tenant_id": tenant_id}


# ─── Sync — ViciDial campaigns not yet in BRICK ───────────────────────────────

@router.get("/vici/campaigns/unassigned")
def admin_vici_unassigned():
    # Campaigns already registered in SQLite
    sc = sqlite3.connect(DB_PATH)
    sc_cur = sc.cursor()
    _init_tenants(sc_cur)
    sc.commit()
    sc_cur.execute("SELECT campaign_id FROM tenants WHERE campaign_id IS NOT NULL")
    assigned = {row[0] for row in sc_cur.fetchall()}
    sc.close()

    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT campaign_id, campaign_name, active FROM vicidial_campaigns ORDER BY campaign_name"
        )
        all_campaigns = cur.fetchall()
        cur.close()
        conn.close()
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


# ─── Sync — register tenant in BRICK ─────────────────────────────────────────

@router.post("/tenants/sync")
def admin_sync_tenant(payload: dict, authorization: Optional[str] = Header(None)):
    """
    Register an existing ViciDial tenant in BRICK.
    ViciDial campaigns/lists/DIDs are already set up manually.
    This endpoint:
      1. Creates auth tenant + admin user in 8001 (PostgreSQL)
      2. Creates SQLite tenant rows (one per campaign)
    """
    tenant_name    = str(payload.get("tenant_name",     "")).strip()
    subdomain      = str(payload.get("subdomain",       "")).strip().lower()
    admin_email    = str(payload.get("admin_email",     "")).strip()
    admin_password = str(payload.get("admin_password",  "")).strip()
    admin_first    = str(payload.get("admin_first_name","")).strip()
    admin_last     = str(payload.get("admin_last_name", "")).strip()
    campaigns      = payload.get("campaigns", [])  # [{campaign_id, tenant_id}]

    if not all([tenant_name, subdomain, admin_email, admin_password, admin_first, admin_last]):
        return {"ok": False, "error": "Faltan campos requeridos"}
    if not campaigns:
        return {"ok": False, "error": "Selecciona al menos una campaña"}

    # ── Step 1: Create auth tenant + admin user ────────────────────────────────
    try:
        auth_resp = http.post(
            f"{AUTH_BASE_URL}/api/tenants",
            json={
                "name":             tenant_name,
                "subdomain":        subdomain,
                "industry":         "rei",
                "primary_color":    "#2563EB",
                "max_seats":        10,
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

    # ── Step 2: Save each campaign row to SQLite ───────────────────────────────
    sc = sqlite3.connect(DB_PATH)
    sc_cur = sc.cursor()
    _init_tenants(sc_cur)
    synced = []
    for camp in campaigns:
        cid = str(camp.get("campaign_id", "")).strip().upper()
        tid = str(camp.get("tenant_id",   "")).strip().lower()
        if cid and tid:
            sc_cur.execute(
                "INSERT OR IGNORE INTO tenants (tenant_id, tenant_name, campaign_id, role, active) VALUES (?,?,?,'client',1)",
                (tid, tenant_name, cid),
            )
            synced.append({"campaign_id": cid, "tenant_id": tid})
    sc.commit()
    sc.close()

    return {
        "ok":              True,
        "tenant_name":     tenant_name,
        "subdomain":       subdomain,
        "campaigns_synced": synced,
    }


# ─── Scripts ──────────────────────────────────────────────────────────────────

@router.get("/scripts/{campaign_id}")
def admin_get_script(campaign_id: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    _init_scripts(cur)
    conn.commit()
    cur.execute(
        "SELECT script, updated_at FROM campaign_scripts WHERE campaign_id=?",
        (campaign_id.upper(),),
    )
    row = cur.fetchone()
    conn.close()
    if row:
        return {"campaign_id": campaign_id.upper(), "script": row[0], "updated_at": row[1]}
    return {"campaign_id": campaign_id.upper(), "script": "", "updated_at": None}


@router.put("/scripts/{campaign_id}")
def admin_save_script(campaign_id: str, payload: dict):
    script = str(payload.get("script", ""))
    now    = dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    _init_scripts(cur)
    cur.execute(
        "INSERT OR REPLACE INTO campaign_scripts (campaign_id, script, updated_at) VALUES (?,?,?)",
        (campaign_id.upper(), script, now),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "campaign_id": campaign_id.upper(), "updated_at": now}
