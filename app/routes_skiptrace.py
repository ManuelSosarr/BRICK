from fastapi import APIRouter, UploadFile, File, Form, Depends
from typing import Optional
import pandas as pd
import io
from datetime import date
from app.address_normalizer import normalize_address
from app.auth import get_current_tenant

router = APIRouter()

RESIMPLI_PHONE_COLS = [f"Phone_{i}" for i in range(1, 11)]
SKIPGENIE_MOBILE_COLS = [f"MOBILE{i}" for i in range(1, 6)]
SKIPGENIE_PHONE_COLS = [f"PHONE{i}" for i in range(1, 11)]
DEALMACHINE_PHONE_COLS = ["phone_1", "phone_2", "phone_3"]

def clean_phone(phone):
    if not phone or pd.isna(phone):
        return None
    import re
    cleaned = re.sub(r'\D', '', str(phone))
    return cleaned if len(cleaned) >= 10 else None

def parse_resimpli(df, source_tag, campaign_id, list_id):
    records = []
    for _, row in df.iterrows():
        address = normalize_address(str(row.get("Formated_Address", "")).strip())
        first_name = str(row.get("First_Name", "")).strip()
        last_name = str(row.get("Last_Name", "")).strip()
        for col in RESIMPLI_PHONE_COLS:
            phone = clean_phone(row.get(col))
            if phone:
                records.append({
                    "phone": phone,
                    "first_name": first_name,
                    "last_name": last_name,
                    "address": address,
                    "source": source_tag,
                    "campaign_id": campaign_id,
                    "list_id": list_id,
                    "date_added": date.today().isoformat(),
                })
    return records

def parse_skipgenie(df, source_tag, campaign_id, list_id):
    records = []
    for _, row in df.iterrows():
        raw_address = f"{row.get('INPUT_ADDRESS', '')} {row.get('INPUT_CITY', '')} {row.get('INPUT_STATE', '')} {row.get('INPUT_ZIPCODE', '')}".strip()
        address = normalize_address(raw_address)
        first_name = str(row.get("FIRST", "")).strip()
        last_name = str(row.get("LAST", "")).strip()
        all_phone_cols = SKIPGENIE_MOBILE_COLS + SKIPGENIE_PHONE_COLS
        for col in all_phone_cols:
            phone = clean_phone(row.get(col))
            if phone:
                records.append({
                    "phone": phone,
                    "first_name": first_name,
                    "last_name": last_name,
                    "address": address,
                    "source": source_tag,
                    "campaign_id": campaign_id,
                    "list_id": list_id,
                    "date_added": date.today().isoformat(),
                })
    return records

def parse_dealmachine(df, source_tag, campaign_id, list_id):
    records = []
    for _, row in df.iterrows():
        address = normalize_address(str(row.get("associated_property_address_full", "")).strip())
        first_name = str(row.get("first_name", "")).strip()
        last_name = str(row.get("last_name", "")).strip()
        for col in DEALMACHINE_PHONE_COLS:
            phone = clean_phone(row.get(col))
            if phone:
                records.append({
                    "phone": phone,
                    "first_name": first_name,
                    "last_name": last_name,
                    "address": address,
                    "source": source_tag,
                    "campaign_id": campaign_id,
                    "list_id": list_id,
                    "date_added": date.today().isoformat(),
                })
    return records

@router.post("/upload")
async def upload_skiptrace(
    file: UploadFile = File(...),
    platform: str = Form(...),
    source_tag: str = Form(...),
    campaign_id: str = Form(...),
    list_id: str = Form(...),
    tenant_id: str = Depends(get_current_tenant)
):
    content = await file.read()
    df = pd.read_csv(io.BytesIO(content))

    if platform == "resimpli":
        records = parse_resimpli(df, source_tag, campaign_id, list_id)
    elif platform == "skipgenie":
        records = parse_skipgenie(df, source_tag, campaign_id, list_id)
    elif platform == "dealmachine":
        records = parse_dealmachine(df, source_tag, campaign_id, list_id)
    else:
        return {"error": "Plataforma no reconocida"}

    from app.database import SessionLocal
    from app.models import SkipTraceRecord
    db = SessionLocal()
    added = 0
    duplicates = 0
    for r in records:
        r["tenant_id"] = tenant_id
        existing = db.query(SkipTraceRecord).filter(
            SkipTraceRecord.phone == r["phone"],
            SkipTraceRecord.address == r["address"],
            SkipTraceRecord.tenant_id == tenant_id
        ).first()
        if not existing:
            db.add(SkipTraceRecord(**r))
            added += 1
        else:
            duplicates += 1
    db.commit()
    db.close()

    return {
        "status": "ok",
        "platform": platform,
        "source_tag": source_tag,
        "campaign_id": campaign_id,
        "list_id": list_id,
        "total_processed": len(records),
        "added": added,
        "duplicates": duplicates
    }

@router.get("/list")
def list_skiptrace(
    source: Optional[str] = None,
    tenant_id: str = Depends(get_current_tenant)
):
    from app.database import SessionLocal
    from app.models import SkipTraceRecord
    db = SessionLocal()
    query = db.query(SkipTraceRecord).filter(SkipTraceRecord.tenant_id == tenant_id)
    if source:
        query = query.filter(SkipTraceRecord.source == source)
    records = query.all()
    db.close()
    return [{
        "phone": r.phone,
        "first_name": r.first_name,
        "last_name": r.last_name,
        "address": r.address,
        "source": r.source,
        "campaign_id": r.campaign_id,
        "list_id": r.list_id,
        "date_added": r.date_added
    } for r in records]
