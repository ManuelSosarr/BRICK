# BRICK Platform — Claude Code Instructions

## READ THIS ENTIRE FILE BEFORE TOUCHING ANYTHING

You are Claude Code working on the BRICK platform. Your role is **executor**, not decision-maker.
You write code, run commands, and verify results. You do NOT improvise, redesign, or make architectural decisions.

---

## STEP 1 — VERIFY STATE BEFORE EVERY SESSION

Run these commands first. Every single session. No exceptions.

**In ASUS PowerShell:**
```powershell
cd C:\Users\sosai\BRICK && git branch && git log --oneline -3
cd C:\Users\sosai\BRICK-auth && git branch && git log --oneline -3
cd C:\Users\sosai\BRICK-frontend && git branch && git status
```

**Verify critical patches exist:**
```powershell
findstr "wscfjqwo" C:\Users\sosai\BRICK-auth\backend\config.py
findstr "PAUSE!" C:\Users\sosai\BRICK-auth\backend\routers\agent.py
findstr "pymysql" C:\Users\sosai\BRICK\app\routes_agent.py
findstr "brickClient" C:\Users\sosai\BRICK-frontend\src\pages\Agent.tsx
```

Each command must return a result. If any returns nothing, DO NOT PROCEED. Report to Manuel immediately.

**Verify ViciDial API (open in browser on ASUS):**
```
http://144.126.146.250/vicidial/non_agent_api.php?source=test&user=APIUSER&pass=wscfjqwo3yr1092ruj123t&function=version
```
Expected: `VERSION: 2.14...` — If it returns `BAD`, the ASUS IP changed. Stop and report.

---

## STEP 2 — RULES YOU CANNOT BREAK

### Git Rules
- NEVER run `git reset --hard` without first running `git status` and confirming there are no unpushed local changes
- NEVER run `git merge`, `git rebase`, or `git checkout -b` without explicit approval from Manuel
- ALWAYS push to GitHub before telling Manuel you are done — unpushed code does not exist
- BRICK-auth ASUS local branch is `master`. To push to GitHub: `git push origin master:main`
- BRICK and BRICK-frontend use `main` branch

### Python/pip Rules
- NEVER run `pip install -r requirements.txt` — it breaks bcrypt and sqlalchemy
- If you must install a package, IMMEDIATELY after run: `pip install bcrypt==4.0.1`
- NEVER write Python inline with `-c` for multi-line scripts — use a `.py` file

### File Editing Rules (ASUS IBM850 encoding)
- NEVER use `Set-Content` with special characters like `!`, `{`, `}`, `$`, `@`
- ALWAYS write Python scripts using this pattern:
```powershell
Set-Content script.py -Encoding UTF8 -Value @'
# your python code here
'@
python script.py
```
- ALWAYS verify the patch was applied with `findstr` before committing
- If `findstr` returns nothing after applying a patch, the patch failed — try again

### Process Rules
- ALWAYS kill Python before restarting: `Get-Process python | Stop-Process -Force`
- ALWAYS delete `__pycache__` when a code change is not being picked up:
```powershell
Remove-Item -Recurse -Force C:\Users\sosai\BRICK-auth\backend\routers\__pycache__
```
- ALWAYS specify which terminal each command runs in: **ASUS PowerShell**, **Mac Terminal**, or **SSH Server (vmi2377273)**

### ViciDial Rules
- NEVER touch campaigns outside the IBF prefix
- NEVER modify server-wide ViciDial settings
- NEVER assume a ViciDial API function exists — verify in the PHP file first

---

## STEP 3 — ARCHITECTURE YOU MUST KNOW

### Two Backends — Both Must Be Kept in Sync
| Backend | Port | Agent File |
|---|---|---|
| BRICK | 8000 | `C:\Users\sosai\BRICK\app\routes_agent.py` |
| BRICK-auth | 8001 | `C:\Users\sosai\BRICK-auth\backend\routers\agent.py` |

When you fix a bug in agent control, fix it in BOTH files. They must be identical in logic.

### Frontend Client Routing
- `brickClient` (port 8000): Resume, Pause, Hangup, Dispo, Push-CRM, Logout buttons
- `client` (port 8001): Lead polling every 3 seconds (`/api/agent/lead/{user}`)

### ViciDial MySQL Direct — How Agent Control Works
The ViciDial API does NOT have pause_agent, hangup_lead, or save_dispo in this version (2.14-197).
We bypass the API and write directly to MySQL via SSH tunnel on port 3307.

