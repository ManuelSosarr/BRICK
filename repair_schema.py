from app.database import engine
from app.models import Base
import sqlalchemy as sa

def repair():
    inspector = sa.inspect(engine)
    columns = [c['name'] for c in inspector.get_columns('skiptrace_records')]
    
    if 'synced_to_vici' not in columns:
        print("Detectado: Falta columna 'synced_to_vici'. Agregando...")
        with engine.connect() as conn:
            conn.execute(sa.text("ALTER TABLE skiptrace_records ADD COLUMN synced_to_vici BOOLEAN DEFAULT 0"))
            conn.commit()
        print("ÉXITO: Columna agregada.")
    else:
        print("La columna ya existe en la DB que SQLAlchemy está viendo.")

if __name__ == "__main__":
    try:
        repair()
    except Exception as e:
        print(f"Error durante la reparación: {e}")
