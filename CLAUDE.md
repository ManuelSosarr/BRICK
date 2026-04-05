# BRICK — CLAUDE.md
## Última actualización: 5 de Abril, 2026 | Referencia: BRICK_Handover_V20

---

## ARQUITECTURA GENERAL

| Componente | Ruta (ASUS) | Puerto | Descripción |
|---|---|---|---|
| BRICK Backend | `C:\Users\sosai\BRICK\app\` | 8000 | SQL, skiptrace, export, Data Burner, Admin |
| Auth Backend | `C:\Users\sosai\BRICK-auth\backend\` | 8001 | JWT, agente, sesiones, tenants, users |
| Frontend | `C:\Users\sosai\BRICK-frontend\src\` | 5173 | React 19 + TypeScript + Vite |
| SQLite | `C:\Users\sosai\BRICK\vicidial.db` | — | Ruta ABSOLUTA siempre |
| MySQL Dialer | túnel SSH 127.0.0.1:3307 | 3307 | cron / 1234 / asterisk |
| PostgreSQL Auth | docker en ASUS | 5432 | Tenants, Users, Leads, CRM |

### Infraestructura
- **ASUS** = máquina de producción Windows. Aquí corren TODOS los backends y el túnel SSH.
- **Mac** = desarrollo. `git push` desde Mac, `git pull` en ASUS.
- **Dialer Server**: root@144.126.146.250
- **Túnel SSH**: llave en `C:\Users\sosai\.ssh\vicidial_key` (ASUS) y `~/.ssh/vicidial_key` (Mac)
- **NGROK**: tunneling del frontend para acceso externo (corre en BRICK.ps1)

### Startup completo (ASUS — BRICK.ps1)
```powershell
# Túnel SSH al dialer
ssh -i C:\Users\sosai\.ssh\vicidial_key -N -L 3307:localhost:3306 root@144.126.146.250

# Backend BRICK (8000)
cd C:\Users\sosai\BRICK; uvicorn app.main:app --port 8000

# Backend Auth (8001)
cd C:\Users\sosai\BRICK-auth\backend; python main.py

# Frontend
cd C:\Users\sosai\BRICK-frontend; npm run dev

# NGROK (acceso externo)
ngrok http 5173 --log=stdout

# Watchdog (auto-restart backends caídos)
C:\Users\sosai\BRICK\BRICK-watchdog.ps1
```

### BRICK-watchdog.ps1
Monitorea puertos 8000 y 8001 cada 30s. Si alguno cae, mata todos los Python y los relanza.
Archivo: `C:\Users\sosai\BRICK\BRICK-watchdog.ps1`

---

## REGLAS DE ORO — ABSOLUTAS

1. **Agente** → TODO cambio de lógica va en `BRICK-auth/backend/routers/agent.py` (8001)
2. **DELETE masivo** → NUNCA en lista del dialer sin backup previo con `backup_list_to_sqlite()`
3. **Hangup** → usar agc/api.php como primario. MySQL directo deja al agente en DEAD
4. **CORS** → `allow_credentials=False` — True + wildcard es inválido por spec
5. **Túnel SSH** → siempre en ASUS, dos terminales: una bloqueada (túnel), una libre (comandos)
6. **Start/Stop y Billing** → SOLO visibles para superadmin (isMaster)
7. **Routing** → TODO agente en 8001. Admin/datos en 8000
8. **V19 Standard** → toda operación destructiva en masa DEBE tener `/preview` antes del ejecutor
9. **Sin referencias al dialer** → NUNCA mencionar el nombre del dialer en UI, copy, o labels del frontend. Usar "backend", "sistema", "dialer" genérico
10. **SSH desde Mac** → `chmod 600 ~/.ssh/vicidial_key` antes de usar

---

## CREDENCIALES CRÍTICAS

| Sistema | Usuario | Password |
|---|---|---|
| Dialer MySQL | cron | 1234 (DB: asterisk) |
| Dialer APIUSER | APIUSER | wscfjqwo3yr1092ruj123t |
| Dialer Server SSH | root | 144.126.146.250 |
| ResImpli API | — | 2eea1a4bd7164b8888a5a2c97fd26560 |
| BRICK superadmin | super@brick.com | (ver seed.py) |

---

## BRANDING — REGLAS

- Producto: **BRICK**
- Empresa: **BRICK LLC**
- NO mencionar el dialer por nombre en ningún lugar del frontend
- Subdomain del superadmin: `brick`
- Email superadmin: `super@brick.com`
- Login URL reference: `.brick.com`

---

## MULTI-TENANT — ARQUITECTURA

### Dos bases de datos de tenants (deben estar en sync)

| DB | Tabla | Quién la usa | Qué guarda |
|---|---|---|---|
| SQLite (BRICK 8000) | `tenants` | Data Burner, Admin | tenant_id, tenant_name, campaign_id, role, active |
| PostgreSQL (Auth 8001) | `tenants` | JWT, login, users, CRM | id (UUID), name, subdomain, status, max_seats |

### Tabla `tenants` SQLite
```sql
CREATE TABLE IF NOT EXISTS tenants (
    tenant_id   TEXT PRIMARY KEY,   -- ej: "bossbuy_main"
    tenant_name TEXT NOT NULL,       -- ej: "BossBuy LLC"
    campaign_id TEXT,               -- campaña del dialer asignada
    role        TEXT DEFAULT 'client',
    active      INTEGER DEFAULT 1
);
INSERT OR IGNORE INTO tenants (tenant_id, tenant_name, campaign_id)
VALUES ('bossbuy','BossBuy','IBFEO');
```
- Auto-migra desde `burner_tenants` si existe (backward compat)
- UN row por campaña. Un cliente con 3 campañas = 3 rows
- Todos los endpoints usan `tenant_id`. Helper `get_campaign_for_tenant(tenant_id)` resuelve a `campaign_id`

### isMaster — lógica frontend
```ts
const isMaster = getTokenPayload()?.role === 'superadmin'
// isMaster: ve todos los tenants, dropdowns visibles, Start/Stop disponible
// Non-master: auto-select por subdomain del JWT, sin dropdowns de admin
```

---

## TENANT MANAGER — WORKFLOW V2 (Abril 2026)

**Principio**: El dialer es source of truth. Campañas, Listas y DIDs se crean MANUALMENTE en el dialer. BRICK solo registra lo que ya existe.

### Flujo para nuevo cliente
```
1. Crear en el dialer (manual):
   - Campaña(s)
   - Lista(s) por campaña
   - DIDs asignados

