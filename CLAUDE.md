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

## MULTI-TENANT — DATA BURNER
El superadmin (BRICK) ve todos los clientes. Cada cliente tiene su campaña burner asignada.
El dropdown muestra **nombre del tenant**, no la campaña — la campaña es un detalle interno.

### Tabla `burner_tenants` en SQLite (vicidial.db)
```sql
CREATE TABLE IF NOT EXISTS burner_tenants (
    tenant_id   TEXT PRIMARY KEY,
    tenant_name TEXT NOT NULL,
    campaign_id TEXT NOT NULL,  -- campaña burner asignada al cliente
    active      INTEGER DEFAULT 1
);
-- Dato inicial:
INSERT OR IGNORE INTO burner_tenants VALUES ('bossbuy','BossBuy','IBFEO',1);
```

Para agregar un nuevo cliente: `POST /api/burner/tenants` con `{tenant_id, tenant_name, campaign_id}`

### isMaster en frontend
```ts
const payload = JSON.parse(atob(localStorage.getItem('access_token').split('.')[1]))
const isMaster = payload?.role === 'superadmin' || payload?.subdomain === 'brick'
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

## REFERENCIA COMPLETA
BRICK_Handover_V18.1.2 + sesión 5 Abril 2026
