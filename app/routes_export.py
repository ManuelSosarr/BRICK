from fastapi import APIRouter, Depends, Query
from app.auth import get_current_tenant
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import CallRecord, ManualExclusion, SkipTraceRecord
from app.address_normalizer import normalize_address
from app.vici_connector import get_connection, upload_leads_to_vici, backup_list_to_sqlite, restore_list_from_backup
import pandas as pd
import io
from fastapi.responses import StreamingResponse, JSONResponse

router = APIRouter()

PROPERTY_EXCLUDE_STATUSES = {"SET", "NI", "DEADL"}
EMPTY_ADDRESS_VALUES = {None, "", "NONE", "none", "None"}

def clean(value):
    if value is None:
        return ""
    s = str(value).strip()
    if s.upper() in {"NONE", "NAN", "NULL"}:
        return ""
    return s

def is_empty_address(address):
    return address in EMPTY_ADDRESS_VALUES or (address and address.strip().upper() == "NONE")

def get_current_list_phones(list_id):
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT phone_number FROM vicidial_list WHERE list_id = %s", (list_id,))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return {r["phone_number"] for r in rows}
    except Exception:
        return set()

def delete_phones_in_batches(list_id, phones, batch_size=500):
    phones_list = list(phones)
    deleted = 0
    try:
        conn = get_connection()
        cursor = conn.cursor()
        for i in range(0, len(phones_list), batch_size):
            batch = phones_list[i:i + batch_size]
            placeholders = ",".join(["%s"] * len(batch))
            cursor.execute(
                f"DELETE FROM vicidial_list WHERE list_id = %s AND phone_number IN ({placeholders})",
                [list_id] + batch
            )
            deleted += cursor.rowcount
            conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        raise Exception(f"Error borrando leads: {str(e)}")
    return deleted

def get_excluded_phones(db, list_id, campaign_id, tenant_id):
    q = db.query(CallRecord.phone).filter(CallRecord.exclude_keep == "EXCLUDE")
    if tenant_id:
        q = q.filter(CallRecord.tenant_id == tenant_id)
    if campaign_id:
        q = q.filter(CallRecord.campaign_id == campaign_id)
    if list_id:
        q = q.filter(CallRecord.list_id == list_id)
    return {r.phone for r in q.all() if r.phone}

def get_new_skiptrace_leads(db, list_id, campaign_id, tenant_id, current_list_phones):
    manual_exclusions = db.query(ManualExclusion).filter(ManualExclusion.tenant_id == tenant_id).all() if tenant_id else db.query(ManualExclusion).all()
    excluded_addresses = {normalize_address(e.address) for e in manual_exclusions if e.address}
    q = db.query(CallRecord).filter(CallRecord.status.in_(PROPERTY_EXCLUDE_STATUSES))
    if tenant_id:
        q = q.filter(CallRecord.tenant_id == tenant_id)
    set_ni_records = q.all()
    set_ni_addresses = {normalize_address(r.address) for r in set_ni_records if not is_empty_address(r.address)}
    excluded_addresses = excluded_addresses.union(set_ni_addresses)
    set_ni_phones = {r.phone for r in set_ni_records if r.phone}
    skip_query = db.query(SkipTraceRecord).filter(SkipTraceRecord.synced_to_vici == False)
    if tenant_id:
        skip_query = skip_query.filter(SkipTraceRecord.tenant_id == tenant_id)
    if campaign_id:
        skip_query = skip_query.filter(SkipTraceRecord.campaign_id == campaign_id)
    if list_id:
        skip_query = skip_query.filter(SkipTraceRecord.list_id == list_id)
    skip_records = skip_query.all()
    new_leads = []
    for r in skip_records:
        if r.phone in current_list_phones:
            continue
        if r.phone in set_ni_phones:
            continue
        if not is_empty_address(r.address) and normalize_address(r.address) in excluded_addresses:
            continue
        new_leads.append({
            "phone": clean(r.phone), "first_name": clean(r.first_name), "last_name": clean(r.last_name),
            "address": clean(r.address), "city": "", "state": "", "postal_code": "",
            "status": "NEW", "source": clean(r.source), "list_id": clean(r.list_id),
            "campaign_id": clean(r.campaign_id), "origin": "skiptrace",
        })
    seen = set()
    deduped = []
    for r in new_leads:
        if r["phone"] not in seen:
            seen.add(r["phone"])
            deduped.append(r)
    return deduped

