from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func
from app.database import Base

class CallRecord(Base):
    __tablename__ = "call_records"

    id = Column(Integer, primary_key=True, index=True)
    
    # Datos de la llamada
    call_date = Column(String, index=True)
    uniqueid = Column(String, index=True)
    phone_number_dialed = Column(String)
    phone = Column(String, index=True)
    status = Column(String, index=True)
    status_name = Column(String)
    term_reason = Column(String)
    hangup_cause = Column(String)
    length_in_sec = Column(String)
    wrapup_time = Column(String)
    queue_time = Column(String)
    dial_time = Column(String)
    answered_time = Column(String)
    alt_dial = Column(String)
    cpd_result = Column(String)
    
    # Datos del agente
    user = Column(String)
    user_group = Column(String)
    
    # Datos del lead
    lead_id = Column(String, index=True)
    vendor_lead_code = Column(String)
    source_id = Column(String)
    first_name = Column(String)
    last_name = Column(String)
    full_name = Column(String)
    address = Column(String, index=True)
    address2 = Column(String)
    address3 = Column(String)
    city = Column(String)
    state = Column(String)
    postal_code = Column(String)
    country_code = Column(String)
    gender = Column(String)
    date_of_birth = Column(String)
    alt_phone = Column(String)
    email = Column(String)
    comments = Column(String)
    rank = Column(String)
    owner = Column(String)
    entry_date = Column(String)
    modify_date = Column(String)
    called_count = Column(String)
    last_local_call_time = Column(String)
    called_since_last_reset = Column(String)
    
    # Datos de la lista y campaña
    list_id = Column(String, index=True)
    list_name = Column(String)
    list_description = Column(String)
    campaign_id = Column(String, index=True)
    
    # Grabación
    recording_id = Column(String)
    recording_filename = Column(String)
    
    # Clasificación calculada
    flag = Column(String, index=True)
    exclude_keep = Column(String)
    source = Column(String, default="")
    
    # Tenant
    tenant_id = Column(String, index=True)

    # Tracking
    week_loaded = Column(String, index=True)
    created_at = Column(DateTime, server_default=func.now())


class ManualExclusion(Base):
    __tablename__ = "manual_exclusions"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(String, index=True)
    address = Column(String, index=True)
    phone = Column(String)
    reason = Column(String)
    created_at = Column(DateTime, server_default=func.now())


class StatusMapping(Base):
    __tablename__ = "status_mapping"

    id = Column(Integer, primary_key=True, index=True)
    raw_status = Column(String, unique=True, index=True)
    flag = Column(String)


class SkipTraceRecord(Base):
    __tablename__ = "skiptrace_records"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(String, index=True)
    phone = Column(String, index=True)
    first_name = Column(String)
    last_name = Column(String)
    address = Column(String, index=True)
    source = Column(String, index=True)
    campaign_id = Column(String, index=True)
    list_id = Column(String, index=True)
    date_added = Column(String)
    created_at = Column(DateTime, server_default=func.now())

class TenantCampaign(Base):
    __tablename__ = "tenant_campaigns"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(String, index=True)
    campaign_id = Column(String, index=True)
    created_at = Column(DateTime, server_default=func.now())
