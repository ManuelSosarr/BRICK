"""
scheduler.py — Weekly Auto-Sync para BRICK
═══════════════════════════════════════════
Corre con APScheduler embebido en el proceso de BRICK (8000).
Cada semana, por día asignado (thu/fri/sat/sun), sincroniza cada tenant:
  1. Import ViciDial call data → BRICK DB
  2. Limpia leads excluidos
  3. Re-sube leads frescos a ViciDial
  4. Sube CSV resumen a Google Drive
  5. Notifica por email al superadmin + admin del tenant

Configuración requerida (variables de entorno en ASUS):
  GDRIVE_SERVICE_ACCOUNT_JSON  — ruta al JSON de la Service Account
  GDRIVE_FOLDER_ID             — ID de la carpeta raíz en Drive ("BRICK Syncs/")
  NOTIFY_EMAIL_FROM            — email remitente (Gmail con App Password)
  NOTIFY_EMAIL_PASSWORD        — App Password de Gmail
  NOTIFY_EMAIL_TO              — email del superadmin (ej: sosa.infx@gmail.com)
"""

import io
import json
import logging
import smtplib
import os
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pandas as pd
import psycopg2

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

log = logging.getLogger("brick.scheduler")

PG_DSN = "postgresql://dialflow:dialflow@localhost:5432/dialflow"

# ─── Day-of-week mapping ──────────────────────────────────────────────────────
DOW_MAP = {"thu": "thu", "fri": "fri", "sat": "sat", "sun": "sun"}


# ─── PostgreSQL helpers ───────────────────────────────────────────────────────

def _pg():
    return psycopg2.connect(PG_DSN)


def _get_tenants_for_day(sync_day: str) -> list[dict]:
    """Devuelve tenants con su campaign_list_map para el día dado."""
    conn = _pg()
    cur = conn.cursor()
    cur.execute("""
        SELECT t.id, t.name, t.subdomain,
               vc.campaign_ids, vc.campaign_list_map
        FROM   tenants t
        JOIN   vicidial_configs vc ON vc.tenant_id = t.id
        WHERE  vc.sync_day = %s
          AND  t.status IN ('active', 'trial')
          AND  vc.is_active = true
    """, (sync_day,))
    rows = cur.fetchall()
    cur.close(); conn.close()

    result = []
    for tid, name, subdomain, campaign_ids, campaign_list_map in rows:
        camps = campaign_ids or []
        clm   = campaign_list_map or {}
        if isinstance(camps, str):
            try: camps = json.loads(camps)
            except: camps = []
        if isinstance(clm, str):
            try: clm = json.loads(clm)
            except: clm = {}
        result.append({
            "tenant_id":         str(tid),
            "tenant_name":       name,
            "subdomain":         subdomain,
            "campaign_ids":      camps,
            "campaign_list_map": clm,
        })
    return result