def get_updated_data_records(db, date_from=None, date_to=None, campaign_id=None, list_id=None, tenant_id=None):
    manual_exclusions = db.query(ManualExclusion).filter(ManualExclusion.tenant_id == tenant_id).all() if tenant_id else db.query(ManualExclusion).all()
    excluded_addresses = {normalize_address(e.address) for e in manual_exclusions if e.address}
    q = db.query(CallRecord).filter(CallRecord.status.in_(PROPERTY_EXCLUDE_STATUSES))
    if tenant_id: q = q.filter(CallRecord.tenant_id == tenant_id)
    set_ni_records = q.all()
    set_ni_addresses = {normalize_address(r.address) for r in set_ni_records if not is_empty_address(r.address)}
    excluded_addresses = excluded_addresses.union(set_ni_addresses)
    set_ni_phones = {r.phone for r in set_ni_records if r.phone}
    all_vici_phones = {r.phone for r in db.query(CallRecord.phone).all()}
    query = db.query(CallRecord).filter(CallRecord.exclude_keep == "KEEP")
    if tenant_id: query = query.filter(CallRecord.tenant_id == tenant_id)
    if date_from: query = query.filter(CallRecord.call_date >= date_from + " 00:00:00")
    if date_to: query = query.filter(CallRecord.call_date <= date_to + " 23:59:59")
    if campaign_id: query = query.filter(CallRecord.campaign_id == campaign_id)
    if list_id: query = query.filter(CallRecord.list_id == list_id)
    records = query.all()
    filtered = [r for r in records if is_empty_address(r.address) or normalize_address(r.address) not in excluded_addresses]
    skip_query = db.query(SkipTraceRecord)
    if tenant_id: skip_query = skip_query.filter(SkipTraceRecord.tenant_id == tenant_id)
    if campaign_id: skip_query = skip_query.filter(SkipTraceRecord.campaign_id == campaign_id)
    if list_id: skip_query = skip_query.filter(SkipTraceRecord.list_id == list_id)
    skip_records = skip_query.all()
    skip_filtered = [
        r for r in skip_records
        if (is_empty_address(r.address) or normalize_address(r.address) not in excluded_addresses)
        and r.phone not in set_ni_phones and r.phone not in all_vici_phones
    ]
    data = [{
        "phone": clean(r.phone), "first_name": clean(r.first_name), "last_name": clean(r.last_name),
        "address": clean(r.address), "city": clean(r.city), "state": clean(r.state),
        "postal_code": clean(r.postal_code), "status": clean(r.status), "flag": clean(r.flag),
        "list_id": clean(r.list_id), "list_name": clean(r.list_name), "campaign_id": clean(r.campaign_id),
        "source": clean(r.source), "week_loaded": clean(r.week_loaded), "origin": "vicidial",
    } for r in filtered]
    for r in skip_filtered:
        data.append({
            "phone": clean(r.phone), "first_name": clean(r.first_name), "last_name": clean(r.last_name),
            "address": clean(r.address), "city": "", "state": "", "postal_code": "",
            "status": "NEW", "flag": "NEW", "list_id": clean(r.list_id), "list_name": "",
            "campaign_id": clean(r.campaign_id), "source": clean(r.source),
            "week_loaded": clean(r.date_added), "origin": "skiptrace",
        })
    seen_phones = set()
    deduped = []
    for r in data:
        if r["phone"] not in seen_phones:
            seen_phones.add(r["phone"])
            deduped.append(r)
    return deduped

