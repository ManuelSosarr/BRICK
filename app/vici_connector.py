import mysql.connector
import subprocess
import time
import os
import requests

SSH_HOST = "144.126.146.250"
SSH_PORT = 22
SSH_USER = "root"
SSH_KEY = os.path.expanduser("~/.ssh/vicidial_key")
LOCAL_PORT = 3307
MYSQL_USER = "cron"
MYSQL_PASSWORD = "1234"
MYSQL_DB = "asterisk"

VICI_API_URL = "http://144.126.146.250/vicidial/non_agent_api.php"
VICI_API_USER = "APIUSER"
VICI_API_PASS = "APIUSER"

def is_tunnel_active():
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        result = s.connect_ex(('127.0.0.1', LOCAL_PORT))
        s.close()
        return result == 0
    except:
        return False

def start_tunnel():
    if not is_tunnel_active():
        subprocess.Popen([
            "ssh", "-f", "-N",
            "-L", f"{LOCAL_PORT}:127.0.0.1:3306",
            f"{SSH_USER}@{SSH_HOST}",
            "-p", str(SSH_PORT),
            "-i", SSH_KEY,
            "-o", "StrictHostKeyChecking=no",
            "-o", "ServerAliveInterval=60",
            "-o", "BatchMode=yes"
        ])
        time.sleep(3)

def get_connection():
    start_tunnel()
    return mysql.connector.connect(
        host="127.0.0.1",
        port=LOCAL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DB
    )

def get_campaigns():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT campaign_id, campaign_name FROM vicidial_campaigns ORDER BY campaign_name")
    results = cursor.fetchall()
    cursor.close()
    conn.close()
    return results

def get_lists(campaign_id: str = None):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    if campaign_id:
        cursor.execute("""
            SELECT list_id, list_name, campaign_id 
            FROM vicidial_lists 
            WHERE campaign_id = %s 
            ORDER BY list_name
        """, (campaign_id,))
    else:
        cursor.execute("SELECT list_id, list_name, campaign_id FROM vicidial_lists ORDER BY list_name")
    results = cursor.fetchall()
    cursor.close()
    conn.close()
    return results

def get_call_data(date_from: str, date_to: str, campaign_id: str = None, list_id: str = None):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    query = """
        SELECT 
            vlog.call_date,
            vlog.uniqueid,
            vlog.phone_number as phone_number_dialed,
            vl.phone_number as phone,
            vlog.status,
            vs.status_name,
            vlog.term_reason,
            vlog.length_in_sec,
            vlog.user,
            vlog.user_group,
            vlog.called_count,
            vlog.alt_dial,
            vl.lead_id,
            vl.vendor_lead_code,
            vl.source_id,
            vl.first_name,
            vl.last_name,
            CONCAT(vl.first_name, ' ', vl.last_name) as full_name,
            vl.address1 as address,
            vl.address2,
            vl.address3,
            vl.city,
            vl.state,
            vl.postal_code,
            vl.country_code,
            vl.gender,
            vl.date_of_birth,
            vl.alt_phone,
            vl.email,
            vl.comments,
            vl.rank,
            vl.owner,
            vl.entry_date,
            vl.modify_date,
            vl.last_local_call_time,
            vl.called_since_last_reset,
            vl.list_id,
            vll.list_name,
            vll.list_description,
            vlog.campaign_id
        FROM vicidial_log vlog
        LEFT JOIN vicidial_list vl ON vlog.lead_id = vl.lead_id
        LEFT JOIN vicidial_lists vll ON vl.list_id = vll.list_id
        LEFT JOIN vicidial_statuses vs ON vlog.status = vs.status
        WHERE vlog.call_date BETWEEN %s AND %s
    """
    params = [date_from, date_to]

    if campaign_id:
        query += " AND vlog.campaign_id = %s"
        params.append(campaign_id)

    if list_id:
        query += " AND vl.list_id = %s"
        params.append(list_id)

    query += " ORDER BY vlog.call_date DESC"

    cursor.execute(query, params)
    results = cursor.fetchall()
    cursor.close()
    conn.close()
    return results


