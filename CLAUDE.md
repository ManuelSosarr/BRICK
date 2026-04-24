# BRICK — CLAUDE.md
## Última actualización: 13 de Abril, 2026 | Referencia: BRICK_Handover_V25

---

## REGLAS DE SESIÓN — CLAUDE CODE

### Un chat activo a la vez
Claude Code crea un **git worktree** por cada chat nuevo (branch `claude/nombre`). Si abres 3 chats en paralelo y editas los mismos archivos, puedes crear conflictos.

**Regla:** Un solo chat activo trabajando en BRICK a la vez. Cierra los demás cuando termines una sesión.

### Repos involucrados
| Repo | Ruta Mac | GitHub |
|---|---|---|
| BRICK-auth (8001) | `/Users/manny.sosa/Documents/dialflow` | `ManuelSosarr/BRICK-auth` |
| BRICK backend (8000) + frontend | `/Users/manny.sosa/vicidial-app/` | — (solo en ASUS) |
| BRICK frontend | `/Users/manny.sosa/Documents/dialflow/frontend` | `ManuelSosarr/BRICK-frontend` |

### REGLA DE ORO — Comandos en ASUS
Cada vez que se necesite correr un comando en ASUS, SIEMPRE escribir explícitamente:
**"Corre esto en ASUS PowerShell:"** antes del bloque de código. Sin excepción.

### Cómo limpiar worktrees muertos (Mac Terminal)
```bash
cd /Users/manny.sosa/Documents/dialflow
git worktree list          # ver qué hay activo
git worktree remove .claude/worktrees/NOMBRE --force
git branch -d claude/NOMBRE
```
Antes de borrar: verificar que la branch ya está en main:
```bash
git branch --merged main   # si aparece ahí, es seguro borrar
```

### Workflow de sesión correcto
1. Abrir **un solo** chat de Claude Code
2. Trabajar, hacer commits, push a GitHub
3. En ASUS: `git pull origin main` para cada repo
4. Cerrar el chat cuando termines
5. La próxima sesión arranca con CLAUDE.md actualizado = contexto completo

---

## ARQUITECTURA GENERAL

