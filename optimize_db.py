import sqlite3
conn = sqlite3.connect("vicidial.db")
try:
    conn.execute("CREATE INDEX IF NOT EXISTS idx_phone_records ON call_records (phone)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_phone_skiptrace ON skiptrace_records (phone)")
    conn.commit()
    print("ÉXITO: Índices creados.")
except Exception as e:
    print(f"AVISO: {e}")
conn.close()