def backup_list_to_sqlite(list_id: str, reason: str = "pre_sync"):
    """
    Guarda backup completo de una lista de vicidial_list en SQLite
    antes de cualquier delete. Retorna cantidad de registros respaldados.
    """
    import sqlite3
    from datetime import datetime

    # Obtener datos de ViciDial
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT lead_id, list_id, phone_number, first_name, last_name,
               address1, city, state, postal_code, status
        FROM vicidial_list
        WHERE list_id = %s
    """, (list_id,))
    leads = cursor.fetchall()
    cursor.close()
    conn.close()

    if not leads:
        return 0

    # Guardar en SQLite
    sqlite_conn = sqlite3.connect('vicidial.db')
    sqlite_cursor = sqlite_conn.cursor()

    # Crear tabla de backup si no existe
    sqlite_cursor.execute("""
        CREATE TABLE IF NOT EXISTS list_backups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            backup_date TEXT,
            backup_reason TEXT,
            list_id TEXT,
            lead_id INTEGER,
            phone_number TEXT,
            first_name TEXT,
            last_name TEXT,
            address1 TEXT,
            city TEXT,
            state TEXT,
            postal_code TEXT,
            status TEXT
        )
    """)

    backup_date = datetime.now().isoformat()
    for lead in leads:
        sqlite_cursor.execute("""
            INSERT INTO list_backups 
            (backup_date, backup_reason, list_id, lead_id, phone_number,
             first_name, last_name, address1, city, state, postal_code, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            backup_date,
            reason,
            str(list_id),
            lead['lead_id'],
            lead['phone_number'],
            lead['first_name'] or '',
            lead['last_name'] or '',
            lead['address1'] or '',
            lead['city'] or '',
            lead['state'] or '',
            lead['postal_code'] or '',
            lead['status'] or '',
        ))

    sqlite_conn.commit()
    sqlite_cursor.close()
    sqlite_conn.close()
    return len(leads)


def restore_list_from_backup(list_id: str):
    """
    Restaura una lista desde el backup en SQLite.
    Usa el backup más reciente disponible.
    """
    import sqlite3

    sqlite_conn = sqlite3.connect('vicidial.db')
    sqlite_cursor = sqlite_conn.cursor()

    # Obtener backup más reciente
    sqlite_cursor.execute("""
        SELECT * FROM list_backups
        WHERE list_id = ?
        AND backup_date = (
            SELECT MAX(backup_date) FROM list_backups WHERE list_id = ?
        )
    """, (str(list_id), str(list_id)))
    leads = sqlite_cursor.fetchall()
    sqlite_cursor.close()
    sqlite_conn.close()

    if not leads:
        return 0

    # Restaurar en ViciDial
    conn = get_connection()
    cursor = conn.cursor()
    restored = 0
    for lead in leads:
        _, _, _, _, lead_id, phone_number, first_name, last_name, address1, city, state, postal_code, status = lead
        try:
            cursor.execute("""
                INSERT IGNORE INTO vicidial_list 
                (lead_id, list_id, phone_number, first_name, last_name,
                 address1, city, state, postal_code, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (lead_id, list_id, phone_number, first_name, last_name,
                  address1, city, state, postal_code, status))
            restored += 1
        except:
            pass
    conn.commit()
    cursor.close()
    conn.close()
    return restored


def upload_lead_to_vici(lead: dict, list_id: str) -> dict:
    params = {
        "source": "analytics_app",
        "user": VICI_API_USER,
        "pass": VICI_API_PASS,
        "function": "add_lead",
        "list_id": list_id,
        "phone_number": lead.get("phone", ""),
        "first_name": lead.get("first_name", ""),
        "last_name": lead.get("last_name", ""),
        "address1": lead.get("address", ""),
        "city": lead.get("city", ""),
        "state": lead.get("state", ""),
        "postal_code": lead.get("postal_code", ""),
        "duplicate_check": "DUPLIST",
    }

    try:
        response = requests.get(VICI_API_URL, params=params, timeout=10)
        text = response.text.strip()
        success = text.startswith("SUCCESS")
        return {"success": success, "response": text}
    except Exception as e:
        return {"success": False, "response": str(e)}


def upload_leads_to_vici(leads: list, list_id: str) -> dict:
    uploaded = 0
    failed = 0
    errors = []

    for lead in leads:
        result = upload_lead_to_vici(lead, list_id)
        if result["success"]:
            uploaded += 1
        else:
            failed += 1
            errors.append({"phone": lead.get("phone"), "error": result["response"]})

    return {
        "total": len(leads),
        "uploaded": uploaded,
        "failed": failed,
        "errors": errors[:10]
    }