"""
migrate_add_sync_columns.py
═══════════════════════════
Agrega campaign_list_map y sync_day a vicidial_configs en PostgreSQL.
Seguro de correr múltiples veces (ALTER IF NOT EXISTS).

Cómo correr (ASUS PowerShell — UNA SOLA VEZ):
    cd C:\Users\sosai\BRICK
    python migrate_add_sync_columns.py
"""

import psycopg2

PG_DSN = "postgresql://dialflow:dialflow@localhost:5432/dialflow"


def main():
    conn = psycopg2.connect(PG_DSN)
    cur  = conn.cursor()

    print("Agregando columnas a vicidial_configs...")

    cur.execute("""
        ALTER TABLE vicidial_configs
        ADD COLUMN IF NOT EXISTS campaign_list_map JSONB DEFAULT '{}'::jsonb,
        ADD COLUMN IF NOT EXISTS sync_day TEXT DEFAULT 'thu'
    """)
    conn.commit()

    # Verificar
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='vicidial_configs' ORDER BY ordinal_position")
    cols = [r[0] for r in cur.fetchall()]
    print(f"Columnas actuales: {cols}")

    cur.close(); conn.close()
    print("\n✅ Migración completa.")


if __name__ == "__main__":
    main()