| Componente | Ruta (ASUS) | Puerto | Descripción |
|---|---|---|---|
| BRICK Backend | `C:\Users\sosai\BRICK\app\` | 8000 | SQL, skiptrace, export, Data Burner, Admin |
| Auth Backend | `C:\Users\sosai\BRICK-auth\backend\` | 8001 | JWT, agente, sesiones, tenants, users |
| Frontend | `C:\Users\sosai\BRICK-frontend\src\` | 5173 | React 19 + TypeScript + Vite |
| SQLite | `C:\Users\sosai\BRICK\vicidial.db` | — | Solo campaign_scripts y Burner config keys (NO tenants) |
| MySQL Dialer | túnel SSH 127.0.0.1:3307 | 3307 | cron / 1234 / asterisk |
| PostgreSQL Auth | docker en ASUS | 5432 | Tenants, Users, Leads, CRM |

### Infraestructura
- **ASUS** = máquina de producción Windows. Aquí corren TODOS los backends y el túnel SSH.
- **Mac** = desarrollo. `git push` desde Mac, `git pull` en ASUS.
- **Dialer Server**: root@144.126.146.250
- **Túnel SSH**: llave en `C:\Users\sosai\.ssh\vicidial_key` (ASUS) y `~/.ssh/vicidial_key` (Mac)
- **NGROK**: tunneling del frontend para acceso externo — se lanza MANUALMENTE (no en BRICK.ps1). Ver popup al iniciar BRICK.

### Startup completo (ASUS — BRICK.ps1)
```powershell
# Mata python y node existentes
# Levanta Docker (BRICK-auth)
# Auth backend (8001) — git pull + pip install + python main.py
# BRICK backend (8000) — git pull + uvicorn --reload --port 8000
# Frontend — git pull + npm run dev --host 0.0.0.0 --port 5173
# Túnel SSH al dialer — -L 3307:127.0.0.1:3306 root@144.126.146.250
# Abre browser http://localhost:5173
# Popup con instrucciones de NGROK (manual)
```
**NGROK — arranque manual** (NO está en BRICK.ps1):
```powershell
ngrok http 5173
# Ver URL pública en http://localhost:4040
```

### ⚠️ Acceso directo BRICK.lnk — Problema conocido post-Windows Update

**Síntoma:** Doble clic en el acceso directo del Desktop no hace nada.

**Causa:** Windows Update puede mover el Desktop de `C:\Users\sosai\Desktop` a
`C:\Users\sosai\OneDrive\Desktop`. El `.lnk` queda apuntando al path viejo y no encuentra el script.

**Diagnóstico rápido:**
```powershell
$sh = New-Object -ComObject WScript.Shell
$lnk = $sh.CreateShortcut("C:\Users\sosai\OneDrive\Desktop\BRICK.lnk")
$lnk | Select-Object TargetPath, Arguments
# Si Arguments apunta a C:\Users\sosai\Desktop\... (sin OneDrive) → está roto
```

**Fix (reparar el acceso directo):**
```powershell
$sh = New-Object -ComObject WScript.Shell
$lnk = $sh.CreateShortcut("C:\Users\sosai\OneDrive\Desktop\BRICK.lnk")
$lnk.TargetPath = "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
$lnk.Arguments = '-ExecutionPolicy Bypass -File "C:\Users\sosai\OneDrive\Desktop\BRICK.ps1"'
$lnk.WorkingDirectory = "C:\Users\sosai\OneDrive\Desktop"
$lnk.Save()
# Activar "Ejecutar como administrador"
$bytes = [System.IO.File]::ReadAllBytes("C:\Users\sosai\OneDrive\Desktop\BRICK.lnk")
$bytes[0x15] = $bytes[0x15] -bor 0x20
[System.IO.File]::WriteAllBytes("C:\Users\sosai\OneDrive\Desktop\BRICK.lnk", $bytes)
```

**Prevención:** Después de cualquier Windows Update, verificar que el acceso directo aún funciona.
Si falla, correr el bloque de fix de arriba.

### BRICK-watchdog.ps1
Monitorea puertos 8000 y 8001 cada 30s. Si alguno cae, mata todos los Python y los relanza.
Archivo: `C:\Users\sosai\BRICK\BRICK-watchdog.ps1`

---

## FUENTES DE VERDAD — CUÁL DB PARA QUÉ

| Dato | Base de datos | Dónde |
|---|---|---|
| Tenants + Users | PostgreSQL 5432 | BRICK-auth (8001) + lectura directa en 8000 vía psycopg2 |
| VicidialConfig (campaign_ids) | PostgreSQL 5432 | tabla `vicidial_configs`, campo `campaign_ids` JSON |
| Campaign Scripts | SQLite `vicidial.db` | tabla `campaign_scripts` — son config de BRICK, no de auth |
| Burner config keys | SQLite `vicidial.db` | claves como `manual_stop__IBFEO`, `first_start_done__IBFEO` |
| Leads / Dialing | MySQL Dialer (via túnel) | `vicidial_list`, `vicidial_campaigns` |

**Regla:** NUNCA volver a escribir tenants en SQLite. PostgreSQL es la única fuente de verdad para tenants.

### Migración realizada (6 Abril 2026)
- `routes_admin.py` ahora lee tenants de PostgreSQL via `psycopg2` directo (sin HTTP a 8001)
- SQLite dejó de ser fuente de verdad para tenants
- Script de migración: `migrate_tenants_to_pg.py` — copió tenants SQLite → PostgreSQL (one-time)
- `psycopg2-binary==2.9.10` agregado a `requirements.txt`

---

## REGLAS DE ORO — ABSOLUTAS

1. **Agente** → TODO cambio de lógica va en `BRICK-auth/backend/routers/agent.py` (8001)
2. **DELETE masivo** → NUNCA en lista del dialer sin backup previo con `backup_list_to_sqlite()`
3. **Hangup** → usar agc/api.php como primario. MySQL directo deja al agente en DEAD
4. **CORS** → `allow_credentials=False` — True + wildcard es inválido por spec
5. **Túnel SSH** → siempre en ASUS, dos terminales: una bloqueada (túnel), una libre (comandos)
6. **Start/Stop** → visibles para TODOS los tenants. **Billing y Reset View** → SOLO superadmin (isMaster)
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
| **Tenants** | Lista tenants en BRICK SQLite. Botón Sync abre wizard de 4 pasos |
| **Scripts** | Redirect al Script Flow Editor |
| **Users** | Lista TODOS los users de TODOS los tenants. Crear, editar, desactivar |

### Wizard Sync — 4 pasos
1. **Campañas** — checkboxes con campañas no asignadas en BRICK
2. **Listas** — checkboxes multi-select por campaña (usa `/api/burner/lists` — NO `/api/vici/lists` que filtra por tenant)
3. **Info Tenant** — nombre, subdomain, admin email/pwd/nombre
4. **Confirmar** — review y ejecutar

**Nota crítica**: En el paso 2, usar siempre `/api/burner/lists?campaign_id=X`. `/api/vici/lists` filtra por tenant_id del JWT — el superadmin no tiene tenant_id, devuelve vacío.

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
POST   /api/burner/toggle                      → START/STOP agente + SSH AST_VDauto_dial
GET    /api/burner/weekly?tenant_id=X          → resumen 7 días (PWORK/EXCLUD/AL)
GET    /api/burner/minutes?tenant_id=X         → minutos facturados (solo isMaster)
GET    /api/burner/lists?campaign_id=X         → listas activas de una campaña (sin restricción de tenant)
POST   /api/burner/push/preview                → preview push (source_tenant_id + destination_campaign_id)
POST   /api/burner/push                        → ejecuta push {tenant_id, dest_list_id}
GET    /api/burner/export?tenant_id=X          → CSV (3 secciones: AL, Elegibles, Excluidos) + setea csv_downloaded flag
GET    /api/burner/cycle-status?tenant_id=X   → {list_complete, csv_downloaded, push_done}
POST   /api/burner/reset                       → verifica 3 flags, DELETE leads, limpia flags

# Script Library (routes_admin.py)
GET    /api/admin/scripts/library              → lista scripts con assignments
POST   /api/admin/scripts/library/import       → upload file (drawio/xml/json/pdf/jpg/png)
GET    /api/admin/scripts/library/{id}/content → sirve bytes raw (PDF/imagen)
PUT    /api/admin/scripts/library/{id}/assign  → asigna lista de campaign_ids
DELETE /api/admin/scripts/library/{id}         → elimina script + assignments
GET    /api/admin/vici/campaigns/all           → todas las campañas del dialer (para assignment UI)

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

### Configuración crítica IBFEO (10 Abril 2026)
- `available_only_ratio_tally = N` → motor no depende de agentes humanos activos
- `AST_VDauto_dial.pl --campaign=IBFEO --loop` corre en el servidor ViciDial — arrancado/parado via SSH desde `routes_burner.py` toggle START/STOP
- `AL` removido de `dial_statuses` → Burner nunca re-llama a quien ya contestó
- `AL` protegido con `called_since_last_reset='Y'` via UPDATE directo

### 3 Buckets (statuses actualizados — 10 Abril 2026)
| Bucket | Status | Acción |
|---|---|---|
| ANSWERED | `AL` | Push como NEW |
| POSSIBLE WORKING | `PWORK` | Push como NEW — reemplaza NA/AB |
| EXCLUDED | `EXCLUD` | NUNCA se toca — reemplaza DROP/PDROP/AA/DNCL/DNC |

**Todos los endpoints actualizados**: `export`, `weekly`, `push`, `push/preview`, `_process_hopper` usan `PWORK` y `EXCLUD`.

### Lista de datos
- Lista **808** — 2,388 leads cargados del Master Global Clean (10 Abril 2026)

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

### SSH toggle — AST_VDauto_dial
```python
# START: lanza motor en ViciDial via SSH
nohup /usr/share/astguiclient/AST_VDauto_dial.pl --campaign={id} --loop > /dev/null 2>&1 &
# STOP: mata proceso
pkill -f 'AST_VDauto_dial.pl --campaign={id}'
# Llave: C:\Users\sosai\.ssh\vicidial_key | Host: root@144.126.146.250
```

---

## AGENT UI — LÓGICA CLAVE

- **Resume**: `UPDATE external_pause='RESUME'` via MySQL ✅
- **Pause**: `UPDATE external_pause='PAUSE!{epoch}'` via MySQL ✅
- **Hangup**: `UPDATE external_hangup='Y'` via MySQL — `agentHungUp.current=true` antes de la llamada para que el polling no lo interprete como "customer hung up" ✅
- **Disposiciones activas**: SET, NI, DEADL, AMD, PS, INFLU, CB, NA, WN, DNC
  - `AMD` → `WNA` en STATUS_MAP (logic_classification.py)
  - `PS` → `WNR` en STATUS_MAP (agregado 6 Abril 2026)
  - `INFLU` → `WNR` en STATUS_MAP
- **CRM_DISPOS**: solo SET y NI muestran "Push to CRM"
- **Polling**: 1s con fire inmediato al montar
- **Customer hung up detection**: `noLeadCount` ref cuenta polls consecutivos sin lead. A los **2 polls seguidos sin lead** dispara la detección — independiente de `vici_status` (elimina fallos cuando ViciDial retorna UNKNOWN transitoriamente) ✅
- **Auto-resume tras dispo**: `_autoResume()` llama `setStatus('waiting')` al inicio (optimistic) antes de hacer API calls. UI cambia de inmediato. ✅
- **Dispo lag eliminado**: `handleSaveDispo` corre POST dispo y 300ms grace en paralelo (`Promise.all`). Era 800ms secuencial. ✅
- **Logout (botón)**: `handleLogout()` → llama `/api/agent/logout` + limpia localStorage + navega a `/login` ✅
- **Back button + tab close**: `useEffect` en `loggedIn` registra `popstate` + `beforeunload` → `fetch` con `keepalive:true` para completar logout aunque el componente se desmonte ✅
- **Agent name**: 3 capas de fallback
- **Chrome Extension**: `window.postMessage(BRICK_PUSH_CRM)` → content.js → background.js → llena ResImpli

### agent_status pipe (CRÍTICO)
```
parts[0] = status (INCALL, PAUSED, etc.)
parts[1] = uniqueid (V... — NO es el lead_id)
parts[2] = lead_id  ← ESTE es el correcto
```

### Ciclo completo de llamada (actualizado — 13 Abril 2026)
```
1. Agent press Resume → external_pause='RESUME' → await asyncio.sleep(2) → clear → ViciDial inicia dialing
2. Polling detecta lead → status='oncall', timer inicia, noLeadCount=0
3a. Agent press Hangup → agentHungUp=true → external_hangup='Y' → dispo panel abre inmediatamente
3b. Customer cuelga → noLeadCount++ por 2 polls consecutivos → banner rojo + dispo panel abre (robusto vs UNKNOWN)
4. Agent selecciona dispo → external_status UPDATE en ViciDial (POST dispo + 300ms en paralelo)
5. _autoResume() → setStatus('waiting') optimistic → chequea ViciDial → Resume → vuelta al paso 1
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
| `src/pages/admin/TenantManager.tsx` | Tenant Manager V2 (3 tabs: Tenants, Scripts→redirect, Users) |
| `src/pages/admin/ScriptFlowEditor.tsx` | Editor visual Lucidchart-style (ReactFlow) — palette izq, canvas centro, props derecha |
| `src/pages/admin/DataBurner.tsx` | Data Burner UI |
| `src/pages/Agent.tsx` | Agent UI — call cycle completo, back button protection, auto-resume |
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

