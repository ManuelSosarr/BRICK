import sqlite3
import os

db_path = r"C:\Users\sosai\BRICK\vicidial.db"
if not os.path.exists(db_path):
    print(f"CRÍTICO: No se encontró la DB en {db_path}")
else:
    try:
        conn = sqlite3.connect(db_path)
        # Intentamos agregar la columna que falta
        conn.execute("ALTER TABLE skiptrace_records ADD COLUMN synced_to_vici BOOLEAN DEFAULT 0")
        conn.commit()
        print("ÉXITO: Columna 'synced_to_vici' agregada correctamente a vicidial.db")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e).lower():
            print("AVISO: La columna ya existía.")
        else:
            print(f"ERROR SQL: {e}")
    except Exception as e:
        print(f"ERROR: {e}")
    finally:
        conn.close()
