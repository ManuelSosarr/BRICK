from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import CallRecord
from app.logic_classification import classify_row
import pandas as pd
import io
from datetime import date

router = APIRouter()

COLUMN_MAP = {
    0:  "call_date",
    1:  "phone",
    2:  "status",
    13: "first_name",
    15: "last_name",
    16: "address",
    17: "distress1",
    18: "distress2",
    20: "property_type",
    21: "zip_code",
    50: "hangup_cause",
    51: "carrier_result",
}

@router.post("/csv")
async def upload_csv(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Solo se aceptan archivos CSV")

    contents = await file.read()
    df = pd.read_csv(io.StringIO(contents.decode("utf-8")), header=0, low_memory=False)

    week_loaded = str(date.today())
    records_added = 0

    for _, row in df.iterrows():
        raw = {}
        for col_idx, col_name in COLUMN_MAP.items():
            try:
                raw[col_name] = str(row.iloc[col_idx]) if col_idx < len(row) else ""
            except:
                raw[col_name] = ""

        classified = classify_row(raw)

        record = CallRecord(
            call_date=classified.get("call_date", ""),
            phone=classified.get("phone", ""),
            status=classified.get("status", ""),
            first_name=classified.get("first_name", ""),
            last_name=classified.get("last_name", ""),
            address=classified.get("address", ""),
            distress1=classified.get("distress1", ""),
            distress2=classified.get("distress2", ""),
            property_type=classified.get("property_type", ""),
            zip_code=classified.get("zip_code", ""),
            hangup_cause=classified.get("hangup_cause", ""),
            carrier_result=classified.get("carrier_result", ""),
            flag=classified.get("flag", ""),
            exclude_keep=classified.get("exclude_keep", ""),
            week_loaded=week_loaded,
        )
        db.add(record)
        records_added += 1

    db.commit()
    return {"status": "ok", "records_added": records_added, "week_loaded": week_loaded}
