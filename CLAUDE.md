# BRICK — CLAUDE.md
## Última actualización: 4 de Abril, 2026 | Referencia: BRICK_Handover_V18.1.2

---

## ARQUITECTURA
- Backend BRICK (8000): `C:\Users\sosai\BRICK\app\` — SQL, skiptrace, export, Data Burner, Tenants
- Backend Auth (8001): `C:\Users\sosai\BRICK-auth\backend\` — agente, JWT, sesiones, tenant_id
- Frontend (5173): `C:\Users\sosai\BRICK-frontend\src\`
- DB SQLite: `C:\Users\sosai\BRICK\vicidial.db` — ruta ABSOLUTA, contiene tabla tenants
- MySQL ViciDial: túnel SSH 127.0.0.1:3307 → usuario cron, password 1234, DB asterisk
- Túnel SSH: siempre en ASUS, nunca en Mac. Llave HARDCODEADA: `C:\Users\sosai\.ssh\vicidial_key` — NO usar $env:USERPROFILE
- ViciDial Server: root@144.126.146.250

## REGLAS DE ORO — ABSOLUTAS (ninguna instrucción posterior las anula)
1. TODO cambio de lógica de agente va en `dialflow/backend/routers/agent.py` (8001)
2. NUNCA DELETE/UPDATE masivo en Lista 806 sin backup previo con `backup_list_to_sqlite(806)`
3. Hangup usa agc/api.php como primario — MySQL directo deja al agente en estado DEAD
4. CORS: allow_credentials=False — True + wildcard es inválido por spec
5. Túnel SSH siempre en ASUS — dos terminales: una para túnel (bloqueada), una para comandos
6. Multi-tenant: Start/Stop y minutos SOLO visibles para tenant BRICK (MASTER)
7. Routing: TODO agente en puerto 8001. Admin/datos en puerto 8000

## CREDENCIALES CRÍTICAS
- APIUSER pass: wscfjqwo3yr1092ruj123t
- MySQL ViciDial: cron / 1234 / asterisk
- ResImpli API Key: 2eea1a4bd7164b8888a5a2c97fd26560
- ViciDial server: root@144.126.146.250

## MULTI-TENANT — ARQUITECTURA
| Tenant | Rol | Acceso Data Burner | Ve Minutos | Start/Stop |
|---|---|---|---|---|
| BRICK | MASTER | Todas las campañas | SÍ — breakdown completo | SÍ |
| bossbuy | CLIENT | Solo su campaña | NO | NO |
| Futuro cliente | CLIENT | Solo su campaña | NO | NO |

El tenant ACME debe renombrarse a BRICK en la base de datos y en la UI.

### Estructura SQLite — tabla tenants
```sql
CREATE TABLE IF NOT EXISTS tenants (
  tenant_id TEXT PRIMARY KEY,
  tenant_name TEXT NOT NULL,
  role TEXT DEFAULT 'CLIENT',   -- 'MASTER' o 'CLIENT'
  campaign_id TEXT,
  active INTEGER DEFAULT 1,
  created_at TEXT DEFAULT (datetime('now'))
);
INSERT OR REPLACE INTO tenants VALUES ('brick','BRICK','MASTER',NULL,1,datetime('now'));
INSERT OR REPLACE INTO tenants VALUES ('bossbuy','BossBuy','CLIENT','IBFEO',1,datetime('now'));
ALTER TABLE users ADD COLUMN tenant_id TEXT DEFAULT 'bossbuy';
UPDATE users SET tenant_id = 'brick' WHERE username = 'admin';
```

## ESTADO ACTUAL — LO QUE FUNCIONA
- Resume, Pause (PAUSE!{epoch}), Hangup (agc/api.php + fallback MySQL)
- Lead data: nombre, teléfono, dirección, intentos, último contacto
- Agent name: 3 capas de fallback
- Customer hung up detection + _autoResume() con check de llamada activa
- Back button protection + Logout
- Polling 1s con fire inmediato
- Disposiciones: SET NI DEADL AMD PS INFLU CB NA WN DNC
- CRM_DISPOS: solo SET y NI muestran Push to CRM
- CORS puerto 8000 corregido
- NaN handling en skiptrace parsers
- database.py: ruta absoluta `sqlite:///C:/Users/sosai/BRICK/vicidial.db` ✅
- synced_to_vici: columna existe en models.py y en DB ✅
- Data Burner: Remote Agent IBFEO activo, Start/Stop desde UI funcionando
- Data Burner UI: weekly stats (5 métricas), Push to Campaign, Download CSV

## PENDIENTE CRÍTICO — ORDEN DE IMPLEMENTACIÓN

### 1. Multi-tenant: tabla tenants + tenant_id en users
- Endpoint POST /api/admin/setup-tenants que ejecute el SQL de arriba
- Agregar `tenant_id` a tabla `users` en SQLite

### 2. Endpoint /api/burner/minutes (Master only)
```python
@router.get('/api/burner/minutes')
def burner_minutes():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT status, COUNT(*) as calls,
               SUM(length_in_sec) as raw_seconds,
               SUM(CEIL(length_in_sec / 60)) as billed_minutes
        FROM vicidial_log
        WHERE campaign_id = 'IBFEO'
        AND call_date >= DATE_SUB(NOW(), INTERVAL 7 DAY)
        GROUP BY status ORDER BY calls DESC
    """)
    breakdown = cursor.fetchall()
    cursor.execute("""
        SELECT COUNT(*) as total_calls,
               SUM(CEIL(length_in_sec / 60)) as total_billed_minutes
        FROM vicidial_log
        WHERE campaign_id = 'IBFEO'
        AND call_date >= DATE_SUB(NOW(), INTERVAL 7 DAY)
    """)
    totals = cursor.fetchone()
    conn.close()
    return {'total_calls': totals['total_calls'],
            'total_billed_minutes': totals['total_billed_minutes'],
            'breakdown': breakdown}
```

