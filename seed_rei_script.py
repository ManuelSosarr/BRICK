"""
One-time seed: inserts rei_script.json into the BRICK script library
and assigns it to campaign MUH.

Run once on ASUS:
    python seed_rei_script.py
"""
import sqlite3
import json
import uuid
import datetime
import pathlib

DB_PATH     = "C:/Users/sosai/BRICK/vicidial.db"
SCRIPT_FILE = pathlib.Path(__file__).parent / "sample_scripts" / "rei_script.json"
CAMPAIGN_ID = "MUH"
SCRIPT_NAME = "REI Cold Call — MoveUp"

script_content = SCRIPT_FILE.read_text(encoding="utf-8")
# Validate it parses
json.loads(script_content)

script_id  = str(uuid.uuid4())
now        = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

conn = sqlite3.connect(DB_PATH)
cur  = conn.cursor()

cur.execute("""
    CREATE TABLE IF NOT EXISTS scripts (
        id         TEXT PRIMARY KEY,
        name       TEXT NOT NULL,
        file_type  TEXT NOT NULL DEFAULT 'drawio',
        content    TEXT NOT NULL DEFAULT '',
        created_at TEXT,
        updated_at TEXT
    )
""")
cur.execute("""
    CREATE TABLE IF NOT EXISTS script_assignments (
        script_id   TEXT NOT NULL,
        campaign_id TEXT NOT NULL,
        PRIMARY KEY (script_id, campaign_id)
    )
""")

cur.execute(
    "INSERT INTO scripts (id, name, file_type, content, created_at, updated_at) VALUES (?,?,?,?,?,?)",
    (script_id, SCRIPT_NAME, "drawio", script_content, now, now),
)
cur.execute(
    "INSERT OR IGNORE INTO script_assignments (script_id, campaign_id) VALUES (?,?)",
    (script_id, CAMPAIGN_ID),
)
conn.commit()
conn.close()

print(f"✅ Script '{SCRIPT_NAME}' insertado (id={script_id}) y asignado a {CAMPAIGN_ID}")
