import sqlite3
import subprocess
import logging
from datetime import datetime
from fastapi import APIRouter, Query
from app.vici_connector import get_connection
from app.routes_burner import get_campaign_for_tenant as _get_campaign_for_tenant

logger = logging.getLogger(__name__)
router = APIRouter()

DB_PATH   = "C:/Users/sosai/BRICK/vicidial.db"
VICI_HOST = "root@144.126.146.250"
VICI_KEY  = r"C:\Users\sosai\.ssh\vicidial_key"
AUTODIAL  = "/usr/share/astguiclient/AST_VDauto_dial.pl"

try:
    import pytz
    EST = pytz.timezone("America/New_York")
except ImportError:
    EST = None


# ── SQLite config helpers ─────────────────────────────────────────────────────

def _cfg_key(campaign_id: str, key: str) -> str:
    return f"{key}__{campaign_id}"

def _init_table(cur):
    cur.execute("CREATE TABLE IF NOT EXISTS copilot_config (key TEXT PRIMARY KEY, value TEXT)")

def get_copilot_config(campaign_id: str, key: str):
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    _init_table(cur)
    cur.execute("SELECT value FROM copilot_config WHERE key=?", (_cfg_key(campaign_id, key),))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None

def set_copilot_config(campaign_id: str, key: str, value):
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    _init_table(cur)
    cur.execute("INSERT OR REPLACE INTO copilot_config VALUES (?,?)",
                (_cfg_key(campaign_id, key), str(value)))
    conn.commit()
    conn.close()

def get_active_copilot_campaigns() -> list[str]:
    """All campaign_ids where copilot is running (copilot_active = 'true')."""
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    _init_table(cur)
    cur.execute(
        "SELECT key FROM copilot_config WHERE key LIKE 'copilot_active__%' AND value='true'"
    )
    rows = cur.fetchall()
    conn.close()
    return [r[0].replace("copilot_active__", "") for r in rows]


def _ssh(remote_cmd: str):
    subprocess.Popen([
        "ssh", "-i", VICI_KEY,
        "-o", "StrictHostKeyChecking=no",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=10",
        VICI_HOST, remote_cmd
    ])


# ── Core push logic (used by endpoint + scheduler) ────────────────────────────