## REVISIÓN DE CÓDIGO — 13 Abril 2026

Auditoría general completada. Resultado: 3 categorías. Lo que se hizo y lo que se dejó conscientemente.

### ✅ Corregido en esta sesión
| Fix | Archivo | Detalle |
|---|---|---|
| `time.sleep(2)` → `asyncio.sleep(2)` | `routers/agent.py` | Bloqueaba el event loop completo en Resume y Pause. Ahora cierra conexión antes del await, abre nueva conexión limpia después. |
| `print()` → `logger.info()` | `dialflow/backend/main.py` | Debug print en startup reemplazado con logger estándar. |
| `noLeadCount` — detección robusta | `Agent.tsx` | Conteo de polls consecutivos sin lead en lugar de validar `vici_status !== 'UNKNOWN'`. |
| Optimistic dispo | `Agent.tsx` | `setStatus('waiting')` al inicio de `_autoResume()` antes de API calls. Lag percibido eliminado. |
| `Promise.all` en dispo | `Agent.tsx` | POST dispo y 300ms grace en paralelo. Era 800ms secuencial. |

### ⛔ Dejado conscientemente — con razón documentada
| Issue | Por qué NO se toca ahora |
|---|---|
| Auth en endpoints de agente (`/resume`, `/pause`, `/hangup`, `/dispo`) | El interceptor 401 de `client.ts` hace `localStorage.clear()` + redirect a `/login`. Un token expirado mid-call dejaría al agente sin poder colgar ni guardar dispo. **Requiere token refresh automático primero.** |
| CORS wildcard en puerto 8000 | ASUS detrás de ngrok, acceso solo por red local/tunnel. Riesgo real es mínimo hasta servidor público. |
| Credenciales en config.py | Máquina cerrada (ASUS local). Riesgo aceptable en esta etapa. |
| `SECRET_KEY` con fallback de dev | Aceptable mientras ASUS no sea servidor público. |
| localStorage para JWT tokens | Estándar en SPAs. XSS requeriría comprometer el frontend primero. |