| Action | SQL |
|---|---|
| Resume | `UPDATE vicidial_live_agents SET external_pause = 'RESUME' WHERE user = ?` |
| Pause | `UPDATE vicidial_live_agents SET external_pause = CONCAT('PAUSE!', UNIX_TIMESTAMP()) WHERE user = ?` |
| Hangup | `UPDATE vicidial_live_agents SET external_hangup = 'Y' WHERE user = ?` |
| Dispo | `UPDATE vicidial_live_agents SET external_status = ? WHERE user = ?` |

**CRITICAL: PAUSE requires the epoch timestamp format `PAUSE!{unix_timestamp}`. Plain `PAUSE` is ignored by ViciDial.**

### ViciDial Credentials
- API URL: `http://144.126.146.250/vicidial/non_agent_api.php`
- API User: `APIUSER`
- API Pass: `wscfjqwo3yr1092ruj123t`
- MySQL tunnel: `host=127.0.0.1, port=3307, user=cron, pass=1234, db=asterisk`

### agent_status Response Format
```
STATUS|lead_id|sub_status|campaign|user_level|full_name|group|calls_today|phone|address|...
```
Only return lead data to frontend when `STATUS == 'INCALL'`. All other statuses return `{"lead": null}`.

---

## STEP 4 — CURRENT PENDING WORK (in order of priority)

1. **Hangup button** — `UPDATE external_hangup='Y'`, reset to `''` after 2s. Open dispo panel after.
2. **Customer hung up detection** — When polling detects status changed from INCALL to non-INCALL without agent clicking Hangup, show alert: "Customer hung up — Please set disposition"
3. **Dispo saves to ViciDial** — `external_status` UPDATE already in code. Verify end-to-end during real call.
4. **Add missing dispositions** — Add to `DISPOSITIONS` in `Agent.tsx`: AMD (Answer Machine), PS (Phone Screener), INFLU (Influencer). Add to `STATUS_MAP` in `logic_classification.py`.
5. **Push to CRM (Zapier → ResImpli)** — POST to `ZAPIER_WEBHOOK_URL` in `config.py`. URL not configured yet.
6. **Auto-return to waiting after dispo** — After saving dispo, automatically call Resume.
7. **Logout from both BRICK and ViciDial** — `handleLogout` must call `agent_logout` API then clear localStorage. Remove Quit button.
8. **Back button protection** — Auto-logout if agent presses back while logged in.
9. **Push BRICK-frontend patches** — Verify brickClient patches are pushed to GitHub.
10. **Remove debug print()** — Remove from `routes_export.py`.
11. **Re-add .xlsx backup download** — Add as separate button in `Sync.tsx`.

---

## STEP 5 — HOW TO DIAGNOSE COMMON PROBLEMS

### Button does nothing in UI
1. Check browser console for errors
2. Check if `viciUser` is empty: add `console.log('viciUser:', viciUser)` temporarily
3. Check if button `disabled` condition matches current status
4. Check backend log for the POST request

### POST arrives at backend but DB does not change
1. Add `print(f">>> HIT {payload.vici_user}")` inside the function
2. If print does not appear: delete `__pycache__` and restart backend
3. If print appears but DB unchanged: check the SQL value format, check MySQL tunnel is active on port 3307

### ViciDial ignores MySQL write
1. Verify field value format (PAUSE requires `PAUSE!{epoch}`)
2. Verify agent is in correct status for that operation
3. Check on ViciDial server: `mysql -u root asterisk -e "SELECT user, status, external_pause, external_hangup FROM vicidial_live_agents WHERE user='3020';"`

### Git does not detect file change
1. Run `git diff filename` — if nothing, git sees the content as identical to last commit
2. Force-write the file with a Python script that opens, modifies, and saves it
3. Run `git diff filename` again — if still nothing, the byte content is identical to what GitHub has

### SSH tunnel fails from ASUS
1. Open in ASUS browser: `http://144.126.146.250/vicidial/non_agent_api.php?source=test&user=APIUSER&pass=wscfjqwo3yr1092ruj123t&function=version`
2. If returns `BAD`: ASUS IP changed — update iptables on ViciDial server from Mac
3. On ViciDial server: `iptables -I INPUT -s NEW_IP -j ACCEPT -m comment --comment "ASUS Manuel"`

---

## REFERENCE — Full documentation in BRICK_Handover_v16.docx
For complete architecture, credentials, lessons learned, and roadmap — read the handover document.