def _get_admin_email(tenant_id: str) -> str | None:
    """Obtiene el email del primer admin del tenant."""
    conn = _pg()
    cur = conn.cursor()
    cur.execute("""
        SELECT email FROM users
        WHERE tenant_id = %s AND role = 'admin' AND is_active = true
        LIMIT 1
    """, (tenant_id,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return row[0] if row else None


def _update_last_sync(tenant_id: str):
    conn = _pg()
    cur = conn.cursor()
    cur.execute(
        "UPDATE vicidial_configs SET updated_at = NOW() WHERE tenant_id = %s",
        (tenant_id,)
    )
    conn.commit()
    cur.close(); conn.close()


# ─── Sync pipeline ───────────────────────────────────────────────────────────

def _run_sync_for_tenant(tenant: dict) -> dict:
    """
    Corre el pipeline completo para un tenant.
    Retorna {"ok": bool, "deleted": int, "uploaded": int, "csv_bytes": bytes}
    """
    from app.routes_export import (
        get_excluded_phones,
        get_new_skiptrace_leads,
        get_current_list_phones,
        delete_phones_in_batches,
    )
    from app.vici_connector import upload_leads_to_vici, get_call_data
    from app.database import SessionLocal
    from app.models import CallRecord, SkipTraceRecord
    from app.logic_classification import classify_row

    tenant_id        = tenant["tenant_id"]
    campaign_list_map = tenant["campaign_list_map"]

    total_deleted  = 0
    total_uploaded = 0
    all_rows       = []

    db = SessionLocal()
    try:
        for campaign_id, list_id in campaign_list_map.items():
            if not list_id:
                log.warning(f"[sync] {tenant['subdomain']} / {campaign_id} — sin list_id, saltando")
                continue

            log.info(f"[sync] {tenant['subdomain']} / {campaign_id} / list {list_id}")

            # 1. Importar call data de ViciDial → BRICK DB
            try:
                raw = get_call_data(date_from=None, date_to=None,
                                    campaign_id=campaign_id, list_id=list_id)
                for r in raw:
                    classified = classify_row(r)
                    rec = CallRecord(
                        tenant_id   = tenant_id,
                        campaign_id = campaign_id,
                        list_id     = list_id,
                        phone       = str(r.get("phone_number", "")),
                        first_name  = str(r.get("first_name", "")),
                        last_name   = str(r.get("last_name", "")),
                        address     = str(r.get("address1", "")),
                        status      = str(r.get("status", "")),
                        flag        = classified.get("flag", ""),
                        exclude_keep= classified.get("exclude_keep", ""),
                    )
                    db.merge(rec)
                db.commit()
            except Exception as e:
                log.error(f"[sync] import error {campaign_id}: {e}")
                continue

            # 2. Eliminar excluidos de la lista
            try:
                current_phones  = get_current_list_phones(list_id)
                excluded_phones = get_excluded_phones(db, list_id, campaign_id, tenant_id)
                to_delete = current_phones.intersection(excluded_phones)
                if to_delete:
                    deleted = delete_phones_in_batches(list_id, to_delete)
                    total_deleted += deleted
                    log.info(f"[sync] deleted {deleted} from list {list_id}")
            except Exception as e:
                log.error(f"[sync] delete error {campaign_id}: {e}")

            # 3. Subir leads nuevos de skiptrace
            try:
                current_phones = get_current_list_phones(list_id)
                new_leads = get_new_skiptrace_leads(db, list_id, campaign_id, tenant_id, current_phones)
                if new_leads:
                    result = upload_leads_to_vici(new_leads, list_id)
                    total_uploaded += result.get("uploaded", 0)
                    log.info(f"[sync] uploaded {result.get('uploaded')} to list {list_id}")
                    if result.get("uploaded", 0) > 0:
                        phones_up = {r["phone"] for r in new_leads}
                        db.query(SkipTraceRecord).filter(
                            SkipTraceRecord.phone.in_(phones_up),
                            SkipTraceRecord.list_id == list_id,
                            SkipTraceRecord.synced_to_vici == False
                        ).update({"synced_to_vici": True}, synchronize_session=False)
                        db.commit()
            except Exception as e:
                log.error(f"[sync] upload error {campaign_id}: {e}")

            # Acumular filas para CSV
            records = db.query(CallRecord).filter(
                CallRecord.tenant_id == tenant_id,
                CallRecord.campaign_id == campaign_id,
            ).all()
            for rec in records:
                all_rows.append({
                    "campaign_id": rec.campaign_id,
                    "list_id":     rec.list_id,
                    "phone":       rec.phone,
                    "first_name":  rec.first_name,
                    "last_name":   rec.last_name,
                    "address":     rec.address,
                    "status":      rec.status,
                    "flag":        rec.flag,
                    "exclude_keep":rec.exclude_keep,
                })

    finally:
        db.close()

    # 4. Generar CSV
    csv_bytes = b""
    if all_rows:
        buf = io.StringIO()
        pd.DataFrame(all_rows).to_csv(buf, index=False)
        csv_bytes = buf.getvalue().encode("utf-8")

    return {
        "ok":        True,
        "deleted":   total_deleted,
        "uploaded":  total_uploaded,
        "csv_bytes": csv_bytes,
        "row_count": len(all_rows),
    }


# ─── Google Drive upload ──────────────────────────────────────────────────────

def _upload_to_gdrive(tenant_name: str, filename: str, csv_bytes: bytes) -> str | None:
    """Sube CSV a GDrive. Retorna link público o None si falla."""
    sa_path    = os.getenv("GDRIVE_SERVICE_ACCOUNT_JSON", "")
    folder_id  = os.getenv("GDRIVE_FOLDER_ID", "")
    if not sa_path or not folder_id:
        log.warning("[gdrive] GDRIVE_SERVICE_ACCOUNT_JSON o GDRIVE_FOLDER_ID no configurados")
        return None

    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaIoBaseUpload

        creds = service_account.Credentials.from_service_account_file(
            sa_path,
            scopes=["https://www.googleapis.com/auth/drive"],
        )
        service = build("drive", "v3", credentials=creds, cache_discovery=False)

        # Buscar o crear subcarpeta del tenant
        q = (f"mimeType='application/vnd.google-apps.folder'"
             f" and name='{tenant_name}' and '{folder_id}' in parents and trashed=false")
        res = service.files().list(q=q, fields="files(id)").execute()
        files = res.get("files", [])
        if files:
            sub_folder_id = files[0]["id"]
        else:
            meta = {
                "name":     tenant_name,
                "mimeType": "application/vnd.google-apps.folder",
                "parents":  [folder_id],
            }
            sub = service.files().create(body=meta, fields="id").execute()
            sub_folder_id = sub["id"]

        # Subir el CSV
        file_meta = {"name": filename, "parents": [sub_folder_id]}
        media = MediaIoBaseUpload(io.BytesIO(csv_bytes), mimetype="text/csv")
        f = service.files().create(body=file_meta, media_body=media, fields="id,webViewLink").execute()

        # Hacer el archivo accesible con el link
        service.permissions().create(
            fileId=f["id"],
            body={"role": "reader", "type": "anyone"},
        ).execute()

        return f.get("webViewLink")

    except Exception as e:
        log.error(f"[gdrive] upload error: {e}")
        return None


# ─── Email notification ───────────────────────────────────────────────────────

def _send_email(to_emails: list[str], subject: str, body_html: str):
    email_from = os.getenv("NOTIFY_EMAIL_FROM", "")
    email_pass = os.getenv("NOTIFY_EMAIL_PASSWORD", "")
    if not email_from or not email_pass:
        log.warning("[email] NOTIFY_EMAIL_FROM o NOTIFY_EMAIL_PASSWORD no configurados")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = email_from
    msg["To"]      = ", ".join(to_emails)
    msg.attach(MIMEText(body_html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(email_from, email_pass)
            smtp.sendmail(email_from, to_emails, msg.as_string())
        log.info(f"[email] enviado a {to_emails}")
    except Exception as e:
        log.error(f"[email] error: {e}")


def _notify(tenant: dict, result: dict, gdrive_link: str | None):
    superadmin_email = os.getenv("NOTIFY_EMAIL_TO", "sosa.infx@gmail.com")
    admin_email      = _get_admin_email(tenant["tenant_id"])
    to_emails        = [superadmin_email]
    if admin_email and admin_email != superadmin_email:
        to_emails.append(admin_email)

    date_str  = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    link_html = f'<a href="{gdrive_link}">Ver en Google Drive</a>' if gdrive_link else "No disponible"

    body = f"""
    <h2>BRICK — Weekly Sync completado</h2>
    <p><strong>Tenant:</strong> {tenant['tenant_name']} ({tenant['subdomain']})</p>
    <p><strong>Fecha:</strong> {date_str}</p>
    <table style="border-collapse:collapse;font-family:monospace">
      <tr><td style="padding:4px 12px">Eliminados</td><td><strong>{result['deleted']}</strong></td></tr>
      <tr><td style="padding:4px 12px">Subidos</td><td><strong>{result['uploaded']}</strong></td></tr>
      <tr><td style="padding:4px 12px">Total registros</td><td><strong>{result['row_count']}</strong></td></tr>
    </table>
    <p>{link_html}</p>
    <p style="color:#888;font-size:12px">BRICK LLC — Auto-Sync semanal</p>
    """
    _send_email(
        to_emails,
        subject=f"[BRICK] Weekly Sync — {tenant['tenant_name']} — {date_str}",
        body_html=body,
    )


# ─── Main sync job ────────────────────────────────────────────────────────────

def run_weekly_sync(sync_day: str):
    """Job que corre APScheduler para un día específico."""
    log.info(f"[scheduler] === Weekly sync START — day={sync_day} ===")
    tenants = _get_tenants_for_day(sync_day)
    log.info(f"[scheduler] {len(tenants)} tenant(s) para hoy ({sync_day})")

    for tenant in tenants:
        log.info(f"[scheduler] → {tenant['subdomain']}")
        try:
            result = _run_sync_for_tenant(tenant)

            # GDrive
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            filename = f"{date_str}_{tenant['subdomain']}_sync.csv"
            gdrive_link = None
            if result["csv_bytes"]:
                gdrive_link = _upload_to_gdrive(tenant["tenant_name"], filename, result["csv_bytes"])

            # Email
            _notify(tenant, result, gdrive_link)

            # Actualizar timestamp
            _update_last_sync(tenant["tenant_id"])

            log.info(f"[scheduler] ✓ {tenant['subdomain']} — deleted={result['deleted']} uploaded={result['uploaded']}")

        except Exception as e:
            log.error(f"[scheduler] ✗ {tenant['subdomain']} — {e}")

    log.info(f"[scheduler] === Weekly sync END — day={sync_day} ===")


# ─── Scheduler setup ─────────────────────────────────────────────────────────

_scheduler: BackgroundScheduler | None = None


def start_scheduler():
    global _scheduler
    _scheduler = BackgroundScheduler(timezone="America/New_York")

    # 8:05pm EST — 5 minutos después de que para el Data Burner (8pm)
    for day in ["thu", "fri", "sat", "sun"]:
        _scheduler.add_job(
            run_weekly_sync,
            trigger=CronTrigger(
                day_of_week=day,
                hour=20,
                minute=5,
                timezone="America/New_York",
            ),
            args=[day],
            id=f"weekly_sync_{day}",
            name=f"Weekly Sync — {day}",
            replace_existing=True,
            misfire_grace_time=3600,  # si el server estaba caído, corre hasta 1h tarde
        )

    _scheduler.start()
    log.info("[scheduler] APScheduler iniciado — sync a las 8:05pm EST (thu/fri/sat/sun)")


def stop_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("[scheduler] APScheduler detenido")