---

## CHECKLIST MIGRACIÓN A SERVIDOR PRIVADO

**Cuando BRICK se monte en servidor dedicado con IP estática, revisar estos puntos ANTES de lanzar.**

### Seguridad — Crítico
- [ ] **Auth en endpoints de agente** — Agregar `Depends(get_current_user)` a `/resume`, `/pause`, `/hangup`, `/dispo`, `/logout`, `/lead/{user}`. Implementar refresh automático de tokens primero para no bloquear agentes mid-call.
- [ ] **CORS restringido en puerto 8000** — Reemplazar `allow_origins=["*"]` con dominios específicos (igual que 8001 que ya usa `settings.ENVIRONMENT`).
- [ ] **SECRET_KEY forzado** — Hacer que el servidor falle en startup si `SECRET_KEY` no está en env vars: `if not SECRET_KEY: raise RuntimeError("SECRET_KEY not set")`.
- [ ] **Credenciales a variables de entorno** — Mover `PG_DSN`, `VICI_API_PASS`, `_VICI_DB` y URLs hardcodeadas a `.env` con `python-dotenv`. Nunca en código.
- [ ] **Webhook ViciDial con auth** — `/webhook/vici-dispo` necesita firma HMAC o token fijo en header para verificar que viene del dialer.
- [ ] **Rate limiting** — Agregar `slowapi` o middleware de rate limiting a endpoints públicos de login y webhook.

