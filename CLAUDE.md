# BRICK — CLAUDE.md
## Última actualización: 5 de Abril, 2026 | Referencia: BRICK_Handover_V18.1.2 + sesión actual

---

## ARQUITECTURA
- Backend BRICK (8000): `C:\Users\sosai\BRICK\app\` — SQL, skiptrace, export, Data Burner
- Backend Auth (8001): `C:\Users\sosai\BRICK-auth\backend\` — agente, JWT, sesiones
- Frontend (5173): `C:\Users\sosai\BRICK-frontend\src\`
- DB SQLite: `C:\Users\sosai\BRICK\vicidial.db` — ruta ABSOLUTA
- MySQL ViciDial: túnel SSH 127.0.0.1:3307 → cron / 1234 / asterisk
- Túnel SSH: siempre en ASUS. Llave HARDCODEADA: `C:\Users\sosai\.ssh\vicidial_key` — NO usar $env:USERPROFILE
- ViciDial Server: root@144.126.146.250

## REGLAS DE ORO — ABSOLUTAS
1. TODO cambio de lógica de agente va en `dialflow/backend/routers/agent.py` (8001)
2. NUNCA DELETE/UPDATE masivo en Lista 806 sin backup previo con `backup_list_to_sqlite(806)`
3. Hangup usa agc/api.php como primario — MySQL directo deja al agente en estado DEAD
4. CORS: allow_credentials=False — True + wildcard es inválido por spec
5. Túnel SSH siempre en ASUS — dos terminales: una para túnel (bloqueada), una para comandos
6. Start/Stop y Billing SOLO visibles para superadmin (isMaster)
7. Routing: TODO agente en puerto 8001. Admin/datos en puerto 8000
8. ESTÁNDAR V19: toda operación destructiva en masa DEBE tener endpoint /preview antes del ejecutor real

## CREDENCIALES CRÍTICAS
- APIUSER pass: wscfjqwo3yr1092ruj123t
- MySQL ViciDial: cron / 1234 / asterisk
- ResImpli API Key: 2eea1a4bd7164b8888a5a2c97fd26560
- ViciDial server: root@144.126.146.250

## TENANT MANAGER — WORKFLOW (V2, Abril 2026)
ViciDial es source of truth. Campañas, Listas y DIDs se crean MANUALMENTE en ViciDial.
BRICK solo registra lo que ya existe en ViciDial via Sync.

### Flujo para nuevo cliente:
1. Crear campaña(s), lista(s) y DIDs en ViciDial Admin UI
2. En BRICK → Tenant Manager → "Sync desde ViciDial"
   - Selecciona las campañas del cliente (aparecen las no asignadas)
   - Llena: tenant name, subdomain, admin email/password
   - Ejecutar → crea auth tenant en 8001 (PostgreSQL) + filas SQLite en BRICK
3. En "Users" tab → crear agentes, supervisores, etc. para el tenant

### Endpoints relevantes (BRICK 8000):
- `GET  /api/admin/vici/campaigns/unassigned` — campañas en ViciDial sin BRICK tenant
- `POST /api/admin/tenants/sync`              — registra tenant (llama a 8001 + SQLite)
- `GET  /api/admin/scripts/{campaign_id}`     — obtiene script de llamada
- `PUT  /api/admin/scripts/{campaign_id}`     — guarda script de llamada
- Scripts guardados en SQLite tabla `campaign_scripts`

### Endpoints relevantes (Auth 8001):
- `GET  /api/admin/tenants-with-users` — todos los tenants con conteo de usuarios activos
- `GET  /api/admin/users`              — todos los usuarios (filtro por tenant_id, role, is_active)
- `POST /api/admin/users`              — crea user para cualquier tenant (superadmin only)
- `PATCH /api/admin/users/{id}`        — edita rol, vici_user, password
- `DELETE /api/admin/users/{id}`       — desactiva user

### SSH desde Mac (key en ~/.ssh/vicidial_key):
```bash
chmod 600 ~/.ssh/vicidial_key
ssh -i ~/.ssh/vicidial_key root@144.126.146.250 "mysql -u cron -p1234 asterisk -e \"SELECT ...\""
```

## MULTI-TENANT — DATA BURNER
El superadmin (BRICK) ve todos los clientes. Cada cliente tiene su campaña burner asignada.
El dropdown muestra **nombre del tenant**, no la campaña — la campaña es un detalle interno.
El dropdown **solo es visible para superadmin (isMaster)**. Los clientes se auto-seleccionan por su subdomain del JWT.

### Tabla `tenants` en SQLite (vicidial.db)
```sql
CREATE TABLE IF NOT EXISTS tenants (
    tenant_id   TEXT PRIMARY KEY,
    tenant_name TEXT NOT NULL,
    campaign_id TEXT,           -- campaña burner asignada (NULL = sin burner)
    role        TEXT DEFAULT 'client',
    active      INTEGER DEFAULT 1
);
-- Dato inicial:
INSERT OR IGNORE INTO tenants (tenant_id, tenant_name, campaign_id) VALUES ('bossbuy','BossBuy','IBFEO');
```
Auto-migra datos de `burner_tenants` si existe (backward compat).
Para agregar un nuevo cliente: `POST /api/burner/tenants` con `{tenant_id, tenant_name, campaign_id}`

### Resolución tenant → campaign (backend)
Todos los endpoints usan `tenant_id` (no `campaign_id`). El helper `get_campaign_for_tenant(tenant_id)` hace el lookup en SQLite.

### isMaster + auto-select en frontend
```ts
const _payload = getTokenPayload()
const isMaster = _payload?.role === 'superadmin' || _payload?.subdomain === 'brick'
const clientSubdomain = _payload?.subdomain ?? ''

