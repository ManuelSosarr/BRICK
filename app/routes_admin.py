import sqlite3
import datetime as dt
from fastapi import APIRouter
from app.vici_connector import get_connection

router = APIRouter()

DB_PATH = "C:/Users/sosai/BRICK/vicidial.db"


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
    cur.execute("INSERT OR IGNORE INTO tenants (tenant_id, tenant_name, campaign_id) VALUES ('bossbuy','BossBuy','IBFEO')")


def _clean(v):
    """Convert Python datetime/date to string for MySQL re-insert."""
    if isinstance(v, dt.datetime):
        return v.strftime('%Y-%m-%d %H:%M:%S')
    if isinstance(v, dt.date):
        return v.strftime('%Y-%m-%d')
    return v


# ─── Tenant CRUD ──────────────────────────────────────────────────────────────

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
        return {"ok": False, "error": f"Tenant '{tenant_id}' not found"}
    new_active = 0 if row[0] == 1 else 1
    cur.execute("UPDATE tenants SET active=? WHERE tenant_id=?", (new_active, tenant_id))
    conn.commit()
    conn.close()
    return {"ok": True, "tenant_id": tenant_id, "active": bool(new_active)}


# ─── Provision — validate (V19 preview) ──────────────────────────────────────

@router.post("/provision/validate")
def admin_provision_validate(payload: dict):
    campaigns = payload.get("campaigns", [])
    errors = []

    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)

        for camp in campaigns:
            cid        = str(camp.get("campaign_id", "")).strip().upper()
            clone_from = str(camp.get("clone_from",  "")).strip()
            tenant_id  = str(camp.get("tenant_id",   "")).strip().lower()

            if not cid:
                errors.append("Campaign ID vacío"); continue

            # Campaign must not already exist
            cur.execute("SELECT campaign_id FROM vicidial_campaigns WHERE campaign_id=%s", (cid,))
            if cur.fetchone():
                errors.append(f"Campaña '{cid}' ya existe en ViciDial")

            # Clone source must exist
            if clone_from:
                cur.execute("SELECT campaign_id FROM vicidial_campaigns WHERE campaign_id=%s", (clone_from,))
                if not cur.fetchone():
                    errors.append(f"Campaña fuente '{clone_from}' no existe")

            # Tenant must not already exist in SQLite
            sc = sqlite3.connect(DB_PATH)
            sc_cur = sc.cursor()
            sc_cur.execute("SELECT tenant_id FROM tenants WHERE tenant_id=?", (tenant_id,))
            if sc_cur.fetchone():
                errors.append(f"Tenant ID '{tenant_id}' ya existe en BRICK")
            sc.close()

            # List IDs must not already exist
            for lst in camp.get("lists", []):
                lid = lst.get("list_id")
                if lid:
                    cur.execute("SELECT list_id FROM vicidial_lists WHERE list_id=%s", (int(lid),))
                    if cur.fetchone():
                        errors.append(f"List ID {lid} ya existe en ViciDial")

        cur.close()
        conn.close()

    except Exception as e:
        errors.append(f"Error de conexión: {str(e)}")

    return {"valid": len(errors) == 0, "errors": errors}


# ─── Provision — execute ──────────────────────────────────────────────────────

@router.post("/provision")
def admin_provision(payload: dict):
    client_name = str(payload.get("client_name", "")).strip()
    campaigns   = payload.get("campaigns", [])

    if not client_name or not campaigns:
        return {"ok": False, "errors": ["client_name y campaigns son requeridos"], "results": []}

    results = []
    errors  = []

    try:
        conn = get_connection()
        cur  = conn.cursor(dictionary=True)

        for camp in campaigns:
            cid        = str(camp.get("campaign_id",   "")).strip().upper()
            cname      = str(camp.get("campaign_name", "")).strip()[:40]
            clone_from = str(camp.get("clone_from",    "IBFEO")).strip()
            tenant_id  = str(camp.get("tenant_id",     "")).strip().lower()
            lists      = camp.get("lists", [])

            if not cid or not cname or not tenant_id:
                errors.append(f"Datos incompletos para campaña '{cid}'"); continue

            # ── Clone campaign ────────────────────────────────────────────────
            cur.execute("SELECT * FROM vicidial_campaigns WHERE campaign_id=%s", (clone_from,))
            source = cur.fetchone()
            if not source:
                errors.append(f"Campaña fuente '{clone_from}' no encontrada"); continue

            # Override campaign-specific fields
            source["campaign_id"]           = cid
            source["campaign_name"]         = cname
            source["active"]                = "Y"
            source["campaign_changedate"]   = dt.datetime.now()
            source["campaign_logindate"]    = None
            source["campaign_calldate"]     = None
            source["campaign_stats_refresh"]= "N"

            cols        = list(source.keys())
            cols_str    = ", ".join([f"`{c}`" for c in cols])
            placeholders= ", ".join(["%s"] * len(cols))
            values      = [_clean(source[c]) for c in cols]

            insert_cur = conn.cursor()
            insert_cur.execute(
                f"INSERT INTO vicidial_campaigns ({cols_str}) VALUES ({placeholders})", values
            )

            # ── Create lists ──────────────────────────────────────────────────
            lists_created = []
            for lst in lists:
                lid   = lst.get("list_id", "")
                lname = str(lst.get("list_name", "")).strip()
                if not lid or not lname:
                    continue
                insert_cur.execute("""
                    INSERT INTO vicidial_lists
                        (list_id, list_name, campaign_id, active, list_changedate)
                    VALUES (%s, %s, %s, 'Y', NOW())
                """, (int(lid), lname, cid))
                lists_created.append({"list_id": int(lid), "list_name": lname})

            conn.commit()
            insert_cur.close()

            # ── Save tenant to SQLite ─────────────────────────────────────────
            sc = sqlite3.connect(DB_PATH)
            sc_cur = sc.cursor()
            _init_tenants(sc_cur)
            sc_cur.execute(
                "INSERT OR IGNORE INTO tenants (tenant_id, tenant_name, campaign_id, role, active) VALUES (?,?,?,'client',1)",
                (tenant_id, cname, cid)
            )
            sc.commit()
            sc.close()

            results.append({
                "campaign_id":   cid,
                "campaign_name": cname,
                "tenant_id":     tenant_id,
                "lists":         lists_created,
            })

        cur.close()
        conn.close()

    except Exception as e:
        errors.append(f"DB Error: {str(e)}")

    return {"ok": len(errors) == 0 and len(results) > 0, "results": results, "errors": errors}
