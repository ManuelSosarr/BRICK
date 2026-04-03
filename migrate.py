import sqlite3
conn = sqlite3.connect("vicidial.db")
try:
    conn.execute("ALTER TABLE skiptrace_records ADD COLUMN synced_to_vici BOOLEAN DEFAULT 0")
    conn.commit()
    print("OK: columna synced_to_vici agregada")
except Exception as e:
    print(f"ERROR: {e}")
conn.close()