2. En BRICK → Admin → Tenant Manager → "Sync Tenant with Backend":
   - Seleccionar campañas del cliente (muestra las no asignadas)
   - Llenar: nombre, subdomain, admin email/password, nombre/apellido
   - Ejecutar → crea en PostgreSQL (auth tenant + admin user) + SQLite (row por campaña)

3. En tab "Users":
   - Crear agentes, supervisores, etc. para el tenant
   - Asignar ViciDial User a cada agente
```

### Tenant Manager — 3 Tabs
| Tab | Función |
|---|---|
| **Tenants** | Lista tenants en BRICK SQLite. Botón Sync abre wizard de 3 pasos |
| **Scripts** | Editor de script de llamada por campaña. Guardado en SQLite `campaign_scripts` |
| **Users** | Lista TODOS los users de TODOS los tenants. Crear, editar, desactivar |

### Tabla `campaign_scripts` SQLite (nueva, Abril 2026)
```sql
CREATE TABLE IF NOT EXISTS campaign_scripts (
    campaign_id TEXT PRIMARY KEY,
    script      TEXT NOT NULL DEFAULT '',
    updated_at  TEXT
);
```
Variables disponibles en scripts: `[NOMBRE]` `[TELEFONO]` `[DIRECCION]` `[CIUDAD]` `[ESTADO]` `[AGENTE]`

---

## ENDPOINTS — MAPA COMPLETO

### BRICK Backend (8000) — `app/routes_admin.py`
```
GET    /api/admin/tenants                      → lista tenants SQLite
POST   /api/admin/tenants/{id}/toggle          → activa/desactiva tenant
DELETE /api/admin/tenants/{id}                 → elimina tenant de SQLite
GET    /api/admin/vici/campaigns/unassigned    → campañas del dialer sin BRICK tenant
POST   /api/admin/tenants/sync                 → registra tenant (llama 8001 + escribe SQLite)
GET    /api/admin/scripts/{campaign_id}        → obtiene script de llamada
PUT    /api/admin/scripts/{campaign_id}        → guarda script de llamada
```

### Auth Backend (8001) — `routers/tenants.py` + `routers/admin_users.py`
```
POST   /api/tenants                            → crea tenant + admin user (superadmin)
GET    /api/tenants                            → lista tenants (superadmin)
PATCH  /api/tenants/{id}                       → edita tenant
GET    /api/admin/tenants-with-users           → tenants con conteo de usuarios activos
GET    /api/admin/users                        → todos los users (filtro: tenant_id, role, is_active)
POST   /api/admin/users                        → crea user para cualquier tenant
PATCH  /api/admin/users/{id}                   → edita rol, vici_user, password
DELETE /api/admin/users/{id}                   → desactiva user
```

### BRICK Backend (8000) — Otros routers clave
```
# Data Burner
GET    /api/burner/tenants                     → lista tenants activos (para dropdown)
GET    /api/burner/status?tenant_id=X          → estado del agente remoto
POST   /api/burner/toggle                      → START/STOP agente remoto
GET    /api/burner/kpis?tenant_id=X            → KPIs tiempo real
GET    /api/burner/summary?tenant_id=X         → resumen 7 días
GET    /api/burner/billing?tenant_id=X         → minutos facturados
POST   /api/burner/push/preview?tenant_id=X    → preview push de leads (V19)
POST   /api/burner/push?tenant_id=X            → ejecuta push de leads
GET    /api/burner/export?tenant_id=X          → descarga CSV (3 buckets)

