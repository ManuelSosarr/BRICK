from datetime import datetime, timedelta

DEFAULT_STATUS_MAP = {
    # NW - Non Working
    "DC": "NW", "WRONG": "NW", "CHUNG": "NW", "DISCONNECTED": "NW",
    "NW": "NW", "DEAD": "NW", "DEADA": "NW", "ADC": "NW",
    "CONGESTION": "NW",

    # WNA - Working No Answer
    "NA": "WNA", "B": "WNA", "DROP": "WNA", "AA": "WNA",
    "AMD": "WNA", "BUSY": "WNA", "NOANSWER": "WNA", "N": "WNA",
    "PDROP": "WNA", "AB": "WNA", "SPNISH": "WNA", "DISPO": "WNA",
    "nan": "WNA",

    # WAN - Working Answered Rediable
    "CALLBK": "WAN", "SET": "WAN", "A": "WAN", "ANSWER": "WAN",
    "WN": "WAN",

    # WNR - Working Not Rediable
    "SALE": "WNR", "SOLD": "WNR", "NI": "WNR", "DNC": "WNR",
    "INFLU": "WNR", "INFL": "WNR", "DEADL": "WNR", "SCRN": "WNR", "PS": "WNR",
}

def get_flag(status: str, custom_map: dict = None) -> str:
    mapping = custom_map if custom_map else DEFAULT_STATUS_MAP
    return mapping.get(str(status).upper().strip(), "WNA")


def get_exclude_keep(flag: str, carrier_result: str, attempt_count: int) -> str:
    if flag == "NW":
        return "EXCLUDE"
    if flag == "WNA" and str(carrier_result).upper() == "CONGESTION" and attempt_count == 0:
        return "EXCLUDE"
    return "KEEP"


def classify_row(row: dict, custom_map: dict = None) -> dict:
    status = row.get("status", "")
    carrier_result = row.get("carrier_result", "")
    attempt_count = int(row.get("attempt_count", 0) or 0)

    flag = get_flag(status, custom_map)
    exclude_keep = get_exclude_keep(flag, carrier_result, attempt_count)

    return {
        **row,
        "flag": flag,
        "exclude_keep": exclude_keep,
    }


def apply_behavioral_rules(db, WNA_CONSECUTIVE_LIMIT=5, NO_CONTACT_ATTEMPTS=6, MIN_AGE_DAYS=21):
    """
    Aplica reglas de comportamiento sobre los registros existentes en SQLite.
    
    Regla 1: 5+ WNA consecutivos SIN ningún WAN en medio + mínimo 21 días desde primer intento → EXCLUDE
    Regla 2: 6+ intentos totales sin ningún WAN + mínimo 21 días desde primer intento → EXCLUDE
    Regla 3: 3+ DROP consecutivos → EXCLUDE
    """
    from app.models import CallRecord
    from sqlalchemy import func

    updated = 0
    cutoff_date = (datetime.now() - timedelta(days=MIN_AGE_DAYS)).strftime("%Y-%m-%d")

    # Obtener todos los teléfonos únicos con al menos un registro KEEP
    phones = db.query(CallRecord.phone).filter(
        CallRecord.exclude_keep == "KEEP"
    ).distinct().all()

    for (phone,) in phones:
        # Obtener todos los registros de este teléfono ordenados por fecha
        records = db.query(CallRecord).filter(
            CallRecord.phone == phone
        ).order_by(CallRecord.call_date.asc()).all()

        if not records:
            continue

        # Verificar antigüedad mínima — primer intento hace 21+ días
        first_date = str(records[0].call_date)[:10]
        if first_date > cutoff_date:
            continue

        flags = [get_flag(r.status) for r in records]

        # Regla 2: 6+ intentos totales sin ningún WAN
        total_attempts = len(records)
        has_wan = any(f == "WAN" for f in flags)

        if total_attempts >= NO_CONTACT_ATTEMPTS and not has_wan:
            for r in records:
                if r.exclude_keep == "KEEP":
                    r.exclude_keep = "EXCLUDE"
                    r.flag = r.flag if r.flag == "NW" else "WNA"
                    updated += 1
            continue

        # Regla 1: 5+ WNA consecutivos sin WAN en medio
        consecutive_wna = 0
        for f in flags:
            if f == "WNA":
                consecutive_wna += 1
                if consecutive_wna >= WNA_CONSECUTIVE_LIMIT:
                    break
            elif f == "WAN":
                consecutive_wna = 0
            # NW y WNR no resetean ni incrementan

        if consecutive_wna >= WNA_CONSECUTIVE_LIMIT:
            for r in records:
                if r.exclude_keep == "KEEP":
                    r.exclude_keep = "EXCLUDE"
                    updated += 1
            continue

        # Regla 3: 3+ DROP consecutivos
        consecutive_drop = 0
        for r in records:
            if str(r.status).upper() == "DROP":
                consecutive_drop += 1
                if consecutive_drop >= 3:
                    break
            else:
                consecutive_drop = 0

        if consecutive_drop >= 3:
            for r in records:
                if r.exclude_keep == "KEEP":
                    r.exclude_keep = "EXCLUDE"
                    updated += 1

    db.commit()
    return updated