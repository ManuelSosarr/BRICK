# BRICK — CLAUDE.md
## Última actualización: 4 de Abril, 2026 | Referencia: BRICK_Handover_Enhanced_V17.docx

---

## ARQUITECTURA
- Backend BRICK (8000): `C:\Users\sosai\BRICK\app\` — SQL, skiptrace, export, Data Burner
- Backend Auth (8001): `C:\Users\sosai\BRICK-auth\backend\` — agente, JWT, sesiones
- Frontend (5173): `C:\Users\sosai\BRICK-frontend\src\`
- DB SQLite: `C:\Users\sosai\BRICK\vicidial.db` — ruta ABSOLUTA, no relativa
- MySQL ViciDial: túnel SSH 127.0.0.1:3307 → usuario cron, password 1234, DB asterisk
- Túnel SSH: siempre en ASUS, nunca en Mac. Llave: `C:\Users\sosai\.ssh\vicidial_key`

## REGLAS DE ORO
1. TODO cambio de lógica de agente va en `dialflow/backend/routers/agent.py` (8001)
2. NUNCA DELETE/UPDATE masivo en Lista 806 sin backup previo con `backup_list_to_sqlite(806)`
3. Hangup usa agc/api.php como primario — MySQL directo deja al agente en estado DEAD
4. CORS: allow_credentials=False — True + wildcard es inválido por spec

## CREDENCIALES CRÍTICAS
- APIUSER pass: wscfjqwo3yr1092ruj123t
- MySQL ViciDial: cron / 1234 / asterisk
- ResImpli API Key: 2eea1a4bd7164b8888a5a2c97fd26560
- ViciDial server: root@144.126.146.250

## ESTADO ACTUAL — LO QUE FUNCIONA
- Resume, Pause (PAUSE!{epoch}), Hangup (agc/api.php + fallback MySQL)
- Lead data: nombre, teléfono, dirección, intentos, último contacto
- Agent name: 3 capas de fallback
- Customer hung up detection
- _autoResume() con check de llamada activa
- Back button protection + Logout
- Polling 1s con fire inmediato
- Disposiciones: SET NI DEADL AMD PS INFLU CB NA WN DNC
- CRM_DISPOS: solo SET y NI muestran Push to CRM
- CORS puerto 8000 corregido
- NaN handling en skiptrace parsers
- Data Burner: Remote Agent IBFEO activo, Start/Stop desde UI funcionando

## PENDIENTE CRÍTICO
1. Push to CRM vía Chrome Extension — reescrito, no probado en llamada real
2. County Link — endpoint existe, verificar con datos reales en PropertyMaster

## DATA BURNER — IBFEO
- Remote Agent: user_start=9999, campaign_id=IBFEO
- Horario: 7am-8pm EST — auto-stop fuera de horario
- Primer START: siempre manual desde UI
- Auto-reset hopper cuando dialable_leads=0 — solo NA/AB con menos de 5 intentos en 7 días
- Freno duro: día 7 desde primer START
- 3 buckets output: ANSWERED (AL) / POSSIBLE WORKING (NA/AB<5) / EXCLUDED (DROP/PDROP/AA/DNCL)
- Push to Campaign: AL + POSSIBLE WORKING como NEW, EXCLUDED nunca se empuja
- Download CSV: un archivo con los 3 buckets separados

## DATA BURNER — PENDIENTE DE IMPLEMENTAR
1. UI acumulado semanal: Total / Dialed / Dialable / Excluded / Answered
2. Auto-reset hopper en background thread
3. Auto-stop 8pm / Auto-start 7am EST scheduler
4. Freno duro día 7
5. Push to Campaign con dropdown
6. Download CSV 3 buckets

## LECCIONES APRENDIDAS CRÍTICAS
- agent_status pipe: parts[1]=uniqueid (V...), parts[2]=lead_id real — NUNCA usar parts[1]
- ViciDial columnas: address1 (no address), postal_code (no zip_code)
- SQLite ruta relativa = riesgo — migración puede aplicarse al archivo equivocado
- Chrome Extension: content.js=isolated world, Angular=main world — usar executeScript world:MAIN
- agc/api.php: si falta cualquier parámetro → ERROR: Invalid Username/Password
- Túnel SSH siempre en ASUS — si corre en Mac, el backend en ASUS no lo alcanza

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

## REFERENCIA COMPLETA
BRICK_Handover_Enhanced_V17.docx — arquitectura completa, credenciales, lecciones aprendidas