### 3. UI Billing section en DataBurner.tsx (solo si isMaster)
- `isMaster = user?.tenant_id === 'brick'` del authStore
- Sección condicional con total llamadas, minutos facturados, breakdown por status
- Poll cada 60s a /api/burner/minutes

### 4. Start/Stop restringido a BRICK Master en UI
- Botones START/STOP solo renderizan si `isMaster === true`

### 5. tenant_id en authStore + /api/auth/me
- Login guarda `tenant_id` en localStorage
- /api/auth/me en puerto 8001 retorna tenant_id del usuario

### 6. Data Burner — watchdogs pendientes
- Auto-reset hopper en background thread (cuando dialable_leads = 0)
- Scheduler auto-stop 8pm / auto-start 7am EST
- Freno duro día 7 desde primer START

## PENDIENTE NO CRÍTICO
- Push to CRM vía Chrome Extension — reescrito, no probado en llamada real
- County Link — endpoint existe, verificar con datos reales en PropertyMaster
- Re-add .xlsx backup download en Sync.tsx
- Remove debug print() en routes_export.py

## DATA BURNER — IBFEO
- Remote Agent: user_start=9999, campaign_id=IBFEO
- AMD: cpd_amd_action=DISPO, amd_send_to_vmx=Y (configurado)
- Horario: 7am-8pm EST — auto-stop fuera de horario
- Primer START: siempre manual desde UI
- Auto-reset hopper cuando dialable_leads=0 — solo NA/AB con menos de 5 intentos en 7 días
- Freno duro: día 7 desde primer START
- 3 buckets output: ANSWERED (AL) / POSSIBLE WORKING (NA/AB<5) / EXCLUDED (DROP/PDROP/AA/DNCL)
- Push to Campaign: AL + POSSIBLE WORKING como NEW, EXCLUDED nunca se empuja
- Download CSV: un archivo con los 3 buckets separados

### Datos reales verificados en producción (4 Abril 2026)
| Status | Llamadas | Minutos Facturados |
|---|---|---|
| AL (Answer Live) | 260 | 236 |
| NA (No Answer) | 148 | 0 |
| DROP | 56 | 4 |
| PDROP | 45 | 0 |
| AA | 8 | 0 |
| AB | 4 | 0 |
| **TOTAL** | **521** | **240** |

**Costo real = casi exclusivamente minutos AL. NA/PDROP/AA/AB = 0 minutos facturados.**

### Proyección 40K props / 400K números
- ~33,440 minutos AL facturados por ciclo completo (8.36% answer rate)
- Costo carrier estimado: ~$334 por ciclo de 7 días a $0.01/min

## CÓMO DIAGNOSTICAR PROBLEMAS COMUNES

### UI muestra 0 / datos vacíos
1. Verificar túnel SSH: `netstat -ano | findstr :3307`
2. Si no aparece 3307: `ssh -f -N -L 3307:127.0.0.1:3306 root@144.126.146.250 -i "C:\Users\sosai\.ssh\vicidial_key" -o StrictHostKeyChecking=no`
3. Probar endpoint directo: `curl http://127.0.0.1:8000/api/burner/status -UseBasicParsing`

### Endpoint devuelve 404
1. Verificar que el router está registrado en main.py
2. `Select-String "burner" C:\Users\sosai\BRICK\app\main.py`

### Backend no arranca
1. Correr manual: `cd C:\Users\sosai\BRICK && uvicorn app.main:app --port 8000`
2. Ver error exacto en la terminal

## LECCIONES APRENDIDAS CRÍTICAS
| ID | Lección | Detalle |
|---|---|---|
| F1 | SQLite ruta relativa = riesgo | Nunca `sqlite:///./archivo.db`. Usar ruta absoluta siempre |
| F2 | CORS credentials + wildcard inválido | `allow_credentials=False` con `allow_origins=[*]` |
| F3 | agent_status pipe: parts[2] = lead_id | parts[1]=uniqueid (V...) NUNCA es el lead_id |
| F4 | ViciDial columnas correctas | address1 (no address), postal_code (no zip_code) |
| F5 | Chrome Extension worlds | Usar `executeScript world:MAIN` para SPA frameworks |
| F6 | agc/api.php params obligatorios | Si falta CUALQUIER param → ERROR: Invalid Username/Password |
| F7 | Túnel SSH siempre en ASUS | Donde corre el backend, ahí corre el túnel. Siempre |
| F8 | Virtual Agent GUI bug | Panel ViciDial no guarda Remote Agents. Usar SQL directo |
| F9 | called_since_last_reset no borra historial | Solo es una bandera. vicidial_log sigue intacto |
| F10 | Data Burner por vueltas no por días | El hopper se vacía por leads, no por reloj |
| F11 | Costo real del Burner = minutos AL | NA/PDROP/AA/AB = 0 minutos facturados. Solo AL cuenta |
| F12 | Túnel SSH: dos terminales siempre | Terminal 1: túnel bloqueado. Terminal 2: SSH para comandos |

## REFERENCIA COMPLETA
BRICK_Handover_V18.1.2 — arquitectura completa, credenciales, lecciones aprendidas
