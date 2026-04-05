from fastapi import APIRouter, Depends, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.auth import get_current_tenant
from app.models import TenantCampaign
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import CallRecord
from app.logic_classification import classify_row, apply_behavioral_rules
from app.vici_connector import get_campaigns, get_lists, get_call_data
from app.address_normalizer import normalize_address
from datetime import date
from jose import jwt, JWTError
import os

router = APIRouter()
_security = HTTPBearer(auto_error=False)
_SECRET = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")

def _get_role(credentials: HTTPAuthorizationCredentials = Depends(_security)) -> str:
    try:
        payload = jwt.decode(credentials.credentials, _SECRET, algorithms=["HS256"])
        return payload.get("role", "")
    except Exception:
        return ""

@router.get("/campaigns")
def list_campaigns(
    db: Session = Depends(get_db),
    tenant_id: str = Depends(get_current_tenant),
    role: str = Depends(_get_role),
):
    all_campaigns = get_campaigns()
    if role == "superadmin":
        return all_campaigns
    allowed = {r.campaign_id for r in db.query(TenantCampaign).filter(TenantCampaign.tenant_id == tenant_id).all()}
    return [c for c in all_campaigns if c["campaign_id"] in allowed]

@router.get("/lists")
def list_lists(
    campaign_id: str = Query(None),
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    allowed = {r.campaign_id for r in db.query(TenantCampaign).filter(TenantCampaign.tenant_id == tenant_id).all()}
    lists = get_lists(campaign_id)
    if campaign_id:
        return lists if campaign_id in allowed else []
    return [l for l in lists if l["campaign_id"] in allowed]

@router.post("/import")
def import_from_vici(
    date_from: str = Query(...),
    date_to: str = Query(...),
    campaign_id: str = Query(None),
    list_id: str = Query(None),
    db: Session = Depends(get_db),
    tenant_id: str = Depends(get_current_tenant)
):
    # Validate campaign belongs to tenant
    if campaign_id:
        allowed = {r.campaign_id for r in db.query(TenantCampaign).filter(TenantCampaign.tenant_id == tenant_id).all()}
        if campaign_id not in allowed:
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="Campaign not allowed for this tenant")

    records = get_call_data(date_from, date_to, campaign_id, list_id)
    week_loaded = date.today().isoformat()
    added = 0

    for r in records:
        classified = classify_row({
            "status": r.get("status", ""),
            "term_reason": r.get("term_reason", ""),
            "called_count": r.get("called_count", 0),
        })

        raw_address = str(r.get("address", ""))
        normalized = normalize_address(raw_address)

        record = CallRecord(
            call_date=str(r.get("call_date", "")),
            uniqueid=str(r.get("uniqueid", "")),
            phone_number_dialed=str(r.get("phone_number_dialed", "")),
            phone=str(r.get("phone", "")),
            status=str(r.get("status", "")),
            status_name=str(r.get("status_name", "")),
            term_reason=str(r.get("term_reason", "")),
            length_in_sec=str(r.get("length_in_sec", "")),
            user=str(r.get("user", "")),
            user_group=str(r.get("user_group", "")),
            called_count=str(r.get("called_count", "")),
            alt_dial=str(r.get("alt_dial", "")),
            lead_id=str(r.get("lead_id", "")),
            vendor_lead_code=str(r.get("vendor_lead_code", "")),
            source_id=str(r.get("source_id", "")),
            first_name=str(r.get("first_name", "")),
            last_name=str(r.get("last_name", "")),
            full_name=str(r.get("full_name", "")),
            address=normalized,
            address2=str(r.get("address2", "")),
            address3=str(r.get("address3", "")),
            city=str(r.get("city", "")),
            state=str(r.get("state", "")),
            postal_code=str(r.get("postal_code", "")),
            country_code=str(r.get("country_code", "")),
            gender=str(r.get("gender", "")),
            date_of_birth=str(r.get("date_of_birth", "")),
            alt_phone=str(r.get("alt_phone", "")),
            email=str(r.get("email", "")),
            comments=str(r.get("comments", "")),
            rank=str(r.get("rank", "")),
            owner=str(r.get("owner", "")),
            entry_date=str(r.get("entry_date", "")),
            modify_date=str(r.get("modify_date", "")),
            last_local_call_time=str(r.get("last_local_call_time", "")),
            called_since_last_reset=str(r.get("called_since_last_reset", "")),
            list_id=str(r.get("list_id", "")),
            list_name=str(r.get("list_name", "")),
            list_description=str(r.get("list_description", "")),
            campaign_id=str(r.get("campaign_id", "")),
            flag=classified["flag"],
            exclude_keep=classified["exclude_keep"],
            week_loaded=week_loaded,
            tenant_id=tenant_id,
        )
        db.add(record)
        added += 1

    db.commit()

    behavioral_updates = apply_behavioral_rules(db)

    return {
        "status": "ok",
        "records_added": added,
        "behavioral_updates": behavioral_updates,
        "week_loaded": week_loaded
    }


@router.get("/agent_status")
def agent_status(
    agent_user: str = Query(...),
    tenant_id: str = Depends(get_current_tenant)
):
    from app.vici_connector import get_agent_status, get_lead_by_id
    status = get_agent_status(agent_user)
    if status.get("lead_id"):
        lead = get_lead_by_id(status["lead_id"])
        status["lead"] = lead
    return status


@router.post("/update_lead")
def update_lead(
    lead_id: str = Query(...),
    status: str = Query(...),
    tenant_id: str = Depends(get_current_tenant)
):
    from app.vici_connector import update_lead_status
    return update_lead_status(lead_id, status)