@router.get("/updated-data")
def export_updated_data(
    date_from: str = Query(None), date_to: str = Query(None),
    campaign_id: str = Query(None), list_id: str = Query(None),
    db: Session = Depends(get_db)
):
    deduped = get_updated_data_records(db, date_from, date_to, campaign_id, list_id)
    output = io.BytesIO()
    pd.DataFrame(deduped).to_excel(output, index=False)
    output.seek(0)
    return StreamingResponse(output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=updated_data.xlsx",
                 "X-Total-Records": str(len(deduped)),
                 "Access-Control-Expose-Headers": "X-Total-Records"})

@router.post("/upload-to-vici")
def upload_to_vici(
    list_id: str = Query(...), date_from: str = Query(...), date_to: str = Query(...),
    campaign_id: str = Query(None), db: Session = Depends(get_db),
    tenant_id: str = Depends(get_current_tenant)
):
    # Early exit if nothing to do
    excluded_phones = get_excluded_phones(db, list_id, campaign_id, tenant_id)
    new_leads_check = db.query(SkipTraceRecord).filter(SkipTraceRecord.synced_to_vici == False, SkipTraceRecord.list_id == list_id)
    if tenant_id:
        new_leads_check = new_leads_check.filter(SkipTraceRecord.tenant_id == tenant_id)
    if campaign_id:
        new_leads_check = new_leads_check.filter(SkipTraceRecord.campaign_id == campaign_id)
    has_new_leads = new_leads_check.count() > 0
    if not excluded_phones and not has_new_leads:
        return {"status": "ok", "message": "Lista ya esta al dia. No hay cambios necesarios.",
                "deleted": 0, "uploaded": 0, "failed": 0, "total": 0, "errors": []}
    current_phones = get_current_list_phones(list_id)
    if not current_phones:
        return JSONResponse(status_code=400, content={"error": "Lista vacia o no encontrada en ViciDial."})
    phones_to_delete = current_phones.intersection(excluded_phones)
    new_leads = get_new_skiptrace_leads(db, list_id, campaign_id, tenant_id, current_phones)
    if not phones_to_delete and not new_leads:
        return {"status": "ok", "message": "Lista ya esta al dia. No hay cambios necesarios.",
                "deleted": 0, "uploaded": 0, "failed": 0, "total": 0, "errors": []}
    deleted = 0
    if phones_to_delete:
        try:
            deleted = delete_phones_in_batches(list_id, phones_to_delete)
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})
    uploaded = 0
    failed = 0
    errors = []
    if new_leads:
        result = upload_leads_to_vici(new_leads, list_id)
        uploaded = result["uploaded"]
        failed = result["failed"]
        errors = result["errors"]
        if uploaded > 0:
            uploaded_phones = {r["phone"] for r in new_leads}
            db.query(SkipTraceRecord).filter(
                SkipTraceRecord.phone.in_(uploaded_phones),
                SkipTraceRecord.list_id == list_id,
                SkipTraceRecord.synced_to_vici == False
            ).update({"synced_to_vici": True}, synchronize_session=False)
            db.commit()
    return {"status": "ok", "deleted": deleted, "uploaded": uploaded,
            "failed": failed, "total": deleted + uploaded, "errors": errors}

@router.get("/dashboard-report")
def export_dashboard_report(db: Session = Depends(get_db)):
    from app.logic_dashboard import build_dashboard
    data = build_dashboard(db)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame([data["quick_stats"]]).to_excel(writer, sheet_name="Quick Stats", index=False)
        pd.DataFrame(data["section1_no_dialable"]).to_excel(writer, sheet_name="Section1 Sin Dialables", index=False)
        pd.DataFrame(data["section1b_consecutive"]).to_excel(writer, sheet_name="Section1B Consecutivas", index=False)
        pd.DataFrame(data["section2_excluded"]).to_excel(writer, sheet_name="Section2 Excluidos", index=False)
        pd.DataFrame(data["section3_never_contacted"]).to_excel(writer, sheet_name="Section3 Sin Contacto", index=False)
    output.seek(0)
    return StreamingResponse(output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=dashboard_report.xlsx"})
