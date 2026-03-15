from fastapi import APIRouter, Depends, Query, Body
import httpx
import os
from sqlalchemy.orm import Session
from app.database import get_db
from app.logic_dashboard import build_dashboard
from app.address_normalizer import normalize_address
from app.models import CallRecord, ManualExclusion
from fastapi.responses import JSONResponse
import requests
import re

router = APIRouter()

VICI_API_URL  = "http://144.126.146.250/vicidial/non_agent_api.php"
VICI_API_USER = "APIUSER"
VICI_API_PASS = "APIUSER"

@router.get("/")
def get_dashboard(db: Session = Depends(get_db)):
    return build_dashboard(db)

@router.get("/search")
def search_phone(phone: str = Query(...)):
    from app.vici_connector import get_connection

    clean_phone = re.sub(r'\D', '', phone)

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT 
            vl.phone_number as phone,
            vl.address1 as address,
            vl.first_name,
            vl.last_name,
            vll.list_name
        FROM vicidial_list vl
        LEFT JOIN vicidial_lists vll ON vl.list_id = vll.list_id
        WHERE vl.phone_number = %s
        LIMIT 1
    """, (clean_phone,))
    lead = cursor.fetchone()

    if not lead:
        cursor.close()
        conn.close()
        return {"found": False, "phone": clean_phone}

    address = lead["address"]
    normalized_address = normalize_address(address)

    cursor.execute("""
        SELECT 
            vl.phone_number as phone,
            vll.list_name
        FROM vicidial_list vl
        LEFT JOIN vicidial_lists vll ON vl.list_id = vll.list_id
        WHERE vl.address1 = %s
    """, (address,))
    all_leads = cursor.fetchall()

    phone_lists = {}
    for row in all_leads:
        p = row["phone"]
        l = row["list_name"] or ""
        if p not in phone_lists:
            phone_lists[p] = set()
        if l:
            phone_lists[p].add(l)

    property_phones = []
    for phone_number, lists_set in phone_lists.items():
        cursor.execute("""
            SELECT 
                vlog.call_date,
                vlog.status,
                vs.status_name,
                vlog.campaign_id,
                vlog.length_in_sec,
                vlog.user
            FROM vicidial_log vlog
            LEFT JOIN vicidial_statuses vs ON vlog.status = vs.status
            WHERE vlog.phone_number = %s
            ORDER BY vlog.call_date DESC
            LIMIT 10
        """, (phone_number,))
        calls = cursor.fetchall()

        property_phones.append({
            "phone": phone_number,
            "lists": sorted(list(lists_set)),
            "calls": [{
                "call_date": str(c["call_date"]),
                "status": c["status"],
                "status_name": c["status_name"],
                "campaign_id": c["campaign_id"],
                "length_in_sec": c["length_in_sec"],
                "user": c["user"],
            } for c in calls]
        })

    cursor.execute("""
        SELECT 
            vlog.call_date,
            vlog.status,
            vs.status_name,
            vlog.campaign_id
        FROM vicidial_log vlog
        LEFT JOIN vicidial_list vl ON vlog.lead_id = vl.lead_id
        LEFT JOIN vicidial_statuses vs ON vlog.status = vs.status
        WHERE vl.address1 = %s
        ORDER BY vlog.call_date DESC
        LIMIT 1
    """, (address,))
    last_call = cursor.fetchone()

    cursor.close()
    conn.close()

    return {
        "found": True,
        "phone": clean_phone,
        "name": f"{lead['first_name']} {lead['last_name']}".strip(),
        "address": address,
        "normalized_address": normalized_address,
        "list_name": lead["list_name"],
        "last_call": str(last_call["call_date"]) if last_call else "Sin llamadas",
        "last_status": last_call["status"] if last_call else None,
        "last_status_name": last_call["status_name"] if last_call else None,
        "last_campaign_id": last_call["campaign_id"] if last_call else None,
        "total_phones": len(property_phones),
        "property_phones": property_phones,
    }


@router.post("/redispo")
def redispo_call(
    phone: str = Body(...),
    call_date: str = Body(...),
    new_status: str = Body(...),
    db: Session = Depends(get_db)
):
    clean_phone = re.sub(r'\D', '', phone)

    record = db.query(CallRecord).filter(
        CallRecord.phone == clean_phone,
        CallRecord.call_date == call_date,
    ).first()

    if not record:
        return JSONResponse(status_code=404, content={"error": "Call record not found"})

    old_status = record.status
    record.status = new_status

    NW_STATUSES  = {"DC", "WRONG", "CHUNG", "DEADA", "ADC", "DEAD", "CONGESTION"}
    WNR_STATUSES = {"NI", "SALE", "SOLD", "DNC", "INFLU", "DEADL"}
    WAN_STATUSES = {"SET", "A", "CALLBK", "WN", "ANSWER"}

    if new_status in NW_STATUSES:
        record.flag         = "NW"
        record.exclude_keep = "EXCLUDE"
    elif new_status in WNR_STATUSES:
        record.flag         = "WNR"
        record.exclude_keep = "EXCLUDE"
    elif new_status in WAN_STATUSES:
        record.flag         = "WAN"
        record.exclude_keep = "KEEP"
    else:
        record.flag         = "WNA"
        record.exclude_keep = "KEEP"

    db.commit()

    MAKE_WEBHOOK_STATUSES = {"SET", "NI", "DEADL"}
    if new_status in MAKE_WEBHOOK_STATUSES:
        make_url = os.getenv("MAKE_WEBHOOK_URL")
        if make_url:
            try:
                httpx.post(make_url, json={
                    "phone": clean_phone,
                    "address": record.address,
                    "first_name": record.first_name,
                    "last_name": record.last_name,
                    "status": new_status,
                    "source": "dialflow"
                }, timeout=5)
            except Exception:
                pass

    return {
        "ok": True,
        "phone": clean_phone,
        "old_status": old_status,
        "new_status": new_status,
        "new_flag": record.flag,
        "new_exclude_keep": record.exclude_keep,
    }


@router.post("/block")
def block_number(
    phone: str = Body(...),
    reason: str = Body(default="Blocked via Search"),
    db: Session = Depends(get_db)
):
    clean_phone = re.sub(r'\D', '', phone)

    existing = db.query(ManualExclusion).filter(ManualExclusion.phone == clean_phone).first()
    if not existing:
        exclusion = ManualExclusion(phone=clean_phone, reason=reason)
        db.add(exclusion)
        db.commit()

    vici_result = "ok"
    try:
        resp = requests.get(VICI_API_URL, params={
            "source":       "brick_search",
            "user":         VICI_API_USER,
            "pass":         VICI_API_PASS,
            "function":     "add_dnc",
            "phone_number": clean_phone,
        }, timeout=10)
        if "ERROR" in resp.text.upper():
            vici_result = f"warning: {resp.text.strip()}"
    except Exception as e:
        vici_result = f"warning: could not reach ViciDial — {str(e)}"

    return {
        "ok": True,
        "phone": clean_phone,
        "local_exclusion": "added" if not existing else "already existed",
        "vici_dnc": vici_result,
    }