// isMaster: dropdown visible, selecciona manualmente
// non-master: no dropdown, auto-select por subdomain
```

## ESTADO ACTUAL — LO QUE FUNCIONA ✅
- Resume, Pause (PAUSE!{epoch}), Hangup (agc/api.php + fallback MySQL)
- Lead data: nombre, teléfono, dirección, intentos, último contacto
- Agent name: 3 capas de fallback
- Customer hung up detection + _autoResume()
- Back button protection + Logout
- Polling 1s con fire inmediato
- Disposiciones: SET NI DEADL AMD PS INFLU CB NA WN DNC
- CRM_DISPOS: solo SET y NI muestran Push to CRM
- database.py: ruta absoluta `sqlite:///C:/Users/sosai/BRICK/vicidial.db`
- synced_to_vici: columna existe en models.py y en DB
- **Data Burner — completo:**
  - Dropdown por tenant (superadmin ve todos, cliente ve el suyo)
  - Remote Agent Start/Stop por campaign_id (solo superadmin)
  - KPIs en tiempo real (calls/min, AMD today, hopper activo)
  - Resumen 7 días: Total, Marcados, Elegibles, Excluidos, Contestaron (AL)
  - Billing con minutos reales de TODOS los statuses (solo superadmin)
  - Push to Campaign con Preview (V19) + Confirmar
  - Download CSV con 3 buckets (AL / Possible Working / Excluded)
  - Watchdogs: hopper auto-reset, scheduler 7am-8pm EST, freno día 7
  - Todos los endpoints parametrizados por campaign_id — nada hardcodeado

## PENDIENTE
- Push to CRM vía Chrome Extension — reescrito, no probado en llamada real
- County Link — endpoint existe, verificar con datos reales en PropertyMaster
- DB PostgreSQL (ASUS): correr SQL de limpieza DialFlow → BRICK (ver abajo)

## SQL DE LIMPIEZA — correr en ASUS una sola vez
```sql
-- PostgreSQL (puerto 8001 / BRICK-auth)
DELETE FROM tenants WHERE subdomain = 'acme';
UPDATE tenants SET name = 'BRICK', subdomain = 'brick' WHERE subdomain = 'system';
UPDATE users SET email = 'super@brick.com' WHERE email = 'super@dialflow.com';

-- Verificar:
SELECT id, name, subdomain FROM tenants;
SELECT email, role FROM users;
```
```powershell
# SQLite (puerto 8000)
python -c "
import sqlite3
conn = sqlite3.connect('C:/Users/sosai/BRICK/vicidial.db')
c = conn.cursor()
c.execute(\"DELETE FROM tenants WHERE tenant_id='acme'\")
c.execute(\"UPDATE tenants SET tenant_name='BRICK' WHERE tenant_id='brick'\")
conn.commit()
print(c.execute('SELECT * FROM tenants').fetchall())
conn.close()
"
```

