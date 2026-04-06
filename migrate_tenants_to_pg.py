"""
migrate_tenants_to_pg.py
═══════════════════════
One-time migration: copia tenants de SQLite → PostgreSQL.
Seguro de correr múltiples veces (INSERT OR IGNORE equivalente en PG).

Cómo correr (en ASUS):
    cd C:/Users/sosai/BRICK
    python migrate_tenants_to_pg.py

Cuándo correr:
    Una sola vez, antes o después de actualizar routes_admin.py.
    Después del deploy con git reset --hard origin/main.
"""

import sqlite3
import json
import psycopg2
from collections import defaultdict

SQLITE_PATH = "C:/Users/sosai/BRICK/vicidial.db"
PG_DSN      = "postgresql://dialflow:dialflow@localhost:5432/dialflow"


def main():
    # ── 1. Leer tenants de SQLite ──────────────────────────────────────────────
    sc = sqlite3.connect(SQLITE_PATH)
    sc_cur = sc.cursor()
    sc_cur.execute(
        "SELECT tenant_id, tenant_name, campaign_id, active FROM tenants"
    )
    rows = sc_cur.fetchall()
    sc.close()

    if not rows:
        print("SQLite está vacío — nada que migrar.")
        return

    # Agrupar por nombre de tenant (tenant_name puede tener múltiples campaign_ids)
    # Usamos tenant_name como agrupador y el primer tenant_id como subdomain
    tenant_map = defaultdict(lambda: {"subdomain": None, "name": None, "campaign_ids": []})
    for tid, tname, cid, active in rows:
        key = tname.lower().replace(" ", "")
        if tenant_map[key]["subdomain"] is None:
            tenant_map[key]["subdomain"] = tid
            tenant_map[key]["name"]      = tname
        if cid:
            tenant_map[key]["campaign_ids"].append(cid)

    # ── 2. Conectar a PostgreSQL ───────────────────────────────────────────────
    pg = psycopg2.connect(PG_DSN)
    cur = pg.cursor()

    print(f"Tenants en SQLite: {len(tenant_map)}")

    for key, t in tenant_map.items():
        subdomain    = t["subdomain"]
        name         = t["name"]
        campaign_ids = t["campaign_ids"]

        # ¿Ya existe en PostgreSQL?
        cur.execute("SELECT id FROM tenants WHERE subdomain=%s", (subdomain,))
        existing = cur.fetchone()

        if existing:
            tenant_uuid = existing[0]
            print(f"  ✓ {subdomain} ya existe en PostgreSQL (id={tenant_uuid})")

            # Asegurarse de que vicidial_config tenga los campaign_ids
            cur.execute(
                "SELECT id, campaign_ids FROM vicidial_configs WHERE tenant_id=%s",
                (tenant_uuid,)
            )
            vc = cur.fetchone()
            if vc:
                existing_ids = vc[1] or []
                merged = list(set(existing_ids + campaign_ids))
                if merged != (vc[1] or []):
                    cur.execute(
                        "UPDATE vicidial_configs SET campaign_ids=%s WHERE id=%s",
                        (json.dumps(merged), vc[0])
                    )
                    print(f"    → campaign_ids actualizado: {merged}")
            else:
                # Crear vicidial_config mínimo
                cur.execute("""
                    INSERT INTO vicidial_configs
                        (id, tenant_id, api_url, api_user, api_pass, campaign_ids, is_active, created_at, updated_at)
                    VALUES
                        (gen_random_uuid(), %s, '', '', '', %s, true, NOW(), NOW())
                """, (tenant_uuid, json.dumps(campaign_ids)))
                print(f"    → vicidial_config creado con campaign_ids: {campaign_ids}")
        else:
            print(f"  + Creando {subdomain} ({name}) en PostgreSQL...")
            # Insertar tenant
            cur.execute("""
                INSERT INTO tenants (id, name, subdomain, status, primary_color, max_seats, industry, created_at, updated_at)
                VALUES (gen_random_uuid(), %s, %s, 'active', '#2563EB', 10, 'rei', NOW(), NOW())
                RETURNING id
            """, (name, subdomain))
            tenant_uuid = cur.fetchone()[0]

            # Insertar vicidial_config
            cur.execute("""
                INSERT INTO vicidial_configs
                    (id, tenant_id, api_url, api_user, api_pass, campaign_ids, is_active, created_at, updated_at)
                VALUES
                    (gen_random_uuid(), %s, '', '', '', %s, true, NOW(), NOW())
            """, (tenant_uuid, json.dumps(campaign_ids)))
            print(f"    → creado con campaign_ids: {campaign_ids}")

    pg.commit()
    cur.close(); pg.close()
    print("\n✅ Migración completa.")


if __name__ == "__main__":
    main()
