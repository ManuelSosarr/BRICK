from fastapi import APIRouter, Query, Body
import requests
from app.vici_connector import get_lead_by_id

router = APIRouter()

VICI_API_URL  = "http://144.126.146.250/vicidial/non_agent_api.php"
VICI_API_USER = "APIUSER"
VICI_API_PASS = "APIUSER"


def vici_call(params: dict) -> str:
    base = {
        "source": "brick_agent",
        "user":   VICI_API_USER,
        "pass":   VICI_API_PASS,
    }
    base.update(params)
    try:
        resp = requests.get(VICI_API_URL, params=base, timeout=10)
        return resp.text.strip()
    except Exception as e:
        return f"ERROR: {str(e)}"


@router.post("/login")
def agent_login(
    vici_user:   str = Body(...),
    vici_pass:   str = Body(...),
    campaign_id: str = Body(...),
):
    result = vici_call({
        "function":    "agent_login",
        "agent_user":  vici_user,
        "agent_pass":  vici_pass,
        "campaign_id": campaign_id,
        "phone_login": vici_user,
        "phone_pass":  vici_pass,
        "agent_dial":  "VOIP",
        "dial_prefix": "",
    })
    success = "SUCCESS" in result.upper() or "agent_login" in result.lower()
    return {"ok": success, "response": result}


@router.post("/logout")
def agent_logout(vici_user: str = Body(..., embed=True)):
    result = vici_call({
        "function":   "agent_logout",
        "agent_user": vici_user,
    })
    return {"ok": True, "response": result}


@router.post("/pause")
def pause_agent(vici_user: str = Body(..., embed=True)):
    result = vici_call({
        "function":   "pause_agent",
        "agent_user": vici_user,
        "pause_code": "PAUSE",
    })
    return {"ok": True, "response": result}


@router.post("/resume")
def resume_agent(vici_user: str = Body(..., embed=True)):
    result = vici_call({
        "function":   "pause_agent",
        "agent_user": vici_user,
        "pause_code": "RESUME",
    })
    return {"ok": True, "response": result}


@router.post("/hangup")
def hangup_lead(vici_user: str = Body(..., embed=True)):
    result = vici_call({
        "function":   "hangup_lead",
        "agent_user": vici_user,
    })
    return {"ok": True, "response": result}


@router.post("/dispo")
def save_dispo(
    vici_user: str = Body(...),
    lead_id:   str = Body(...),
    dispo:     str = Body(...),
):
    result = vici_call({
        "function":   "save_dispo",
        "agent_user": vici_user,
        "lead_id":    lead_id,
        "dispo":      dispo,
    })
    success = "SUCCESS" in result.upper()
    return {"ok": success, "response": result}


@router.get("/current")
def get_current_lead(vici_user: str = Query(...)):
    result = vici_call({
        "function": "agent_status",
        "agent_user": vici_user,
        "stage": "INCALL",
    })

    if "ERROR" in result.upper():
        return {"on_call": False, "raw": result}

    try:
        # Format: STATUS|UNIQUEID|LEAD_ID|CAMPAIGN|PHONE_CODE|USER|GROUP|LOGIN|PAUSE_CODE|PHONE|ALT_PHONE|EXTENSION
        parts = result.split("|")
        status   = parts[0] if len(parts) > 0 else ""
        uniqueid = parts[1] if len(parts) > 1 else ""
        lead_id  = parts[2] if len(parts) > 2 else ""
        campaign = parts[3] if len(parts) > 3 else ""
        phone    = parts[10] if len(parts) > 10 else parts[9] if len(parts) > 9 else ""
        on_call  = status == "INCALL" and bool(lead_id and lead_id not in ("", "0"))

        lead = {}
        if on_call and lead_id:
            try:
                lead = get_lead_by_id(lead_id) or {}
            except:
                pass

        return {
            "on_call":     on_call,
            "status":      status,
            "lead_id":     lead_id,
            "phone":       phone,
            "campaign_id": campaign,
            "uniqueid":    uniqueid,
            "name":        f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip(),
            "first_name":  lead.get("first_name", ""),
            "last_name":   lead.get("last_name", ""),
            "address":     lead.get("address1", ""),
            "city":        lead.get("city", ""),
            "state":       lead.get("state", ""),
            "postal_code": lead.get("postal_code", ""),
            "called_count": str(lead.get("called_count", "")),
            "comments":    lead.get("comments", ""),
            "raw":         result,
        }
    except Exception as e:
        return {"on_call": False, "raw": result, "error": str(e)}




@router.post("/vici-login")
def vici_login(
    vici_user: str = Body(...),
    vici_pass: str = Body(...),
    campaign_id: str = Body(...),
):
    from fastapi import HTTPException
    login_result = vici_call({
        "function":    "agent_login",
        "agent_user":  vici_user,
        "agent_pass":  vici_pass,
        "campaign_id": campaign_id,
        "phone_login": vici_user,
        "phone_pass":  vici_pass,
        "agent_dial":  "VOIP",
        "dial_prefix": "",
    })
    if "ERROR" in login_result.upper() and "SUCCESS" not in login_result.upper():
        raise HTTPException(status_code=401, detail=f"ViciDial error: {login_result}")
    return {
        "ok": True,
        "vici_user": vici_user,
        "campaign_id": campaign_id,
        "login_response": login_result
    }
