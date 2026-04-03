import sqlite3
conn = sqlite3.connect("vicidial.db")
try:
    conn.execute("ALTER TABLE skiptrace_records ADD COLUMN synced_to_vici BOOLEAN DEFAULT 0")
    conn.commit()
    print("COLUMNA INYECTADA")
except Exception as e:
    print(f"AVISO: {e}")
conn.close()
