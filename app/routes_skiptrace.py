from fastapi import APIRouter, UploadFile, File, Form, Depends
from typing import Optional
import pandas as pd
import io
from datetime import date
from app.address_normalizer import normalize_address
from app.auth import get_current_tenant

router = APIRouter()

PLATFORM_LABELS = {
    "resimpli":    "ResImpli",
    "skipgenie":   "Skip Genie",
    "dealmachine": "DealMachine",
}

RESIMPLI_PHONE_COLS = [f"Phone_{i}" for i in range(1, 11)]
SKIPGENIE_MOBILE_COLS = [f"MOBILE{i}" for i in range(1, 6)]
SKIPGENIE_PHONE_COLS = [f"PHONE{i}" for i in range(1, 11)]
DEALMACHINE_PHONE_COLS = ["phone_1", "phone_2", "phone_3"]

def safe_str(val):
    if val is None:
        return ""
    try:
        if pd.isna(val):
            return ""
    except (TypeError, ValueError):
        pass
    s = str(val).strip()
    return "" if s.upper() in ("NAN", "NONE", "NULL") else s

def clean_phone(phone):
    if not phone or pd.isna(phone):
        return None
    import re
    cleaned = re.sub(r'\D', '', str(phone))
    return cleaned if len(cleaned) >= 10 else None

def parse_resimpli(df, source_tag, campaign_id, list_id):
    records = []
    for _, row in df.iterrows():
        address = normalize_address(safe_str(row.get("Formated_Address")))
        first_name = safe_str(row.get("First_Name"))
        last_name = safe_str(row.get("Last_Name"))
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
        raw_address = f"{safe_str(row.get('INPUT_ADDRESS'))} {safe_str(row.get('INPUT_CITY'))} {safe_str(row.get('INPUT_STATE'))} {safe_str(row.get('INPUT_ZIPCODE'))}".strip()
        address = normalize_address(raw_address)
        first_name = safe_str(row.get("FIRST"))
        last_name = safe_str(row.get("LAST"))
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
        address = normalize_address(safe_str(row.get("associated_property_address_full")))
        first_name = safe_str(row.get("first_name"))
        last_name = safe_str(row.get("last_name"))
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

    # Build the source label: always include platform name, append source_tag if provided
    platform_label = PLATFORM_LABELS.get(platform, platform)
    effective_source = f"{platform_label} — {source_tag.strip()}" if source_tag.strip() else platform_label

    if platform == "resimpli":
        records = parse_resimpli(df, effective_source, campaign_id, list_id)
    elif platform == "skipgenie":
        records = parse_skipgenie(df, effective_source, campaign_id, list_id)
    elif platform == "dealmachine":
        records = parse_dealmachine(df, effective_source, campaign_id, list_id)
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