def _run_push_for_campaign(campaign_id: str) -> int:
    """
    Move all AL leads in any list of `campaign_id` (except dest_list) to dest_list as NEW.
    Returns number of leads moved.
    """
    dest_list_id_str = get_copilot_config(campaign_id, "dest_list_id")
    if not dest_list_id_str:
        return 0

    dest_list_id = int(dest_list_id_str)

    conn = get_connection()
    cur  = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT lead_id FROM vicidial_list
        WHERE list_id IN (
            SELECT list_id FROM vicidial_lists WHERE campaign_id=%s
        )
        AND status = 'AL'
        AND list_id != %s
    """, (campaign_id, dest_list_id))
    leads = cur.fetchall()

    moved = 0
    if leads:
        lead_ids     = [str(l["lead_id"]) for l in leads]
        placeholders = ",".join(["%s"] * len(lead_ids))
        cur.execute(f"""
            UPDATE vicidial_list
            SET list_id=%s, status='NEW',
                called_since_last_reset='N', called_count=0
            WHERE lead_id IN ({placeholders})
        """, [dest_list_id] + lead_ids)
        conn.commit()
        moved = len(leads)
        current = int(get_copilot_config(campaign_id, "pushed_today") or 0)
        set_copilot_config(campaign_id, "pushed_today", str(current + moved))
        logger.info("copilot: moved %d AL leads → list %s (campaign %s)",
                    moved, dest_list_id, campaign_id)

    cur.close()
    conn.close()
    return moved


def run_push_for_tenant(tenant_id: str) -> int:
    """Push AL leads for a tenant. Called by /push-now endpoint."""
    campaign_id = _get_campaign_for_tenant(tenant_id)
    if not campaign_id:
        return 0
    return _run_push_for_campaign(campaign_id)


def _get_all_configured_campaigns() -> list[str]:
    """All campaign_ids that have a dest_list_id configured — regardless of copilot_active status."""
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    _init_table(cur)
    cur.execute("SELECT key FROM copilot_config WHERE key LIKE 'dest_list_id__%'")
    rows = cur.fetchall()
    conn.close()
    return [r[0].replace("dest_list_id__", "") for r in rows]


def run_copilot_push_all():
    """
    Push AL leads for ALL campaigns that have dest_list_id configured.
    Unconditional — no copilot_active check, no agent status check, no time gate.
    Called by APScheduler every 30s.
    """
    campaigns = _get_all_configured_campaigns()
    if not campaigns:
        return
    for campaign_id in campaigns:
        try:
            _run_push_for_campaign(campaign_id)
        except Exception as e:
            logger.warning("copilot scheduler error campaign=%s: %s", campaign_id, e)


def reset_pushed_today_all():
    """Reset pushed_today counter for all configured campaigns. Called at midnight EST."""
    for campaign_id in _get_all_configured_campaigns():
        try:
            set_copilot_config(campaign_id, "pushed_today", "0")
            logger.info("copilot: reset pushed_today for campaign=%s", campaign_id)
        except Exception as e:
            logger.warning("copilot midnight reset error campaign=%s: %s", campaign_id, e)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/status")
def copilot_status(tenant_id: str = Query(...)):
    campaign_id = _get_campaign_for_tenant(tenant_id)
    if not campaign_id:
        return {"error": f"No campaign assigned to tenant '{tenant_id}'"}
    try:
        conn = get_connection()
        cur  = conn.cursor(dictionary=True)

        cur.execute(
            "SELECT status FROM vicidial_remote_agents WHERE campaign_id=%s LIMIT 1",
            (campaign_id,)
        )
        agent = cur.fetchone()

        # Today's start in EST — avoids MySQL UTC timezone mismatch
        today_est = (datetime.now(EST) if EST else datetime.now()).strftime('%Y-%m-%d 00:00:00')

        cur.execute("""
            SELECT
                COUNT(*) as total_calls,
                SUM(CASE WHEN status='AL'                                            THEN 1 ELSE 0 END) as answered,
                SUM(CASE WHEN status IN ('NA','AB','PWORK','N')                      THEN 1 ELSE 0 END) as possible_working,
                SUM(CASE WHEN status IN ('DROP','PDROP','AA','EXCLUD','DNC','DNCC')  THEN 1 ELSE 0 END) as excluded,
                MAX(call_date) as last_call
            FROM vicidial_log
            WHERE campaign_id=%s AND call_date >= %s
        """, (campaign_id, today_est))
        kpis = cur.fetchone()
        cur.close()
        conn.close()

        dest_list_id = get_copilot_config(campaign_id, "dest_list_id") or ""

        return {
            "tenant_id":        tenant_id,
            "campaign_id":      campaign_id,
            "agent_status":     agent["status"] if agent else "INACTIVE",
            "total_calls":      int(kpis["total_calls"] or 0),
            "answered":         int(kpis["answered"] or 0),
            "possible_working": int(kpis["possible_working"] or 0),
            "excluded":         int(kpis["excluded"] or 0),
            "pushed_today":     int(get_copilot_config(campaign_id, "pushed_today") or 0),
            "copilot_active":   get_copilot_config(campaign_id, "copilot_active") == "true",
            "dest_list_id":     dest_list_id,
            "last_call":        str(kpis["last_call"]) if kpis["last_call"] else None,
        }
    except Exception as e:
        return {"error": str(e)}


@router.post("/toggle")
def copilot_toggle(payload: dict):
    tenant_id = str(payload.get("tenant_id", "")).strip()
    action    = str(payload.get("action", "")).upper()
    if not tenant_id:
        return {"ok": False, "error": "tenant_id required"}
    if action not in ("START", "STOP"):
        return {"ok": False, "error": "Invalid action. Use START or STOP."}

    campaign_id = _get_campaign_for_tenant(tenant_id)
    if not campaign_id:
        return {"ok": False, "error": f"No campaign assigned to tenant '{tenant_id}'"}

    if action == "START":
        dest_list_id = get_copilot_config(campaign_id, "dest_list_id")
        if not dest_list_id:
            return {"ok": False, "error": "Configura la lista destino antes de iniciar el Co-Pilot"}

    new_status = "ACTIVE" if action == "START" else "INACTIVE"
    try:
        conn = get_connection()
        cur  = conn.cursor()
        cur.execute(
            "UPDATE vicidial_remote_agents SET status=%s WHERE campaign_id=%s",
            (new_status, campaign_id)
        )
        conn.commit()
        affected = cur.rowcount
        cur.close()
        conn.close()
    except Exception as e:
        return {"ok": False, "error": f"DB error: {str(e)}"}

    if action == "START":
        set_copilot_config(campaign_id, "copilot_active", "true")
        set_copilot_config(campaign_id, "pushed_today",   "0")
        _ssh(f"nohup {AUTODIAL} --campaign={campaign_id} --loop > /dev/null 2>&1 &")
    else:
        set_copilot_config(campaign_id, "copilot_active", "false")
        _ssh(f"pkill -f '{AUTODIAL} --campaign={campaign_id}'; echo done")

    logger.info("copilot toggle %s campaign=%s", action, campaign_id)
    return {"ok": affected > 0, "status": new_status}


@router.post("/set-dest")
def copilot_set_dest(payload: dict):
    """Save the destination list for a tenant's Co-Pilot."""
    tenant_id    = str(payload.get("tenant_id", "")).strip()
    dest_list_id = str(payload.get("dest_list_id", "")).strip()
    if not tenant_id or not dest_list_id:
        return {"ok": False, "error": "tenant_id and dest_list_id required"}

    campaign_id = _get_campaign_for_tenant(tenant_id)
    if not campaign_id:
        return {"ok": False, "error": f"No campaign assigned to tenant '{tenant_id}'"}

    set_copilot_config(campaign_id, "dest_list_id", dest_list_id)
    logger.info("copilot set dest_list_id=%s campaign=%s", dest_list_id, campaign_id)
    return {"ok": True, "campaign_id": campaign_id, "dest_list_id": dest_list_id}


@router.get("/lists")
def copilot_lists(campaign_id: str = Query(...)):
    """Return active lists for a campaign (for the dest list picker)."""
    try:
        conn = get_connection()
        cur  = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT list_id, list_name FROM vicidial_lists WHERE campaign_id=%s AND active='Y' ORDER BY list_name",
            (campaign_id,)
        )
        lists = cur.fetchall()
        cur.close()
        conn.close()
        return lists
    except Exception as e:
        return {"error": str(e)}


@router.post("/push-now")
def copilot_push_now(payload: dict):
    """Manual push triggered by the frontend (fallback / on-demand)."""
    tenant_id = str(payload.get("tenant_id", "")).strip()
    if not tenant_id:
        return {"ok": False, "moved": 0, "error": "tenant_id required"}
    try:
        moved = run_push_for_tenant(tenant_id)
        return {"ok": True, "moved": moved}
    except Exception as e:
        logger.warning("copilot push-now error tenant=%s: %s", tenant_id, e)
        return {"ok": False, "moved": 0, "error": str(e)}
