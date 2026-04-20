import sqlite3
import subprocess
import threading
import logging
import time as time_module
from datetime import datetime
from fastapi import APIRouter, Query
from app.vici_connector import get_connection

logger = logging.getLogger(__name__)
router = APIRouter()

DB_PATH = "C:/Users/sosai/BRICK/vicidial.db"

try:
    import pytz
    EST = pytz.timezone("America/New_York")
except ImportError:
    EST = None

VICI_HOST = "root@144.126.146.250"
VICI_KEY  = r"C:\Users\sosai\.ssh\vicidial_key"
AUTODIAL  = "/usr/share/astguiclient/AST_VDauto_dial.pl"

# ── Config helpers ────────────────────────────────────────────────────────────

def _cfg_key(campaign_id: str, key: str) -> str:
    return f"{key}__{campaign_id}"

def get_copilot_config(campaign_id: str, key: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS copilot_config (key TEXT PRIMARY KEY, value TEXT)")
    cur.execute("SELECT value FROM copilot_config WHERE key=?", (_cfg_key(campaign_id, key),))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None

def set_copilot_config(campaign_id: str, key: str, value):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS copilot_config (key TEXT PRIMARY KEY, value TEXT)")
    cur.execute("INSERT OR REPLACE INTO copilot_config VALUES (?,?)", (_cfg_key(campaign_id, key), str(value)))
    conn.commit()
    conn.close()

def _get_campaign_for_tenant(tenant_id: str) -> str | None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT campaign_id FROM tenants WHERE tenant_id=? AND active=1", (tenant_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if (row and row[0]) else None

def _ssh(remote_cmd: str):
    subprocess.Popen([
        "ssh", "-i", VICI_KEY,
        "-o", "StrictHostKeyChecking=no",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=10",
        VICI_HOST, remote_cmd
    ])

# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/status")
def copilot_status(tenant_id: str = Query(...)):
    campaign_id = _get_campaign_for_tenant(tenant_id)
    if not campaign_id:
        return {"error": f"No campaign assigned to tenant '{tenant_id}'"}
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)

        # Estado del Remote Agent
        cur.execute(
            "SELECT status FROM vicidial_remote_agents WHERE campaign_id=%s LIMIT 1",
            (campaign_id,)
        )
        agent = cur.fetchone()

        # KPIs del día
        cur.execute("""
            SELECT
                COUNT(*) as total_calls,
                SUM(CASE WHEN status='AL'                         THEN 1 ELSE 0 END) as answered,
                SUM(CASE WHEN status IN ('NA','AB','PWORK','N')   THEN 1 ELSE 0 END) as possible_working,
                SUM(CASE WHEN status IN ('DROP','PDROP','AA','EXCLUD','DNC','DNCC') THEN 1 ELSE 0 END) as excluded
            FROM vicidial_log
            WHERE campaign_id=%s AND call_date >= CURDATE()
        """, (campaign_id,))
        kpis = cur.fetchone()
        cur.close()
        conn.close()

        return {
            "tenant_id":        tenant_id,
            "campaign_id":      campaign_id,
            "agent_status":     agent["status"] if agent else "INACTIVE",
            "total_calls":      int(kpis["total_calls"] or 0),
            "answered":         int(kpis["answered"] or 0),
            "possible_working": int(kpis["possible_working"] or 0),
            "excluded":         int(kpis["excluded"] or 0),
            "pushed_today":     int(get_copilot_config(campaign_id, "pushed_today") or 0),
            "manual_stop":      get_copilot_config(campaign_id, "manual_stop") or "false",
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

    new_status  = "ACTIVE" if action == "START" else "INACTIVE"
    manual_stop = "false"  if action == "START" else "true"

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

    set_copilot_config(campaign_id, "manual_stop", manual_stop)
    if action == "START":
        set_copilot_config(campaign_id, "pushed_today", "0")
        _ssh(f"nohup {AUTODIAL} --campaign={campaign_id} --loop > /dev/null 2>&1 &")
    else:
        _ssh(f"pkill -f '{AUTODIAL} --campaign={campaign_id}'; echo done")

    logger.info("copilot toggle %s campaign=%s", action, campaign_id)
    return {"ok": affected > 0, "status": new_status}


# ── Background workers ────────────────────────────────────────────────────────

# Campaign and dest list are configurable here — no DB config UI yet
SOURCE_CAMPAIGN = "IBFEO"
DEST_LIST_ID    = 806     # Lista IBFLP/806 donde van los AL

def copilot_push_worker():
    """Every 30s: push AL leads from the last 35s to the destination list."""
    while True:
        try:
            now = datetime.now(EST) if EST else datetime.now()
            hour = now.hour
            manual_stop = get_copilot_config(SOURCE_CAMPAIGN, "manual_stop")

            if 7 <= hour < 15 and manual_stop != "true":
                conn = get_connection()
                cur  = conn.cursor(dictionary=True)

                # AL leads from last 35 seconds not already in dest list
                cur.execute("""
                    SELECT DISTINCT vl.lead_id
                    FROM vicidial_log vlog
                    JOIN vicidial_list vl ON vlog.lead_id = vl.lead_id
                    WHERE vlog.campaign_id = %s
                      AND vlog.status = 'AL'
                      AND vlog.call_date >= NOW() - INTERVAL 35 SECOND
                      AND vl.list_id != %s
                """, (SOURCE_CAMPAIGN, DEST_LIST_ID))
                leads = cur.fetchall()

                if leads:
                    lead_ids = [str(l["lead_id"]) for l in leads]
                    placeholders = ",".join(["%s"] * len(lead_ids))
                    cur.execute(f"""
                        UPDATE vicidial_list
                        SET list_id=%s, status='NEW',
                            called_since_last_reset='N', called_count=0
                        WHERE lead_id IN ({placeholders})
                    """, [DEST_LIST_ID] + lead_ids)
                    conn.commit()

                    current = int(get_copilot_config(SOURCE_CAMPAIGN, "pushed_today") or 0)
                    set_copilot_config(SOURCE_CAMPAIGN, "pushed_today", str(current + len(leads)))
                    logger.info("copilot pushed %d AL leads to list %s", len(leads), DEST_LIST_ID)

                cur.close()
                conn.close()

        except Exception as e:
            logger.warning("copilot_push_worker error: %s", e)

        time_module.sleep(30)


def copilot_schedule_worker():
    """Auto-STOP at 3pm EST if not already manually stopped."""
    while True:
        try:
            now = datetime.now(EST) if EST else datetime.now()
            if now.hour >= 15:
                manual_stop = get_copilot_config(SOURCE_CAMPAIGN, "manual_stop")
                if manual_stop != "true":
                    conn = get_connection()
                    cur  = conn.cursor()
                    cur.execute(
                        "UPDATE vicidial_remote_agents SET status='INACTIVE' WHERE campaign_id=%s",
                        (SOURCE_CAMPAIGN,)
                    )
                    conn.commit()
                    cur.close()
                    conn.close()
                    set_copilot_config(SOURCE_CAMPAIGN, "manual_stop", "true")
                    logger.info("copilot auto-stopped campaign=%s at 3pm EST", SOURCE_CAMPAIGN)
        except Exception as e:
            logger.warning("copilot_schedule_worker error: %s", e)

        time_module.sleep(60)


threading.Thread(target=copilot_push_worker,    daemon=True).start()
threading.Thread(target=copilot_schedule_worker, daemon=True).start()