# Admin / Módulos
POST   /api/upload/sync                        → upload leads → dialer
GET    /api/skiptrace/...                      → skip trace ResImpli
GET    /api/vici/campaigns                     → lista campañas del dialer
GET    /api/dashboard/...                      → analytics y reportes
GET    /api/export/...                         → exportación de datos
```

---

## DATA BURNER — LÓGICA COMPLETA

### Configuración
- Remote Agent: `user_start=9999`, `campaign_id` = campaña del tenant
- AMD: `cpd_amd_action=DISPO`, `amd_send_to_vmx=Y`
- Horario: 7am–8pm EST — watchdog auto-stop/start
- Primer START: SIEMPRE manual desde UI

### Ciclo de vida
1. Admin hace START manual → `manual_stop=false` en SQLite config
2. Scheduler (cada 30s) verifica horario → reactiva si no es `manual_stop=true`
3. Admin hace STOP manual → `manual_stop=true` → scheduler NO reactiva
4. Admin hace START de nuevo → `manual_stop=false` → scheduler vuelve a controlar
5. Día 7 desde primer START → freno duro: INACTIVE + `burned_complete=true`

### `manual_stop` flag
```python
# En toggle endpoint:
if action == "START":
    set_burner_config(campaign_id, "manual_stop", "false")
elif action == "STOP":
    set_burner_config(campaign_id, "manual_stop", "true")

# En _process_schedule:
manual_stop = get_burner_config(campaign_id, "manual_stop")
if not burned and manual_stop != "true" and 7 <= hour < 20:
    # reactivar