### Infraestructura
- [ ] **Rutas absolutas de Windows** → relativas o env vars. `DB_PATH = "C:/Users/sosai/BRICK/..."` rompe en Linux.
- [ ] **SSH key path** → variable de entorno con fallback: `SSH_KEY = os.getenv("VICI_SSH_KEY", "~/.ssh/vicidial_key")`.
- [ ] **httpOnly cookies** para JWT tokens en lugar de localStorage (si se migra a SSR o se endurece seguridad XSS).
- [ ] **PostgreSQL password** — cambiar `dialflow/dialflow` por credenciales fuertes en el nuevo servidor.
- [ ] **MySQL tunnel** — revisar si el nuevo servidor puede conectar directo al dialer o sigue necesitando tunnel SSH.

### Deuda técnica antes de escalar
- [ ] **Bare `except:` clauses** — reemplazar con `except Exception as e: logger.error(...)` para no perder errores silenciosos en producción.
- [ ] **Tenants aislados en queries** — verificar que agentes de un tenant no puedan ver/afectar leads de otro en endpoints de agent.py.
- [ ] **`console.warn` en Agent.tsx** — eliminar o rebajar a `console.debug` (visibles en console del agente).

---

## PENDIENTE

| # | Feature | Prioridad | Notas |
|---|---|---|---|
| 1 | **BRICK.ps1 en ASUS** — recoger todos los cambios pusheados | Alta | logout fix, optimistic UI, hopper fix, BossBuy campaigns, customer hang-up robustness, dispo lag, asyncio.sleep |
| 2 | SQL de limpieza DialFlow→BRICK | Alta | Ver sección arriba — PostgreSQL + SQLite |
| 3 | Push to CRM (Zapier → ResImpli) | Hold | Esperando pago ResImpli |
| 4 | GDrive upload post-sync | Hold | Necesita Service Account JSON Google Cloud en ASUS |
| 5 | Email notification post-sync | Hold | Necesita Gmail App Password en ASUS |
| 6 | County Link | Monitor | Apareciendo correctamente, monitorear con datos reales |
| 7 | Dedicated server + static IP | Q2 | Ver checklist de migración en sección arriba |
| 8 | Beta users onboarding | Esperar | Manuel avisa cuando estén listos |
| 9 | Auth en endpoints de agente | Q2 | Bloqueado hasta implementar token refresh. Ver checklist migración. |

