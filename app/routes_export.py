from fastapi import APIRouter, Depends, Query
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

def get_updated_data_records(db, date_from=None, date_to=None, campaign_id=None, list_id=None):
    manual_exclusions = db.query(ManualExclusion).all()
    excluded_addresses = {normalize_address(e.address) for e in manual_exclusions if e.address}

    set_ni_records = db.query(CallRecord).filter(
        CallRecord.status.in_(PROPERTY_EXCLUDE_STATUSES)
    ).all()
    set_ni_addresses = {normalize_address(r.address) for r in set_ni_records if not is_empty_address(r.address)}
    excluded_addresses = excluded_addresses.union(set_ni_addresses)

    set_ni_phones = {r.phone for r in set_ni_records if r.phone}
    # Todos los telefonos que ya tienen historial en CallRecord (KEEP o EXCLUDE)
    # Los skip traces solo suben si el telefono es completamente nuevo
    all_vici_phones = {r.phone for r in db.query(CallRecord.phone).all()}

    query = db.query(CallRecord).filter(CallRecord.exclude_keep == "KEEP")
    if date_from:
        query = query.filter(CallRecord.call_date >= date_from + " 00:00:00")
    if date_to:
        query = query.filter(CallRecord.call_date <= date_to + " 23:59:59")
    if campaign_id:
        query = query.filter(CallRecord.campaign_id == campaign_id)
    if list_id:
        query = query.filter(CallRecord.list_id == list_id)

    records = query.all()

    filtered = [
        r for r in records
        if is_empty_address(r.address) or normalize_address(r.address) not in excluded_addresses
    ]

    skip_query = db.query(SkipTraceRecord)
    if campaign_id:
        skip_query = skip_query.filter(SkipTraceRecord.campaign_id == campaign_id)
    if list_id:
        skip_query = skip_query.filter(SkipTraceRecord.list_id == list_id)
    skip_records = skip_query.all()

    skip_filtered = [
        r for r in skip_records
        if (is_empty_address(r.address) or normalize_address(r.address) not in excluded_addresses)
        and r.phone not in set_ni_phones
        and r.phone not in all_vici_phones
    ]

    data = [{
        "phone": clean(r.phone),
        "first_name": clean(r.first_name),
        "last_name": clean(r.last_name),
        "address": clean(r.address),
        "city": clean(r.city),
        "state": clean(r.state),
        "postal_code": clean(r.postal_code),
        "status": clean(r.status),
        "flag": clean(r.flag),
        "list_id": clean(r.list_id),
        "list_name": clean(r.list_name),
        "campaign_id": clean(r.campaign_id),
        "source": clean(r.source),
        "week_loaded": clean(r.week_loaded),
        "origin": "vicidial",
    } for r in filtered]

    for r in skip_filtered:
        data.append({
            "phone": clean(r.phone),
            "first_name": clean(r.first_name),
            "last_name": clean(r.last_name),
            "address": clean(r.address),
            "city": "",
            "state": "",
            "postal_code": "",
            "status": "NEW",
            "flag": "NEW",
            "list_id": clean(r.list_id),
            "list_name": "",
            "campaign_id": clean(r.campaign_id),
            "source": clean(r.source),
            "week_loaded": clean(r.date_added),
            "origin": "skiptrace",
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
    date_from: str = Query(None),
    date_to: str = Query(None),
    campaign_id: str = Query(None),
    list_id: str = Query(None),
    db: Session = Depends(get_db)
):
    deduped = get_updated_data_records(db, date_from, date_to, campaign_id, list_id)

    output = io.BytesIO()
    pd.DataFrame(deduped).to_excel(output, index=False)
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": "attachment; filename=updated_data.xlsx",
            "X-Total-Records": str(len(deduped)),
            "Access-Control-Expose-Headers": "X-Total-Records",
        }
    )


@router.post("/upload-to-vici")
def upload_to_vici(
    list_id: str = Query(...),
    date_from: str = Query(...),
    date_to: str = Query(...),
    campaign_id: str = Query(None),
    db: Session = Depends(get_db)
):
    # Paso 1 — validar que hay leads antes de tocar la lista
    leads = get_updated_data_records(db, date_from, date_to, campaign_id, list_id)

    if not leads:
        return JSONResponse(
            status_code=400,
            content={"error": "No hay leads para subir — abortando. La lista NO fue modificada."}
        )

    # Paso 2 — backup completo antes del delete
    backed_up = backup_list_to_sqlite(list_id, reason="pre_sync")

    # Paso 3 — borrar lista en ViciDial
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM vicidial_list WHERE list_id = %s", (list_id,))
        deleted = cursor.rowcount
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Error borrando lista: {str(e)}"})

    # Paso 4 — subir leads via API
    result = upload_leads_to_vici(leads, list_id)

    # Paso 5 — si el upload falló completamente, restaurar desde backup
    if result["uploaded"] == 0 and result["failed"] > 0:
        restored = restore_list_from_backup(list_id)
        return JSONResponse(
            status_code=500,
            content={
                "error": "Upload falló — lista restaurada desde backup",
                "backed_up": backed_up,
                "restored": restored,
                "errors": result["errors"]
            }
        )

    return {
        "status": "ok",
        "backed_up": backed_up,
        "deleted": deleted,
        "uploaded": result["uploaded"],
        "failed": result["failed"],
        "total": result["total"],
        "errors": result["errors"],
    }


@router.get("/dashboard-report")
def export_dashboard_report(db: Session = Depends(get_db)):
    from app.logic_dashboard import build_dashboard
    data = build_dashboard(db)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame([data["quick_stats"]]).to_excel(
            writer, sheet_name="Quick Stats", index=False)
        pd.DataFrame(data["section1_no_dialable"]).to_excel(
            writer, sheet_name="Section1 Sin Dialables", index=False)
        pd.DataFrame(data["section1b_consecutive"]).to_excel(
            writer, sheet_name="Section1B Consecutivas", index=False)
        pd.DataFrame(data["section2_excluded"]).to_excel(
            writer, sheet_name="Section2 Excluidos", index=False)
        pd.DataFrame(data["section3_never_contacted"]).to_excel(
            writer, sheet_name="Section3 Sin Contacto", index=False)

    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=dashboard_report.xlsx"}
    )