```

### 3 Buckets
| Bucket | Statuses | Acción |
|---|---|---|
| ANSWERED | AL | Push como NEW |
| POSSIBLE WORKING | NA / AB < 5 intentos en 7 días | Push como NEW |
| EXCLUDED | DROP / PDROP / AA / DNCL / DNC | NUNCA se toca |

### SQLite config keys
Formato: `{key}__{campaign_id}` — ej: `first_start_done__IBFEO`, `manual_stop__IBFEO`

### Datos reales verificados — BossBuy/IBFEO (4 Abril 2026)
| Status | Llamadas | Min. Facturados |
|---|---|---|
| AL | 260 | 236 |
| DROP | 56 | 4 |
| NA | 148 | 0 |
| PDROP | 45 | 0 |
| **TOTAL** | **521** | **240** — $2.40 |

---

## AGENT UI — LÓGICA CLAVE

- **Resume**: `agc/api.php?action=pause_agent&pause_code=RESUME`
- **Pause**: `PAUSE!{epoch}` como pause_code
- **Hangup**: `agc/api.php` como primario — MySQL directo deja al agente en DEAD
- **Disposiciones activas**: SET NI DEADL AMD PS INFLU CB NA WN DNC
- **CRM_DISPOS**: solo SET y NI muestran "Push to CRM"
- **Polling**: 1s con fire inmediato al montar
- **Customer hung up**: detectado vía `agent_status`, dispara `_autoResume()`
- **Agent name**: 3 capas de fallback
- **Back button**: protegido
- **Chrome Extension**: `window.postMessage(BRICK_PUSH_CRM)` → content.js → background.js → llena ResImpli

### agent_status pipe (CRÍTICO)
```
parts[0] = status (INCALL, PAUSED, etc.)
parts[1] = uniqueid (V... — NO es el lead_id)
parts[2] = lead_id  ← ESTE es el correcto
```

---

## ESTÁNDAR V19 — OPERACIONES DESTRUCTIVAS

Toda UPDATE/DELETE masiva requiere dos endpoints:
1. `POST /api/.../preview` → SELECT COUNT(*) con mismo WHERE → retorna breakdown sin ejecutar
2. `POST /api/...` → ejecuta solo si usuario confirmó

Implementado en: Data Burner Push (`/api/burner/push/preview` + `/api/burner/push`)

---

## FRONTEND — MÓDULOS

| Módulo | Ruta | Acceso | Estado |
|---|---|---|---|
| Sync Data | `/admin/sync` | todos | ✅ |
| Add Skip Trace | `/admin/skip-trace` | todos | ✅ |
| Find a Number | `/admin/search` | todos | ✅ |
| Reports | `/admin/reports` | todos | ✅ |
| Property Data | `/admin/property-data` | todos | ✅ |
| CRM Pipeline | `/admin/crm/pipeline` | todos | ✅ |
| Data Burner | `/admin/burn` | todos (dropdown solo master) | ✅ |
| Tenant Manager | `/admin/tenants` | **solo isMaster** | ✅ V2 |
| Direct Mail | `/admin/direct-mail` | todos | 🔒 Add-on |

### Roles en frontend
```ts
// AdminLayout.tsx
const isMaster = getTokenPayload()?.role === 'superadmin'
const visibleModules = isMaster ? [...MODULES, ...MASTER_MODULES] : MODULES
```

---

## ARCHIVOS CLAVE

### BRICK Backend (8000)
| Archivo | Función |
|---|---|
| `app/main.py` | FastAPI app, routers, CORS |
| `app/routes_admin.py` | Tenants CRUD, Sync, Scripts |
| `app/routes_burner.py` | Data Burner completo |
| `app/routes_agent.py` | Agente (proxy a 8001) |
| `app/routes_upload.py` | Sync leads al dialer |
| `app/routes_vici.py` | Campañas, listas (lectura dialer) |
| `app/vici_connector.py` | Conexión MySQL via túnel 3307 |
| `app/database.py` | SQLite — ruta ABSOLUTA |

### Auth Backend (8001)
| Archivo | Función |
|---|---|
| `main.py` | FastAPI app, lifespan, CORS |
| `routers/agent.py` | Lógica agente, disposiciones, hangup |
| `routers/tenants.py` | CRUD tenants PostgreSQL |
| `routers/users.py` | CRUD users (scoped a tenant) |
| `routers/admin_users.py` | CRUD users cross-tenant (superadmin) |
| `routers/auth.py` | Login, JWT |
| `models.py` | SQLAlchemy models |
| `schemas.py` | Pydantic schemas |
| `auth.py` | JWT decode, require_roles helpers |

### Frontend
| Archivo | Función |
|---|---|
| `src/App.tsx` | Rutas |
| `src/components/AdminLayout.tsx` | Shell admin, tabs, isMaster |
| `src/api/client.ts` | axios clients: `client` (8001), `brickClient` (8000) |
| `src/pages/admin/TenantManager.tsx` | Tenant Manager V2 (3 tabs) |
| `src/pages/admin/DataBurner.tsx` | Data Burner UI |
| `src/pages/Agent.tsx` | Agent UI + Chrome Extension bridge |
| `src/pages/Login.tsx` | Login con subdomain (.brick.com) |

---

## DIAGNÓSTICO — PROBLEMAS COMUNES

### Backend no responde
```powershell
# Verificar puertos
netstat -ano | findstr ":8000 :8001"

# Reiniciar 8000
cd C:\Users\sosai\BRICK; uvicorn app.main:app --port 8000

# Reiniciar 8001
cd C:\Users\sosai\BRICK-auth\backend; python main.py
```

### Túnel SSH caído
```powershell
netstat -ano | findstr :3307
# Si no hay salida → reiniciar túnel:
ssh -i C:\Users\sosai\.ssh\vicidial_key -N -L 3307:localhost:3306 root@144.126.146.250
```

### UI no actualizada después de git push
```powershell
cd C:\Users\sosai\BRICK-frontend; git pull origin main
# Reload browser (Vite hace HMR automático si está corriendo)
```

### Endpoint 404
```powershell
Select-String "admin" C:\Users\sosai\BRICK\app\main.py
```

### SSH desde Mac (dialer server)
```bash
chmod 600 ~/.ssh/vicidial_key
ssh -i ~/.ssh/vicidial_key root@144.126.146.250 "mysql -u cron -p1234 asterisk -e \"SELECT ...\""
```

### Campaña creada por SQL no aparece en dialer UI
Problema de permisos de user group. Fix:
```sql
UPDATE vicidial_user_groups
SET allowed_campaigns = CONCAT(IFNULL(allowed_campaigns,''), 'CAMPID-')
WHERE group_id = 'ADMIN';
```

---

## SQL DE LIMPIEZA — PENDIENTE (correr en ASUS una sola vez)
```sql
-- PostgreSQL (8001)
DELETE FROM tenants WHERE subdomain = 'acme';
UPDATE tenants SET name = 'BRICK', subdomain = 'brick' WHERE subdomain = 'system';
UPDATE users SET email = 'super@brick.com' WHERE email = 'super@dialflow.com';

