import threading
import time as time_module
import sqlite3
import csv
import io
from datetime import datetime, date
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from app.vici_connector import get_connection

try:
    import pytz
    EST = pytz.timezone("America/New_York")
except ImportError:
    EST = None

router = APIRouter()

CAMPAIGN_ID = "IBFEO"
DB_PATH = "C:/Users/sosai/BRICK/vicidial.db"


# ─── SQLite config helpers ────────────────────────────────────────────────────

def get_burner_config(key):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS burner_config (key TEXT PRIMARY KEY, value TEXT)")
    cur.execute("SELECT value FROM burner_config WHERE key=?", (key,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def set_burner_config(key, value):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS burner_config (key TEXT PRIMARY KEY, value TEXT)")
    cur.execute("INSERT OR REPLACE INTO burner_config VALUES (?,?)", (key, str(value)))
    conn.commit()
    conn.close()


# ─── Background watchdogs ─────────────────────────────────────────────────────

def hopper_watchdog():
    while True:
        try:
            start_date_str = get_burner_config("start_date")
            if start_date_str:
                days_elapsed = (date.today() - date.fromisoformat(start_date_str)).days
                if days_elapsed >= 7:
                    conn = get_connection()
                    cur = conn.cursor()
                    cur.execute("UPDATE vicidial_remote_agents SET status='INACTIVE' WHERE campaign_id='IBFEO'")
                    conn.commit()
                    conn.close()
                    set_burner_config("burned_complete", "true")
                    time_module.sleep(3600)
                    continue

            conn = get_connection()
            cur = conn.cursor(dictionary=True)
            cur.execute("SELECT status FROM vicidial_remote_agents WHERE campaign_id='IBFEO' LIMIT 1")
            agent = cur.fetchone()
            if agent and agent["status"] == "ACTIVE":
                cur.execute("SELECT dialable_leads FROM vicidial_campaign_stats WHERE campaign_id='IBFEO'")
                stats = cur.fetchone()
                if stats and stats["dialable_leads"] == 0:
                    cur.execute("""
                        UPDATE vicidial_list SET called_since_last_reset='N'
                        WHERE list_id IN (SELECT list_id FROM vicidial_lists WHERE campaign_id='IBFEO')
                        AND status IN ('NA','AB') AND called_count < 5
                        AND last_local_call_time >= DATE_SUB(NOW(), INTERVAL 7 DAY)
                    """)
                    conn.commit()
            cur.close()
            conn.close()
        except Exception:
            pass
        time_module.sleep(60)


def schedule_watchdog():
    while True:
        try:
            now = datetime.now(EST) if EST else datetime.now()
            hour = now.hour
            conn = get_connection()
            cur = conn.cursor(dictionary=True)
            cur.execute("SELECT status FROM vicidial_remote_agents WHERE campaign_id='IBFEO' LIMIT 1")
            agent = cur.fetchone()
            if agent:
                if agent["status"] == "ACTIVE" and (hour >= 20 or hour < 7):
                    cur.execute("UPDATE vicidial_remote_agents SET status='INACTIVE' WHERE campaign_id='IBFEO'")
                    conn.commit()
                elif agent["status"] == "INACTIVE":
                    first_start = get_burner_config("first_start_done")
                    burned = get_burner_config("burned_complete")
                    if first_start and not burned and 7 <= hour < 20:
                        cur.execute("UPDATE vicidial_remote_agents SET status='ACTIVE' WHERE campaign_id='IBFEO'")
                        conn.commit()
            cur.close()
            conn.close()
        except Exception:
            pass
        time_module.sleep(60)


threading.Thread(target=hopper_watchdog, daemon=True).start()
threading.Thread(target=schedule_watchdog, daemon=True).start()


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/status")
def burner_status():
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT status FROM vicidial_remote_agents WHERE campaign_id='IBFEO' LIMIT 1")
        agent = cur.fetchone()
        cur.execute("SELECT calls_onemin, answering_machines_today, dialable_leads FROM vicidial_campaign_stats WHERE campaign_id='IBFEO' LIMIT 1")
        stats = cur.fetchone()
        cur.execute("SELECT status, last_update_time FROM vicidial_live_agents WHERE campaign_id='IBFEO' ORDER BY last_update_time DESC LIMIT 1")
        live = cur.fetchone()
        conn.close()
        return {
            "remote_agent_status":     agent["status"] if agent else "UNKNOWN",
            "calls_onemin":            stats["calls_onemin"] if stats else 0,
            "answering_machines_today": stats["answering_machines_today"] if stats else 0,
            "dialable_leads":          stats["dialable_leads"] if stats else 0,
            "live_agent_status":       live["status"] if live else "N/A",
            "last_update":             str(live["last_update_time"])[:19] if live else datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    except Exception as e:
        return {"error": str(e)}


@router.get("/weekly")
def burner_weekly():
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT COUNT(*) as total FROM vicidial_list WHERE list_id IN (SELECT list_id FROM vicidial_lists WHERE campaign_id='IBFEO')")
        total = cur.fetchone()["total"]
        cur.execute("SELECT COUNT(*) as dialed FROM vicidial_log WHERE campaign_id='IBFEO' AND call_date >= DATE_SUB(NOW(), INTERVAL 7 DAY)")
        dialed = cur.fetchone()["dialed"]
        cur.execute("SELECT COUNT(*) as dialable FROM vicidial_list WHERE list_id IN (SELECT list_id FROM vicidial_lists WHERE campaign_id='IBFEO') AND status IN ('NA','AB') AND called_count < 5")
        dialable = cur.fetchone()["dialable"]
        cur.execute("SELECT COUNT(*) as excluded FROM vicidial_list WHERE list_id IN (SELECT list_id FROM vicidial_lists WHERE campaign_id='IBFEO') AND status IN ('DROP','PDROP','AA','DNCL','DNC')")
        excluded = cur.fetchone()["excluded"]
        cur.execute("SELECT COUNT(*) as answered FROM vicidial_list WHERE list_id IN (SELECT list_id FROM vicidial_lists WHERE campaign_id='IBFEO') AND status='AL'")
        answered = cur.fetchone()["answered"]
        conn.close()
        return {"total": total, "dialed": dialed, "dialable": dialable, "excluded": excluded, "answered": answered}
    except Exception as e:
        return {"error": str(e)}


@router.post("/toggle")
def burner_toggle(payload: dict):
    action = str(payload.get("action", "")).upper()
    if action not in ("START", "STOP"):
        return {"ok": False, "response": "Invalid action. Use START or STOP."}
    new_status = "ACTIVE" if action == "START" else "INACTIVE"
    if action == "START" and not get_burner_config("first_start_done"):
        set_burner_config("first_start_done", "true")
        set_burner_config("start_date", date.today().isoformat())
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("UPDATE vicidial_remote_agents SET status=%s WHERE campaign_id='IBFEO'", (new_status,))
        conn.commit()
        affected = cur.rowcount
        conn.close()
        return {"ok": affected > 0, "response": new_status, "affected": affected}
    except Exception as e:
        return {"ok": False, "response": f"DB ERROR: {str(e)}"}


@router.post("/push")
def burner_push(payload: dict):
    campaign_id = payload.get("campaign_id")
    if not campaign_id:
        return {"error": "campaign_id required"}
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT list_id FROM vicidial_lists WHERE campaign_id=%s LIMIT 1", (campaign_id,))
        dest_list = cur.fetchone()
        if not dest_list:
            conn.close()
            return {"error": "Campaign not found"}
        dest_list_id = dest_list["list_id"]
        cur.execute("""
            UPDATE vicidial_list
            SET status='NEW', called_since_last_reset='N', called_count=0,
                list_id=%s, campaign_id=%s
            WHERE list_id IN (SELECT list_id FROM vicidial_lists WHERE campaign_id='IBFEO')
            AND (status='AL' OR (status IN ('NA','AB') AND called_count < 5))
        """, (dest_list_id, campaign_id))
        pushed = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        return {"pushed": pushed, "destination": campaign_id}
    except Exception as e:
        return {"error": str(e)}


@router.get("/minutes")
def burner_minutes():
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT status,
                   COUNT(*) as calls,
                   SUM(length_in_sec) as raw_seconds,
                   SUM(CEIL(length_in_sec / 60)) as billed_minutes
            FROM vicidial_log
            WHERE campaign_id = 'IBFEO'
            AND call_date >= DATE_SUB(NOW(), INTERVAL 7 DAY)
            GROUP BY status
            ORDER BY calls DESC
        """)
        breakdown = cur.fetchall()
        cur.execute("""
            SELECT COUNT(*) as total_calls,
                   SUM(length_in_sec) as total_raw_seconds,
                   SUM(CEIL(length_in_sec / 60)) as total_billed_minutes
            FROM vicidial_log
            WHERE campaign_id = 'IBFEO'
            AND call_date >= DATE_SUB(NOW(), INTERVAL 7 DAY)
        """)
        totals = cur.fetchone()
        cur.close()
        conn.close()
        return {
            "total_calls": totals["total_calls"] or 0,
            "total_raw_seconds": int(totals["total_raw_seconds"] or 0),
            "total_billed_minutes": int(totals["total_billed_minutes"] or 0),
            "estimated_cost_usd": round(float(totals["total_billed_minutes"] or 0) * 0.01, 2),
            "breakdown": [
                {
                    "status": row["status"],
                    "calls": row["calls"],
                    "raw_seconds": int(row["raw_seconds"] or 0),
                    "billed_minutes": int(row["billed_minutes"] or 0),
                }
                for row in breakdown
            ]
        }
    except Exception as e:
        return {"error": str(e)}


@router.get("/export")
def burner_export():
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT first_name, last_name, phone_number, address1, city, state,
                   postal_code, status, called_count, last_local_call_time
            FROM vicidial_list
            WHERE list_id IN (SELECT list_id FROM vicidial_lists WHERE campaign_id='IBFEO')
            ORDER BY status
        """)
        leads = cur.fetchall()
        conn.close()

        output = io.StringIO()
        writer = csv.writer(output)
        headers = ["First Name","Last Name","Phone","Address","City","State","Zip","Status","Attempts","Last Call"]

        writer.writerow(["=== ANSWERED (AL) ==="])
        writer.writerow(headers)
        for l in [x for x in leads if x["status"] == "AL"]:
            writer.writerow([l["first_name"],l["last_name"],l["phone_number"],l["address1"],l["city"],l["state"],l["postal_code"],l["status"],l["called_count"],l["last_local_call_time"]])

        writer.writerow([])
        writer.writerow(["=== POSSIBLE WORKING (NA/AB < 5 attempts) ==="])
        writer.writerow(headers)
        for l in [x for x in leads if x["status"] in ("NA","AB") and x["called_count"] < 5]:
            writer.writerow([l["first_name"],l["last_name"],l["phone_number"],l["address1"],l["city"],l["state"],l["postal_code"],l["status"],l["called_count"],l["last_local_call_time"]])

        writer.writerow([])
        writer.writerow(["=== EXCLUDED (DROP/PDROP/AA/DNCL/DNC) ==="])
        writer.writerow(headers)
        for l in [x for x in leads if x["status"] in ("DROP","PDROP","AA","DNCL","DNC")]:
            writer.writerow([l["first_name"],l["last_name"],l["phone_number"],l["address1"],l["city"],l["state"],l["postal_code"],l["status"],l["called_count"],l["last_local_call_time"]])

        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=burner_export_IBFEO.csv"}
        )
    except Exception as e:
        return {"error": str(e)}