## DATA BURNER — LÓGICA
- Remote Agent: user_start=9999, campaign_id = el del tenant seleccionado
- AMD: cpd_amd_action=DISPO, amd_send_to_vmx=Y (configurado en ViciDial)
- Horario: 7am-8pm EST — watchdog auto-stop/start
- Primer START: siempre manual desde UI
- Auto-reset hopper cuando dialable_leads=0 — solo NA/AB < 5 intentos en 7 días
- Freno duro: día 7 desde primer START → pone INACTIVE y marca burned_complete
- 3 buckets: ANSWERED (AL) / POSSIBLE WORKING (NA/AB<5) / EXCLUDED (DROP/PDROP/AA/DNCL/DNC)
- Push: AL + POSSIBLE WORKING como NEW, EXCLUDED nunca se toca
- SQLite keys de config: `{key}__{campaign_id}` (ej: `first_start_done__IBFEO`)

### Datos reales verificados — BossBuy/IBFEO (4 Abril 2026)
| Status | Llamadas | Min. Facturados |
|---|---|---|
| AL | 260 | 236 |
| DROP | 56 | 4 |
| NA | 148 | 0 |
| PDROP | 45 | 0 |
| **TOTAL** | **521** | **240** — $2.40 |

## ESTÁNDAR V19 — OPERACIONES DESTRUCTIVAS
Toda operación UPDATE/DELETE masiva requiere:
- `POST /api/.../preview` → SELECT COUNT(*) con mismo WHERE → devuelve breakdown sin ejecutar
- `POST /api/...` → ejecuta solo si usuario confirmó el preview

Ejemplo: `/api/burner/push/preview` + `/api/burner/push`

## CÓMO DIAGNOSTICAR PROBLEMAS COMUNES

### Dropdown vacío / UI sin datos
1. Verificar túnel SSH: `netstat -ano | findstr :3307`
2. Probar endpoint: `Invoke-RestMethod -Uri "http://localhost:8000/api/burner/tenants"`
3. Si el endpoint responde pero la UI está vacía → ASUS no ha jalado el último frontend: `cd C:\Users\sosai\BRICK-frontend; git pull origin main`

### Endpoint 404
1. `Select-String "burner" C:\Users\sosai\BRICK\app\main.py`

### Backend no arranca
1. `cd C:\Users\sosai\BRICK && uvicorn app.main:app --port 8000`
2. Ver error exacto

## LECCIONES APRENDIDAS CRÍTICAS
| ID | Lección | Detalle |
|---|---|---|
| F1 | SQLite ruta relativa = riesgo | Usar ruta absoluta siempre |
| F2 | CORS credentials + wildcard inválido | allow_credentials=False con allow_origins=[*] |
| F3 | agent_status pipe: parts[2] = lead_id | parts[1]=uniqueid (V...) NUNCA es el lead_id |
| F4 | ViciDial columnas correctas | address1 (no address), postal_code (no zip_code) |
| F5 | Chrome Extension worlds | executeScript world:MAIN para SPA frameworks |
| F6 | agc/api.php params obligatorios | Si falta CUALQUIER param → ERROR: Invalid Username/Password |
| F7 | Túnel SSH siempre en ASUS | Donde corre el backend, ahí corre el túnel |
| F8 | Virtual Agent GUI bug | Panel ViciDial no guarda Remote Agents. Usar SQL directo |
| F9 | called_since_last_reset no borra historial | Solo es una bandera. vicidial_log sigue intacto |
| F10 | Data Burner por vueltas no por días | El hopper se vacía por leads, no por reloj |
| F11 | Costo real del Burner = todos los statuses | AL domina pero DROP también puede facturar |
| F12 | Túnel SSH: dos terminales siempre | Terminal 1: túnel bloqueado. Terminal 2: SSH para comandos |
| F13 | Dropdown vacío ≠ bug de código | Primero verificar git pull en ASUS antes de depurar |
| F14 | Data Burner dropdown = tenants, no campañas | La campaña es un detalle interno, el usuario ve el nombre del cliente |
| F15 | Tabla burner → `tenants` con auto-migración | Usa `tenants` en SQLite. Migra `burner_tenants` automáticamente. Param API = `tenant_id`, no `campaign_id` |
| F16 | Non-master no ve dropdown | Se auto-seleccionan por `subdomain` del JWT. Dropdown solo para superadmin |

## REFERENCIA COMPLETA
BRICK_Handover_V18.1.2 + sesión 5 Abril 2026
