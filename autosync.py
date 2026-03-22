import requests
from datetime import date, datetime
import os
import sys

BRICK_API      = "http://127.0.0.1:8000"
AUTH_API       = "http://127.0.0.1:8001"
LOG_FILE       = r"C:\Users\sosai\backups\autosync.log"

BOSSBUY_EMAIL  = "admin@bossbuy.com"
BOSSBUY_PASS   = "Admin123!"
BOSSBUY_TENANT = "bossbuy"

IBF_CAMPAIGNS  = ["IBF", "IBFLP", "IBFTD", "IBFAP", "IBFEO", "IBFMD"]
SYNC_CAMPAIGN  = "IBFLP"
SYNC_LIST      = "806"

os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

def log(msg):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = "[{}] {}".format(timestamp, msg)
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def get_token():
    log("Authenticating as bossbuy admin...")
    try:
        res = requests.post(
            "{}/api/auth/login".format(AUTH_API),
            json={"email": BOSSBUY_EMAIL, "password": BOSSBUY_PASS},
            headers={"x-tenant-subdomain": BOSSBUY_TENANT},
            timeout=15
        )
        res.raise_for_status()
        token = res.json().get("access_token")
        if not token:
            raise ValueError("No access_token in response")
        log("Authentication successful.")
        return token
    except Exception as e:
        log("ERROR authenticating: {}".format(e))
        sys.exit(1)

def auth_headers(token):
    return {"Authorization": "Bearer {}".format(token)}

def today():
    return date.today().isoformat()

def step_import(token, campaign_id, date_from, date_to):
    log("  Importing campaign {} ({} to {})...".format(campaign_id, date_from, date_to))
    try:
        res = requests.post(
            "{}/api/vici/import".format(BRICK_API),
            headers=auth_headers(token),
            params={"date_from": date_from, "date_to": date_to, "campaign_id": campaign_id},
            timeout=300
        )
        res.raise_for_status()
        data = res.json()
        log("  OK - Imported {} records for {}".format(data.get("records_added", 0), campaign_id))
        return True
    except Exception as e:
        log("  ERROR importing {}: {}".format(campaign_id, e))
        return False

def step_sync(token, date_from, date_to):
    log("Syncing list {} campaign {} ({} to {})...".format(SYNC_LIST, SYNC_CAMPAIGN, date_from, date_to))
    try:
        res = requests.post(
            "{}/api/export/upload-to-vici".format(BRICK_API),
            headers=auth_headers(token),
            params={"list_id": SYNC_LIST, "date_from": date_from, "date_to": date_to, "campaign_id": SYNC_CAMPAIGN},
            timeout=7200
        )
        res.raise_for_status()
        data = res.json()
        log("Sync complete - deleted: {}, uploaded: {}, failed: {}, message: {}".format(
            data.get("deleted", 0), data.get("uploaded", 0), data.get("failed", 0), data.get("message", "")))
        return True
    except Exception as e:
        log("ERROR during sync: {}".format(e))
        return False

def main():
    log("=" * 60)
    log("BRICK Auto-Sync started")
    log("=" * 60)

    date_from = "2024-01-01"
    date_to   = today()

    token = get_token()

    log("--- STEP 1: Import ViciDial history ---")
    import_ok = 0
    for campaign in IBF_CAMPAIGNS:
        ok = step_import(token, campaign, date_from, date_to)
        if ok:
            import_ok += 1

    log("Import complete: {}/{} campaigns".format(import_ok, len(IBF_CAMPAIGNS)))

    if import_ok == 0:
        log("ERROR: All imports failed. Aborting sync.")
        sys.exit(1)

    log("--- STEP 2: Sync list 806 ---")
    sync_ok = step_sync(token, date_from, date_to)

    if not sync_ok:
        log("ERROR: Sync failed.")
        sys.exit(1)

    log("=" * 60)
    log("BRICK Auto-Sync completed successfully")
    log("=" * 60)

if __name__ == "__main__":
    main()
