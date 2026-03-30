from fastapi import APIRouter, Query, Body
import requests

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
def agent_logout(vici_user: str = Body(...)):
    result = vici_call({
        "function":   "agent_logout",
        "agent_user": vici_user,
    })
    return {"ok": True, "response": result}


@router.post("/pause")
def pause_agent(vici_user: str = Body(...)):
    result = vici_call({
        "function":   "pause_agent",
        "agent_user": vici_user,
        "pause_code": "PAUSE",
    })
    return {"ok": True, "response": result}


@router.post("/resume")
def resume_agent(vici_user: str = Body(...)):
    result = vici_call({
        "function":   "pause_agent",
        "agent_user": vici_user,
        "pause_code": "RESUME",
    })
    return {"ok": True, "response": result}


@router.post("/hangup")
def hangup_lead(vici_user: str = Body(...)):
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
        "function":   "agent_display",
        "agent_user": vici_user,
    })

    if "ERROR" in result.upper() or "--OK--" not in result:
        return {"on_call": False, "raw": result}

    try:
        parts = result.split("--OK--")
        if len(parts) < 2:
            return {"on_call": False, "raw": result}

        data     = parts[1].split("|")
        lead_id  = data[0] if len(data) > 0 else ""
        phone    = data[1] if len(data) > 1 else ""
        first    = data[2] if len(data) > 2 else ""
        last     = data[3] if len(data) > 3 else ""
        address  = data[4] if len(data) > 4 else ""
        city     = data[5] if len(data) > 5 else ""
        state    = data[6] if len(data) > 6 else ""
        postal   = data[7] if len(data) > 7 else ""
        status   = data[8] if len(data) > 8 else ""
        on_call  = bool(lead_id and lead_id not in ("", "0"))

        addr_parts = [p for p in [address, city, state, postal] if p]
        return {
            "on_call":    on_call,
            "lead_id":    lead_id,
            "phone":      phone,
            "name":       f"{first} {last}".strip(),
            "first_name": first,
            "last_name":  last,
            "address":    ", ".join(addr_parts),
            "status":     status,
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
        raise HTTPException(status_code=401, detail="Credenciales de ViciDial incorrectas")
    return {
        "ok": True,
        "vici_user": vici_user,
        "campaign_id": campaign_id,
        "login_response": login_result
    }
