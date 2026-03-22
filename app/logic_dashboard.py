from sqlalchemy.orm import Session
from app.models import CallRecord, ManualExclusion, SkipTraceRecord
from collections import defaultdict

def explode_phones(rows, phone_key="phones", extra_keys=[]):
    """Convert list of phones per row into one row per phone."""
    result = []
    for row in rows:
        phones = row.get(phone_key, [])
        for phone in phones:
            new_row = {k: v for k, v in row.items() if k != phone_key}
            new_row["phone"] = phone
            result.append(new_row)
    return result

def build_dashboard(db: Session):
    records = db.query(CallRecord).all()
    manual_exclusions = db.query(ManualExclusion).all()
    excluded_addresses = {e.address for e in manual_exclusions}

    # Build skip trace source map: phone -> source
    skip_records = db.query(SkipTraceRecord).all()
    phone_source_map = {r.phone: r.source for r in skip_records}

    # Estructura principal por dirección
    address_map = defaultdict(lambda: {
        "phones": set(),
        "flags": set(),
        "statuses": set(),
        "weeks": set(),
        "exclude_count": 0,
        "total_count": 0,
        "contacted": False,
        "weeks_without_dialable": 0,
    })

    # PRE-INDEX: records por (address, week) — elimina el triple loop
    records_by_addr_week = defaultdict(list)

    for r in records:
        addr = r.address
        if not addr or addr == "nan":
            continue
        a = address_map[addr]
        a["phones"].add(r.phone)
        if r.phone not in a.get("phone_sources", {}):
            if "phone_sources" not in a:
                a["phone_sources"] = {}
            a["phone_sources"][r.phone] = phone_source_map.get(r.phone, "Unknown")
        a["flags"].add(r.flag)
        a["statuses"].add(r.status)
        a["weeks"].add(r.week_loaded)
        a["total_count"] += 1
        if r.exclude_keep == "EXCLUDE" or addr in excluded_addresses:
            a["exclude_count"] += 1
        if r.status in {"SET", "NI", "SALE", "SOLD"}:
            a["contacted"] = True
        records_by_addr_week[(addr, r.week_loaded)].append(r)

    # Calcular semanas consecutivas sin dialables — ahora O(n) no O(n³)
    all_weeks = sorted(set(r.week_loaded for r in records), reverse=True)

    for addr, data in address_map.items():
        count = 0
        for week in all_weeks:
            week_records = records_by_addr_week[(addr, week)]
            if not week_records:
                continue
            has_dialable = any(r.exclude_keep == "KEEP" for r in week_records)
            if not has_dialable:
                count += 1
            else:
                break
        data["weeks_without_dialable"] = count

    # Semana más reciente cargada
    latest_week = all_weeks[0] if all_weeks else ""

    # Quick Stats
    total_properties = len(address_map)
    total_phones = sum(len(d["phones"]) for d in address_map.values())
    new_this_week = sum(
        1 for d in address_map.values()
        if latest_week in d["weeks"]
        and len(d["weeks"]) == 1
    )
    dialable = sum(
        1 for d in address_map.values()
        if d["exclude_count"] < d["total_count"]
        and "NW" not in d["flags"] or any(f in {"WNA", "WAN"} for f in d["flags"])
    )

    # Section 1 — Sin números dialables
    no_dialable = []
    for addr, data in address_map.items():
        all_excluded = data["exclude_count"] >= data["total_count"]
        only_nw = data["flags"] <= {"NW"}
        if all_excluded or only_nw:
            weeks_count = len(data["weeks"])
            phone_sources = data.get("phone_sources", {})
            for phone in data["phones"]:
                no_dialable.append({
                    "address": addr,
                    "phone": phone,
                    "skip_trace_source": phone_sources.get(phone, "Unknown"),
                    "weeks_in_system": weeks_count,
                    "urgency": "Urgente" if weeks_count >= 3 else "Nuevo",
                })

    # Section 1B — 3+ semanas consecutivas sin dialables
    consecutive_no_dialable = []
    for addr, data in address_map.items():
        if data["weeks_without_dialable"] >= 3:
            phone_sources = data.get("phone_sources", {})
            for phone in data["phones"]:
                consecutive_no_dialable.append({
                    "address": addr,
                    "phone": phone,
                    "skip_trace_source": phone_sources.get(phone, "Unknown"),
                    "consecutive_weeks": data["weeks_without_dialable"],
                })

    # Section 2 — Todos los números EXCLUDE
    all_excluded_list = []
    for addr, data in address_map.items():
        if data["exclude_count"] > 0 or addr in excluded_addresses:
            phone_sources = data.get("phone_sources", {})
            for phone in data["phones"]:
                all_excluded_list.append({
                    "address": addr,
                    "phone": phone,
                    "skip_trace_source": phone_sources.get(phone, "Unknown"),
                    "exclusion_source": "Manual" if addr in excluded_addresses else "Auto",
                })

    # Section 3 — Nunca contactadas
    never_contacted = []
    for addr, data in address_map.items():
        if not data["contacted"]:
            phone_sources = data.get("phone_sources", {})
            for phone in data["phones"]:
                never_contacted.append({
                    "address": addr,
                    "phone": phone,
                    "skip_trace_source": phone_sources.get(phone, "Unknown"),
                    "weeks_in_system": len(data["weeks"]),
                })

    return {
        "quick_stats": {
            "total_properties": total_properties,
            "total_phones": total_phones,
            "dialable_properties": dialable,
            "new_this_week": new_this_week,
            "latest_week": latest_week,
        },
        "section1_no_dialable": no_dialable,
        "section1b_consecutive": consecutive_no_dialable,
        "section2_excluded": all_excluded_list,
        "section3_never_contacted": never_contacted,
    }