### Variables de entorno pendientes en ASUS (para GDrive + Email)
```powershell
$env:GDRIVE_SERVICE_ACCOUNT_JSON = "C:/Users/sosai/BRICK/service_account.json"
$env:GDRIVE_FOLDER_ID            = "ID_DE_CARPETA_EN_DRIVE"
$env:NOTIFY_EMAIL_FROM           = "tu@gmail.com"
$env:NOTIFY_EMAIL_PASSWORD       = "xxxx xxxx xxxx xxxx"   # Gmail App Password
$env:NOTIFY_EMAIL_TO             = "sosa.infx@gmail.com"
```

## SCRIPT EDITOR — DECISIÓN

Flujo decidido: **draw.io → importar XML → guardar → asignar a campaña**.

1. Usuario diseña el script en [draw.io.com](https://draw.io.com)
2. Exporta como `.drawio` (XML)
3. En BRICK → Script Editor → botón "Importar .drawio"
4. Backend parsea XML con `drawio_parser.py` → convierte a ScriptNode dict
5. Script guardado en SQLite `campaign_scripts`
6. Agente ve el script durante la llamada (Agent.tsx soporta formato flat dict)

### Convenciones del script
- Variables: `{name}`, `{address}`, `{agent}`, `{owner_name}`
- Hints de coaching: `[HINT: texto]` en el nodo → extraído al campo `hint` por `_split_hint()`
- Script REI completo: `backend/sample_scripts/rei_script.json`

### Archivos clave
- `app/drawio_parser.py` — parser XML → ScriptNode dict (con `_split_hint` wired)
- `app/routes_admin.py` — `POST /api/admin/scripts/{campaign_id}/import-drawio`
- `frontend/src/pages/admin/ScriptFlowEditor.tsx` — botón "Importar .drawio"
- `frontend/src/pages/Agent.tsx` — soporta formato A (flat dict draw.io) y formato B (ReactFlow JSON)

### COMPLETADO en sesión V24 (11 Abril 2026)

**ngrok / acceso externo:**
- ✅ `client.ts` hardcodea `/auth-api` y `/brick-api` — sin env vars que puedan sobreescribir
- ✅ `.env.development` y `.env.production` limpiados (ya no contienen URLs absolutas de localhost)
- ✅ `vite.config.ts` — proxy Vite: `/auth-api` → 8001, `/brick-api` → 8000 (server-side, transparente para ngrok)
- ✅ `BRICK.ps1` — agrega `npm install` antes de `npm run dev` para garantizar deps actualizadas

**BRICK-auth (8001):**
- ✅ `requirements.txt` — agregado `pymysql==1.1.1` (faltaba, causaba crash en arranque)
- ✅ `routers/agent.py` — renombrado `get_db()` local a `_get_vici_conn()` para evitar naming collision con `from database import get_db`
- ✅ `GET /api/agent/campaigns` — nuevo endpoint: lee `vicidial_configs.campaign_ids` del tenant del JWT. Agent dropdown ahora usa campañas reales por tenant (no hardcodeadas)

**Script Library (ScriptFlowEditor):**
- ✅ `ScriptFlowEditor.tsx` — reescrito completo como gestión de biblioteca (NO editor de nodos). Tabla: Nombre | Tipo | Campañas | Fecha. Import modal (drag-drop), assignment modal (checkboxes por campaña), delete
- ✅ `routes_admin.py` — tablas SQLite `scripts` + `script_assignments`. Endpoints: import, list, content, assign, delete, campaigns/all. Contenido: JSON/drawio en texto, PDF/JPG en base64

**Data Burner — ciclo completo:**
- ✅ `_process_hopper` — detecta `dialable_leads=0` + sin NEW/PWORK → setea `list_complete=true`
- ✅ `/api/burner/weekly` — `answered` (AL) ahora viene de `vicidial_log` (leads AL son pusheados fuera de la lista, no se encontraban con query a `vicidial_list`)
- ✅ `/api/burner/weekly` — `dialable` cuenta todos los leads NOT IN (EXCLUD, AL, DNC, DNCC)
- ✅ `/api/burner/export` — incluye `source_id`, exporta 3 secciones con conteo, setea `csv_downloaded=true`
- ✅ `/api/burner/push` — setea `push_done=true` al completar
- ✅ `GET /api/burner/cycle-status` — expone los 3 flags al frontend
- ✅ `POST /api/burner/reset` — verifica 3 flags, bloquea con mensaje si falta alguno, DELETE leads, limpia todos los flags
- ✅ `DataBurner.tsx` — CyclePill pills visuales (✓ verde / ○ gris), botón Reset Cycle (naranja si todo listo), polling cycle-status cada 15s
- ✅ `DataBurner.tsx` — START/STOP visibles para TODOS los tenants (antes solo isMaster)
- ✅ `DataBurner.tsx` — botón "↺ Reset View" solo para superadmin: pone a 0 KPIs y stats visualmente, sin API, polling restaura automáticamente

### COMPLETADO en sesión V23 (10 Abril 2026)
- ✅ Statuses PWORK + EXCLUD — reemplazan NA/AB/DROP/PDROP/AA en todos los endpoints del Burner
- ✅ SSH toggle START/STOP — `AST_VDauto_dial.pl` arrancado/parado desde `routes_burner.py` via SSH
- ✅ `available_only_ratio_tally=N` en IBFEO — motor independiente de agentes humanos
- ✅ `AL` removido de `dial_statuses` + protegido con `called_since_last_reset='Y'`
- ✅ Push to Campaign — 2 dropdowns (Campaña + Lista) para todos los roles
- ✅ `/api/burner/lists` — nuevo endpoint sin restricción de tenant
- ✅ `/api/burner/push` — recibe `{tenant_id, dest_list_id}` directo
- ✅ Billing de minutos — solo visible para `isMaster`
- ✅ Tenant Manager wizard — listas multi-select (checkboxes) por campaña
- ✅ TenantManager usa `/api/burner/lists` en vez de `/api/vici/lists`
- ✅ draw.io parser — `_split_hint()` wired en construcción de nodos
- ✅ `sample_scripts/rei_script.json` — script REI completo con variables y hints
- ✅ NGROK quitado de BRICK.ps1 — popup de instrucciones al iniciar
- ✅ `vite.config.ts` — `server.allowedHosts: 'all'` para compatibilidad con ngrok

### COMPLETADO en sesión V21 (6 Abril 2026)
- ✅ Hangup button (`handleHangup` + `agentHungUp.current` flag)
- ✅ Customer hung up detection (polling INCALL→non-INCALL)
- ✅ Dispo saves to ViciDial — verificado e2e en llamada real
- ✅ Disposiciones AMD, PS, INFLU — en UI + STATUS_MAP (`PS` agregado a `logic_classification.py`)
- ✅ Auto-return to waiting after dispo (`_autoResume()`)
- ✅ Logout button (`handleLogout`)
- ✅ Back button + tab close protection (`popstate` + `beforeunload` con `keepalive:true`)
- ✅ Script Flow Editor — reescrito estilo Lucidchart (palette + canvas + properties panel)
- ✅ bcrypt 5.x → pinado a 4.0.1 (rompe passlib si se actualiza)

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
| F24 | bcrypt 5.x rompe passlib | passlib requiere bcrypt==4.0.1 exacto. pip install -r requirements.txt puede upgradear a 5.x. Siempre verificar con `pip show bcrypt` |
| F25 | agentHungUp.current debe setearse ANTES del fetch | Si se setea después, el polling puede disparar "customer hung up" en la ventana de ~1s entre hangup y respuesta del backend |
| F26 | `keepalive:true` en fetch para logout al cerrar tab | El componente se desmonta antes de que fetch complete. Sin keepalive, el logout no llega al backend |
| F27 | `campaign_id` no existe en `vicidial_list` | La campaña se asigna via `list_id`. UPDATE en vicidial_list nunca incluye `campaign_id` en SET |
| F28 | `/api/vici/lists` filtra por tenant_id del JWT | El superadmin no tiene tenant_id → devuelve vacío. Usar `/api/burner/lists` para acceso sin restricción |
| F29 | `eslint-disable` no suprime errores de TypeScript | Para variables no usadas en TS usar prefijo `_` (ej: `_previewing`) |
| F30 | Vite dev server bloquea hosts externos | Agregar `server: { allowedHosts: 'all' }` en `vite.config.ts` para ngrok |
| F31 | `git pull` falla si vicidial.db está bloqueado | Matar python ANTES de hacer git pull en ASUS |
| F32 | PWORK/EXCLUD son statuses custom de BRICK | No son nativos de ViciDial — se deben configurar en el dialer manualmente |

---

## REFERENCIA HISTÓRICA
- V1–V10: Arquitectura base, Agent UI, disposiciones
- V11–V15: Skip Trace, Export, CRM Pipeline
- V16–V17: Data Burner v1, Multi-tenant base
- V18.1.2: Data Burner completo, burner_tenants, Billing, Push V19
- **V19**: Refactor tenants (burner_tenants→tenants), manual_stop, BRICK rebranding, BRICK-watchdog.ps1
- **V20**: Tenant Manager V2 (Sync + Scripts + Users), Auth /api/admin/* cross-tenant, SSH Mac fix, sin referencias al dialer en UI
- **V21 (6 Abril 2026)**: Call cycle completo (hangup, customer hung up, dispo, auto-resume, logout, back button), disposiciones AMD/PS/INFLU, Script Flow Editor reescrito estilo Lucidchart, bcrypt pinado a 4.0.1
- **V22 (6 Abril 2026)**: Weekly Auto-Sync — APScheduler (thu/fri/sat/sun 8:05pm EST), round-robin sync_day al crear tenant, campaign_list_map en vicidial_configs, wizard de sync extendido a 4 pasos (campañas→listas→info→confirmar), GDrive+email pendientes de credenciales
- **V23 (10 Abril 2026)**: Statuses PWORK/EXCLUD en todos los endpoints Burner, SSH toggle AST_VDauto_dial, available_only_ratio_tally=N, Push to Campaign 2 dropdowns + multi-select listas, /api/burner/lists sin restricción tenant, billing solo isMaster, draw.io parser _split_hint wired, rei_script.json, NGROK manual + popup BRICK.ps1, vite allowedHosts
- **V24 (24 Abril 2026)**: Co-Pilot module — pre-dialer inteligente que mueve AL leads a lista destino cada 30s via APScheduler. Push es INCONDICIONAL: cualquier campaña con `dest_list_id` configurado en `copilot_config` recibe el push sin importar `copilot_active` ni estado del Remote Agent. Scheduler registrado en `scheduler.py::start_scheduler()` usando el mismo `BackgroundScheduler` que el weekly sync. Jobs: `copilot_push` (interval 30s) + `copilot_reset` (midnight EST). UI: tenant selector (master ve todos), KPIs de hoy, picker de lista destino, botones START/STOP para remote agent.
