import sqlite3
from fastapi import APIRouter
from app.vici_connector import get_connection

router = APIRouter()

DB_PATH = "C:/Users/sosai/BRICK/vicidial.db"


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


@router.post("/tenants")
def admin_create_tenant(payload: dict):
    tenant_id   = str(payload.get("tenant_id",   "")).strip().lower()
    tenant_name = str(payload.get("tenant_name", "")).strip()
    campaign_id = str(payload.get("campaign_id", "")).strip()

    if not tenant_id or not tenant_name or not campaign_id:
        return {"ok": False, "error": "tenant_id, tenant_name and campaign_id are required"}

    # Validate campaign exists in ViciDial
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT campaign_id FROM vicidial_campaigns WHERE campaign_id=%s LIMIT 1", (campaign_id,))
        if not cur.fetchone():
            conn.close()
            return {"ok": False, "error": f"Campaign '{campaign_id}' not found in ViciDial"}
        conn.close()
    except Exception as e:
        return {"ok": False, "error": f"ViciDial error: {str(e)}"}

    # Insert into SQLite
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        _init_tenants(cur)
        cur.execute("SELECT tenant_id FROM tenants WHERE tenant_id=?", (tenant_id,))
        if cur.fetchone():
            conn.close()
            return {"ok": False, "error": f"Tenant '{tenant_id}' already exists"}
        cur.execute(
            "INSERT INTO tenants (tenant_id, tenant_name, campaign_id, role, active) VALUES (?,?,?,'client',1)",
            (tenant_id, tenant_name, campaign_id)
        )
        conn.commit()
        conn.close()
        return {"ok": True, "tenant_id": tenant_id, "tenant_name": tenant_name, "campaign_id": campaign_id}
    except Exception as e:
        return {"ok": False, "error": str(e)}


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
