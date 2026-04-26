import threading
import time as time_module
import sqlite3
import csv
import io
import subprocess
import logging
from datetime import datetime, date
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from app.vici_connector import get_connection

logger = logging.getLogger(__name__)

VICI_HOST = "root@144.126.146.250"
VICI_KEY  = r"C:\Users\sosai\.ssh\vicidial_key"
AUTODIAL  = "/usr/share/astguiclient/AST_VDauto_dial.pl"

def _ssh(remote_cmd: str) -> tuple[int, str, str]:
    result = subprocess.run(
        ["ssh", "-i", VICI_KEY, "-o", "StrictHostKeyChecking=no",
         "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", VICI_HOST, remote_cmd],
        capture_output=True, text=True, timeout=15
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()

try:
    import pytz
    EST = pytz.timezone("America/New_York")
except ImportError:
    EST = None

router = APIRouter()

DB_PATH = "C:/Users/sosai/BRICK/vicidial.db"


# ─── Tenants table (tenant → campaign mapping) ────────────────────────────────

def _init_tenants(cur):
    """Create tenants table and auto-migrate data from burner_tenants if it exists."""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tenants (
            tenant_id   TEXT PRIMARY KEY,
            tenant_name TEXT NOT NULL,
            campaign_id TEXT,
            role        TEXT DEFAULT 'client',
            active      INTEGER DEFAULT 1
        )
    """)
    # Migrate from legacy burner_tenants if it exists
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='burner_tenants'")
    if cur.fetchone():
        cur.execute("SELECT tenant_id, tenant_name, campaign_id, active FROM burner_tenants")
        for r in cur.fetchall():
            cur.execute(
                "INSERT OR IGNORE INTO tenants (tenant_id, tenant_name, campaign_id, active) VALUES (?,?,?,?)", r
            )
    # Seed default tenants (INSERT OR IGNORE — safe to run on every startup)
    cur.executemany(
        "INSERT OR IGNORE INTO tenants (tenant_id, tenant_name, campaign_id) VALUES (?,?,?)",
        [
            ("bossbuy", "BossBuy", "IBFEO"),
            ("moveup",  "Moveup",  "CMUH"),
        ]
    )


def get_campaign_for_tenant(tenant_id: str) -> str | None:
    """Resolve tenant_id → campaign_id from SQLite tenants table."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    _init_tenants(cur)
    conn.commit()
    cur.execute("SELECT campaign_id FROM tenants WHERE tenant_id=? AND active=1", (tenant_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if (row and row[0]) else None


@router.get("/tenants")
def burner_tenants():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    _init_tenants(cur)
    conn.commit()
    cur.execute(
        "SELECT tenant_id, tenant_name, campaign_id FROM tenants WHERE active=1 AND campaign_id IS NOT NULL ORDER BY tenant_name"
    )
    rows = [{"tenant_id": r[0], "tenant_name": r[1], "campaign_id": r[2]} for r in cur.fetchall()]
    conn.close()
    return rows


@router.post("/tenants")
def upsert_burner_tenant(payload: dict):
    tenant_id   = str(payload.get("tenant_id", "")).strip()
    tenant_name = str(payload.get("tenant_name", "")).strip()
    campaign_id = str(payload.get("campaign_id", "")).strip()
    if not tenant_id or not tenant_name or not campaign_id:
        return {"ok": False, "error": "tenant_id, tenant_name and campaign_id required"}
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    _init_tenants(cur)
    cur.execute(
        "INSERT OR REPLACE INTO tenants (tenant_id, tenant_name, campaign_id, active) VALUES (?,?,?,1)",
        (tenant_id, tenant_name, campaign_id)
    )
    conn.commit()
    conn.close()
    return {"ok": True}


# ─── SQLite helpers (campaign-scoped keys) ────────────────────────────────────

def _cfg_key(campaign_id: str, key: str) -> str:
    return f"{key}__{campaign_id}"

def get_burner_config(campaign_id: str, key: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS burner_config (key TEXT PRIMARY KEY, value TEXT)")
    cur.execute("SELECT value FROM burner_config WHERE key=?", (_cfg_key(campaign_id, key),))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None

def set_burner_config(campaign_id: str, key: str, value):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS burner_config (key TEXT PRIMARY KEY, value TEXT)")
    cur.execute("INSERT OR REPLACE INTO burner_config VALUES (?,?)", (_cfg_key(campaign_id, key), str(value)))
    conn.commit()
    conn.close()

def get_active_burner_campaigns() -> list:
    """Return all campaign_ids that have been manually started at least once."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS burner_config (key TEXT PRIMARY KEY, value TEXT)")
    cur.execute("SELECT key FROM burner_config WHERE key LIKE 'first_start_done__%' AND value='true'")
    rows = cur.fetchall()
    conn.close()
    return [row[0].replace("first_start_done__", "") for row in rows]


# ─── Background watchdogs (multi-campaign) ────────────────────────────────────

def _process_hopper(campaign_id: str):
    start_date_str = get_burner_config(campaign_id, "start_date")
    if start_date_str:
        days_elapsed = (date.today() - date.fromisoformat(start_date_str)).days
        if days_elapsed >= 7:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("UPDATE vicidial_remote_agents SET status='INACTIVE' WHERE campaign_id=%s", (campaign_id,))
            conn.commit()
            conn.close()
            set_burner_config(campaign_id, "burned_complete", "true")
            set_burner_config(campaign_id, "list_complete", "true")
            return

    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT status FROM vicidial_remote_agents WHERE campaign_id=%s LIMIT 1", (campaign_id,))
    agent = cur.fetchone()
    if agent and agent["status"] == "ACTIVE":
        cur.execute("SELECT dialable_leads FROM vicidial_campaign_stats WHERE campaign_id=%s", (campaign_id,))
        stats = cur.fetchone()
        if stats and stats["dialable_leads"] == 0:
            # Check if any NEW or PWORK leads remain
            cur.execute("""
                SELECT COUNT(*) as remaining FROM vicidial_list
                WHERE list_id IN (SELECT list_id FROM vicidial_lists WHERE campaign_id=%s)
                AND status IN ('NEW', 'PWORK')
            """, (campaign_id,))
            remaining = cur.fetchone()["remaining"]
            if remaining == 0:
                # All leads burned through — mark list complete
                set_burner_config(campaign_id, "list_complete", "true")
            else:
                # Excluir leads PWORK con 5+ intentos
                cur.execute("""
                    UPDATE vicidial_list SET status='EXCLUD'
                    WHERE list_id IN (SELECT list_id FROM vicidial_lists WHERE campaign_id=%s)
                    AND status='PWORK' AND called_count >= 5
                """, (campaign_id,))
                conn.commit()
                # Reset PWORK leads so dialer can retry them
                cur.execute("""
                    UPDATE vicidial_list SET called_since_last_reset='N'
                    WHERE list_id IN (SELECT list_id FROM vicidial_lists WHERE campaign_id=%s)
                    AND status = 'PWORK' AND called_count < 5
                """, (campaign_id,))
                conn.commit()
    cur.close()
    conn.close()

def _process_schedule(campaign_id: str, hour: int):
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT status FROM vicidial_remote_agents WHERE campaign_id=%s LIMIT 1", (campaign_id,))
    agent = cur.fetchone()
    if agent:
        if agent["status"] == "ACTIVE" and (hour >= 20 or hour < 7):
            cur.execute("UPDATE vicidial_remote_agents SET status='INACTIVE' WHERE campaign_id=%s", (campaign_id,))
            conn.commit()
        elif agent["status"] == "INACTIVE":
            burned = get_burner_config(campaign_id, "burned_complete")
            manual_stop = get_burner_config(campaign_id, "manual_stop")
            if not burned and manual_stop != "true" and 7 <= hour < 20:
                cur.execute("UPDATE vicidial_remote_agents SET status='ACTIVE' WHERE campaign_id=%s", (campaign_id,))
                conn.commit()
    cur.close()
    conn.close()

def hopper_watchdog():
    while True:
        for cid in get_active_burner_campaigns():
            try:
                _process_hopper(cid)
            except Exception:
                pass
        time_module.sleep(60)

def schedule_watchdog():
    while True:
        try:
            now = datetime.now(EST) if EST else datetime.now()
            hour = now.hour
            for cid in get_active_burner_campaigns():
                try:
                    _process_schedule(cid, hour)
                except Exception:
                    pass
        except Exception:
            pass
        time_module.sleep(60)

threading.Thread(target=hopper_watchdog, daemon=True).start()
threading.Thread(target=schedule_watchdog, daemon=True).start()


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/status")
def burner_status(tenant_id: str = Query(...)):
    campaign_id = get_campaign_for_tenant(tenant_id)
    if not campaign_id:
        return {"error": f"No campaign assigned to tenant '{tenant_id}'"}
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT status FROM vicidial_remote_agents WHERE campaign_id=%s LIMIT 1", (campaign_id,))
        agent = cur.fetchone()
        cur.execute("SELECT calls_onemin, answering_machines_today, dialable_leads FROM vicidial_campaign_stats WHERE campaign_id=%s LIMIT 1", (campaign_id,))
        stats = cur.fetchone()
        cur.execute("SELECT status, last_update_time FROM vicidial_live_agents WHERE campaign_id=%s ORDER BY last_update_time DESC LIMIT 1", (campaign_id,))
        live = cur.fetchone()
        conn.close()
        return {
            "tenant_id":                tenant_id,
            "campaign_id":              campaign_id,
            "remote_agent_status":      agent["status"] if agent else "UNKNOWN",
            "calls_onemin":             stats["calls_onemin"] if stats else 0,
            "answering_machines_today": stats["answering_machines_today"] if stats else 0,
            "dialable_leads":           stats["dialable_leads"] if stats else 0,
            "live_agent_status":        live["status"] if live else "N/A",
            "last_update":              str(live["last_update_time"])[:19] if live else datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    except Exception as e:
        return {"error": str(e)}


@router.get("/weekly")
def burner_weekly(tenant_id: str = Query(...)):
    campaign_id = get_campaign_for_tenant(tenant_id)
    if not campaign_id:
        return {"error": f"No campaign assigned to tenant '{tenant_id}'"}
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)

        # Total leads in campaign lists
        cur.execute("""
            SELECT COUNT(*) as total FROM vicidial_list
            WHERE list_id IN (SELECT list_id FROM vicidial_lists WHERE campaign_id=%s)
        """, (campaign_id,))
        total = cur.fetchone()["total"]

        # Calls made in last 7 days (from call log)
        cur.execute("""
            SELECT COUNT(*) as dialed FROM vicidial_log
            WHERE campaign_id=%s AND call_date >= DATE_SUB(NOW(), INTERVAL 7 DAY)
        """, (campaign_id,))
        dialed = cur.fetchone()["dialed"]

        # Elegibles: all leads NOT in a terminal/excluded status
        cur.execute("""
            SELECT COUNT(*) as dialable FROM vicidial_list
            WHERE list_id IN (SELECT list_id FROM vicidial_lists WHERE campaign_id=%s)
            AND status NOT IN ('EXCLUD','AL','DNC','DNCC')
        """, (campaign_id,))
        dialable = cur.fetchone()["dialable"]

        # Excluidos: all excluded statuses
        cur.execute("""
            SELECT COUNT(*) as excluded FROM vicidial_list
            WHERE list_id IN (SELECT list_id FROM vicidial_lists WHERE campaign_id=%s)
            AND status IN ('EXCLUD','DNC','DNCC')
        """, (campaign_id,))
        excluded = cur.fetchone()["excluded"]

        # Contestaron (AL): count from vicidial_log — AL leads may have been pushed out of the list
        cur.execute("""
            SELECT COUNT(DISTINCT lead_id) as answered FROM vicidial_log
            WHERE campaign_id=%s
            AND call_date >= DATE_SUB(NOW(), INTERVAL 7 DAY)
            AND status='AL'
        """, (campaign_id,))
        answered = cur.fetchone()["answered"]

        conn.close()
        return {"total": total, "dialed": dialed, "dialable": dialable, "excluded": excluded, "answered": answered}
    except Exception as e:
        return {"error": str(e)}


@router.get("/minutes")
def burner_minutes(tenant_id: str = Query(...)):
    campaign_id = get_campaign_for_tenant(tenant_id)
    if not campaign_id:
        return {"error": f"No campaign assigned to tenant '{tenant_id}'"}
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT status, COUNT(*) as calls,
                   SUM(length_in_sec) as raw_seconds,
                   SUM(CEIL(length_in_sec / 60)) as billed_minutes
            FROM vicidial_log
            WHERE campaign_id=%s AND call_date >= DATE_SUB(NOW(), INTERVAL 7 DAY)
            GROUP BY status ORDER BY calls DESC
        """, (campaign_id,))
        breakdown = cur.fetchall()
        cur.execute("""
            SELECT COUNT(*) as total_calls,
                   SUM(length_in_sec) as total_raw_seconds,
                   SUM(CEIL(length_in_sec / 60)) as total_billed_minutes
            FROM vicidial_log
            WHERE campaign_id=%s AND call_date >= DATE_SUB(NOW(), INTERVAL 7 DAY)
        """, (campaign_id,))
        totals = cur.fetchone()
        cur.close()
        conn.close()
        total_billed = int(totals["total_billed_minutes"] or 0)
        return {
            "tenant_id": tenant_id,
            "campaign_id": campaign_id,
            "total_calls_all_statuses": totals["total_calls"] or 0,
            "total_raw_seconds_all_statuses": int(totals["total_raw_seconds"] or 0),
            "total_billed_minutes_all_statuses": total_billed,
            "note": "Billed minutes include ALL statuses — not just AL",
            "estimated_cost_usd": round(total_billed * 0.01, 2),
            "breakdown_by_status": [
                {"status": r["status"], "calls": r["calls"],
                 "raw_seconds": int(r["raw_seconds"] or 0),
                 "billed_minutes": int(r["billed_minutes"] or 0)}
                for r in breakdown
            ]
        }
    except Exception as e:
        return {"error": str(e)}


@router.post("/toggle")
def burner_toggle(payload: dict):
    tenant_id   = str(payload.get("tenant_id", "")).strip()
    action      = str(payload.get("action", "")).upper()
    if not tenant_id:
        return {"ok": False, "response": "tenant_id required"}
    campaign_id = get_campaign_for_tenant(tenant_id)
    if not campaign_id:
        return {"ok": False, "response": f"No campaign assigned to tenant '{tenant_id}'"}
    if action not in ("START", "STOP"):
        return {"ok": False, "response": "Invalid action. Use START or STOP."}
    new_status = "ACTIVE" if action == "START" else "INACTIVE"
    if action == "START":
        set_burner_config(campaign_id, "manual_stop", "false")
        if not get_burner_config(campaign_id, "first_start_done"):
            set_burner_config(campaign_id, "first_start_done", "true")
            set_burner_config(campaign_id, "start_date", date.today().isoformat())
    elif action == "STOP":
        set_burner_config(campaign_id, "manual_stop", "true")
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("UPDATE vicidial_remote_agents SET status=%s WHERE campaign_id=%s", (new_status, campaign_id))
        conn.commit()
        affected = cur.rowcount
        conn.close()
    except Exception as e:
        return {"ok": False, "response": f"DB ERROR: {str(e)}"}

    # ── SSH: start/stop AST_VDauto_dial on ViciDial server ───────────────────
    ssh_result = {"ok": False, "msg": "not attempted"}
    try:
        if action == "START":
            rc, out, err = _ssh(
                f"nohup {AUTODIAL} --campaign={campaign_id} --loop > /dev/null 2>&1 &"
            )
            ssh_result = {"ok": rc == 0, "msg": err or out or "launched"}
        else:
            rc, out, err = _ssh(
                f"pkill -f '{AUTODIAL} --campaign={campaign_id}'; echo done"
            )
            ssh_result = {"ok": True, "msg": out or "killed"}
    except subprocess.TimeoutExpired:
        ssh_result = {"ok": False, "msg": "SSH timeout"}
    except Exception as e:
        ssh_result = {"ok": False, "msg": str(e)}

    logger.info("burner toggle %s campaign=%s ssh=%s", action, campaign_id, ssh_result)
    return {"ok": affected > 0, "response": new_status, "affected": affected, "ssh": ssh_result}


@router.post("/push/preview")
def burner_push_preview(payload: dict):
    source_tenant_id  = str(payload.get("source_tenant_id", "")).strip()
    destination       = str(payload.get("destination_campaign_id", "")).strip()
    if not source_tenant_id or not destination:
        return {"error": "source_tenant_id and destination_campaign_id required"}
    source = get_campaign_for_tenant(source_tenant_id)
    if not source:
        return {"error": f"No campaign assigned to tenant '{source_tenant_id}'"}
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT campaign_id FROM vicidial_campaigns WHERE campaign_id=%s LIMIT 1", (destination,))
        if not cur.fetchone():
            conn.close()
            return {"error": f"Destination campaign '{destination}' not found"}
        cur.execute("SELECT COUNT(*) as cnt FROM vicidial_list WHERE list_id IN (SELECT list_id FROM vicidial_lists WHERE campaign_id=%s) AND status='AL'", (source,))
        al = cur.fetchone()["cnt"]
        cur.execute("SELECT COUNT(*) as cnt FROM vicidial_list WHERE list_id IN (SELECT list_id FROM vicidial_lists WHERE campaign_id=%s) AND status='PWORK'", (source,))
        possible = cur.fetchone()["cnt"]
        cur.execute("SELECT COUNT(*) as cnt FROM vicidial_list WHERE list_id IN (SELECT list_id FROM vicidial_lists WHERE campaign_id=%s) AND status='EXCLUD'", (source,))
        excluded = cur.fetchone()["cnt"]
        cur.close()
        conn.close()
        return {
            "would_push": {"AL": al, "possible_working": possible},
            "total": al + possible,
            "excluded": excluded,
            "source_tenant": source_tenant_id,
            "source_campaign": source,
            "destination_campaign": destination
        }
    except Exception as e:
        return {"error": str(e)}


@router.get("/lists")
def burner_lists(campaign_id: str = Query(...)):
    """Return active lists for a given campaign_id."""
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
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


@router.post("/push")
def burner_push(payload: dict):
    tenant_id    = str(payload.get("tenant_id", "")).strip()
    dest_list_id = str(payload.get("dest_list_id", "")).strip()
    if not tenant_id or not dest_list_id:
        return {"error": "tenant_id and dest_list_id required"}
    source = get_campaign_for_tenant(tenant_id)
    if not source:
        return {"error": f"No campaign assigned to tenant '{tenant_id}'"}
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        # Verify dest list exists and get its campaign for response
        cur.execute("SELECT campaign_id FROM vicidial_lists WHERE list_id=%s LIMIT 1", (dest_list_id,))
        dest_list = cur.fetchone()
        if not dest_list:
            conn.close()
            return {"error": f"List '{dest_list_id}' not found"}
        dest_campaign = dest_list["campaign_id"]
        cur.execute("""
            UPDATE vicidial_list
            SET status='NEW', called_since_last_reset='N', called_count=0,
                list_id=%s
            WHERE list_id IN (SELECT list_id FROM vicidial_lists WHERE campaign_id=%s)
            AND status IN ('AL', 'PWORK')
        """, (dest_list_id, source))
        pushed = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        # Mark push_done flag
        set_burner_config(source, "push_done", "true")
        return {"pushed": pushed, "source": source, "destination": dest_campaign, "dest_list_id": dest_list_id}
    except Exception as e:
        return {"error": str(e)}


@router.get("/export")
def burner_export(tenant_id: str = Query(...)):
    campaign_id = get_campaign_for_tenant(tenant_id)
    if not campaign_id:
        return {"error": f"No campaign assigned to tenant '{tenant_id}'"}
    try:
        # ── 1. Leads from ViciDial MySQL — all statuses ───────────────────────
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT vl.first_name, vl.last_name, vl.phone_number, vl.address1,
                   vl.city, vl.state, vl.postal_code, vl.status,
                   vl.called_count, vl.last_local_call_time,
                   vl.source_id
            FROM vicidial_list vl
            WHERE vl.list_id IN (SELECT list_id FROM vicidial_lists WHERE campaign_id=%s)
            ORDER BY vl.status
        """, (campaign_id,))
        leads = cur.fetchall()
        conn.close()

        # ── 2. Skip trace source map: phone → source (from SQLite) ───────────
        phone_source: dict = {}
        try:
            sc = sqlite3.connect(DB_PATH)
            sc_cur = sc.cursor()
            sc_cur.execute(
                "SELECT phone, source FROM skiptrace_records WHERE campaign_id=?",
                (campaign_id,)
            )
            for row in sc_cur.fetchall():
                if row[0] and row[1]:
                    phone_source[str(row[0]).strip()] = row[1]
            sc.close()
        except Exception:
            pass  # skip trace table may not exist yet — column will show blank

        def row_to_csv(x):
            phone = str(x["phone_number"]).strip()
            return [
                x["first_name"], x["last_name"], phone,
                x["address1"], x["city"], x["state"], x["postal_code"],
                x["status"], x["called_count"], x["last_local_call_time"],
                x.get("source_id") or phone_source.get(phone, ""),
            ]

        headers = ["First Name", "Last Name", "Phone", "Address", "City", "State",
                   "Zip", "Status", "Attempts", "Last Call", "Skip Source"]

        output = io.StringIO()
        writer = csv.writer(output)

        # ── Section 1: Answered live (AL) ────────────────────────────────────
        al_leads = [x for x in leads if x["status"] == "AL"]
        writer.writerow([f"=== CONTESTARON (AL) — {campaign_id} === ({len(al_leads)} leads)"])
        writer.writerow(headers)
        for x in al_leads:
            writer.writerow(row_to_csv(x))

        # ── Section 2: Eligible / callable (not excluded, not AL) ────────────
        excluded_statuses = {"EXCLUD", "DNC", "DNCC"}
        eligible_leads = [x for x in leads if x["status"] not in excluded_statuses and x["status"] != "AL"]
        writer.writerow([])
        writer.writerow([f"=== ELEGIBLES (POOL) — {campaign_id} === ({len(eligible_leads)} leads)"])
        writer.writerow(headers)
        for x in eligible_leads:
            writer.writerow(row_to_csv(x))

        # ── Section 3: Excluded ───────────────────────────────────────────────
        excl_leads = [x for x in leads if x["status"] in excluded_statuses]
        writer.writerow([])
        writer.writerow([f"=== EXCLUIDOS — {campaign_id} === ({len(excl_leads)} leads)"])
        writer.writerow(headers)
        for x in excl_leads:
            writer.writerow(row_to_csv(x))

        output.seek(0)

        # Mark csv_downloaded after successful generation
        set_burner_config(campaign_id, "csv_downloaded", "true")

        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=burner_export_{campaign_id}.csv"}
        )
    except Exception as e:
        return {"error": str(e)}


# ─── Cycle status & reset ─────────────────────────────────────────────────────

@router.get("/cycle-status")
def burner_cycle_status(tenant_id: str = Query(...)):
    """Return current state of the 3 cycle-completion flags."""
    campaign_id = get_campaign_for_tenant(tenant_id)
    if not campaign_id:
        return {"error": f"No campaign assigned to tenant '{tenant_id}'"}
    return {
        "campaign_id":    campaign_id,
        "list_complete":  get_burner_config(campaign_id, "list_complete")  == "true",
        "csv_downloaded": get_burner_config(campaign_id, "csv_downloaded") == "true",
        "push_done":      get_burner_config(campaign_id, "push_done")      == "true",
    }


@router.post("/reset")
def burner_reset(payload: dict):
    """Reset the burn cycle. Requires all 3 conditions to be met first."""
    tenant_id = str(payload.get("tenant_id", "")).strip()
    if not tenant_id:
        return {"ok": False, "error": "tenant_id required"}
    campaign_id = get_campaign_for_tenant(tenant_id)
    if not campaign_id:
        return {"ok": False, "error": f"No campaign assigned to tenant '{tenant_id}'"}

    list_complete  = get_burner_config(campaign_id, "list_complete")  == "true"
    csv_downloaded = get_burner_config(campaign_id, "csv_downloaded") == "true"
    push_done      = get_burner_config(campaign_id, "push_done")      == "true"

    missing = []
    if not list_complete:  missing.append("Lista no completada")
    if not csv_downloaded: missing.append("CSV no descargado")
    if not push_done:      missing.append("Push to Campaign no ejecutado")

    if missing:
        return {"ok": False, "blocked": True, "missing": missing}

    # Execute reset — delete all leads in the campaign's lists
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            DELETE FROM vicidial_list
            WHERE list_id IN (SELECT list_id FROM vicidial_lists WHERE campaign_id=%s)
        """, (campaign_id,))
        deleted = cur.rowcount
        conn.commit()
    except Exception as e:
        return {"ok": False, "error": f"DB error during reset: {str(e)}"}

    # Explicit EXCLUD cleanup — belt-and-suspenders for any residuals not caught above
    try:
        cur.execute("""
            DELETE FROM vicidial_list
            WHERE list_id IN (SELECT list_id FROM vicidial_lists WHERE campaign_id=%s)
            AND status = 'EXCLUD'
        """, (campaign_id,))
        excluded_cleaned = cur.rowcount
        conn.commit()
        logger.info("EXCLUD cleanup: %d registros eliminados (campaign %s)", excluded_cleaned, campaign_id)
    except Exception as e:
        logger.error("EXCLUD cleanup failed campaign=%s: %s", campaign_id, e)
        cur.close()
        conn.close()
        return {
            "status": "partial",
            "message": "Reset de KPIs completado pero limpieza de EXCLUD falló — ejecutar manualmente",
            "kpis_reset": True,
        }

    cur.close()
    conn.close()

    # Clear all cycle flags
    for key in ["list_complete", "csv_downloaded", "push_done",
                "manual_stop", "first_start_done", "burned_complete", "start_date"]:
        set_burner_config(campaign_id, key, "false")

    logger.info("burner reset campaign=%s deleted=%d", campaign_id, deleted)
    return {"ok": True, "reset": True, "deleted": deleted}