-- Verificar:
SELECT id, name, subdomain FROM tenants;
SELECT email, role FROM users;
```
```powershell
# SQLite (8000)
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

---

## PENDIENTE

| # | Feature | Prioridad | Notas |
|---|---|---|---|
| 1 | Push to CRM (Chrome Extension) | Alta | Reescrito, no probado en llamada real |
| 2 | County Link | Media | Endpoint existe, verificar con datos reales en PropertyMaster |
| 3 | SQL de limpieza DialFlow→BRICK | Alta | Ver sección arriba — PostgreSQL + SQLite |
| 4 | Deprovision tenant | Media | Botón "Eliminar tenant" en TM → borra SQLite + llama 8001 + dialer |
| 5 | Campaña en dialer no visible tras crear vía SQL | Conocido | Fix: UPDATE vicidial_user_groups (ver diagnóstico) |

---

## LECCIONES APRENDIDAS — HISTORIAL COMPLETO

| ID | Lección | Detalle |
|---|---|---|
| F1 | SQLite ruta relativa = riesgo | Usar ruta absoluta siempre |
| F2 | CORS credentials + wildcard inválido | allow_credentials=False con allow_origins=[*] |
| F3 | agent_status pipe: parts[2] = lead_id | parts[1]=uniqueid (V...) NUNCA es el lead_id |
| F4 | Columnas del dialer | address1 (no address), postal_code (no zip_code) |
| F5 | Chrome Extension worlds | executeScript world:MAIN para SPA frameworks |
| F6 | agc/api.php params obligatorios | Si falta CUALQUIER param → ERROR: Invalid Username/Password |
| F7 | Túnel SSH siempre en ASUS | Donde corre el backend, ahí corre el túnel |
| F8 | Remote Agent GUI bug | El panel del dialer no guarda Remote Agents. Usar SQL directo |
| F9 | called_since_last_reset no borra historial | Solo es una bandera. Log del dialer sigue intacto |
| F10 | Data Burner por vueltas no por días | El hopper se vacía por leads, no por reloj |
| F11 | Costo real del Burner = todos los statuses | AL domina pero DROP también puede facturar |
| F12 | Túnel SSH: dos terminales siempre | Terminal 1: túnel bloqueado. Terminal 2: SSH para comandos |
| F13 | Dropdown vacío ≠ bug de código | Primero verificar git pull en ASUS antes de depurar |
| F14 | Data Burner dropdown = tenants, no campañas | La campaña es un detalle interno, el usuario ve nombre del cliente |
| F15 | Tabla burner → `tenants` con auto-migración | Migra `burner_tenants` automáticamente. Param API = `tenant_id` |
| F16 | Non-master no ve dropdown | Se auto-seleccionan por subdomain del JWT |
| F17 | manual_stop previene que el scheduler sobreescriba STOP manual | Sin este flag, scheduler reactiva el agente en horario aunque admin lo haya parado |
| F18 | PowerShell usa `;` no `&&` | `&&` no es válido en PowerShell para encadenar comandos |
| F19 | Backend debe reiniciarse después de git pull | uvicorn carga el código en memoria al arrancar — git pull no afecta al proceso vivo |
| F20 | Campaña creada via SQL no aparece en dialer UI | Dialer filtra por user group. Fix: UPDATE vicidial_user_groups SET allowed_campaigns |
| F21 | SSH key en Mac necesita chmod 600 | Sin permisos correctos, SSH ignora la llave y pide password |
| F22 | Sin referencias al dialer en UI | Regla de branding: usar términos genéricos. Nunca el nombre del vendor |
| F23 | Un auth tenant por cliente, múltiples rows SQLite | auth usa subdomain único. SQLite tiene 1 row por campaña del cliente |

---

## REFERENCIA HISTÓRICA
- V1–V10: Arquitectura base, Agent UI, disposiciones
- V11–V15: Skip Trace, Export, CRM Pipeline
- V16–V17: Data Burner v1, Multi-tenant base
- V18.1.2: Data Burner completo, burner_tenants, Billing, Push V19
- **V19**: Refactor tenants (burner_tenants→tenants), manual_stop, BRICK rebranding, BRICK-watchdog.ps1
- **V20 (sesión actual)**: Tenant Manager V2 (Sync + Scripts + Users), Auth /api/admin/* cross-tenant, SSH Mac fix, sin referencias al dialer en UI
