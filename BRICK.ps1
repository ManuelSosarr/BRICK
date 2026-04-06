# Stop existing services
Write-Host "Stopping existing services..." -ForegroundColor Yellow
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
Get-Process node   -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2
# Docker
Start-Process powershell -ArgumentList '-NoExit', '-Command', 'cd C:\Users\sosai\BRICK-auth; docker compose up -d'
Start-Sleep -Seconds 5
# Backend BRICK-auth (port 8001) - pull + deps + start
Start-Process powershell -ArgumentList '-NoExit', '-Command', 'cd C:\Users\sosai\BRICK-auth; git fetch origin main; git reset --hard origin/main; cd backend; pip install -r requirements.txt -q; python main.py'
Start-Sleep -Seconds 3
# Backend BRICK (port 8000) - pull + deps + start
Start-Process powershell -ArgumentList '-NoExit', '-Command', 'cd C:\Users\sosai\BRICK; git fetch origin; git reset --hard origin/main; pip install -r requirements.txt -q; uvicorn app.main:app --port 8000'
# Frontend - pull + start
Start-Process powershell -ArgumentList '-NoExit', '-Command', 'cd C:\Users\sosai\BRICK-frontend; git fetch origin main; git reset --hard origin/main; npm run dev -- --host 0.0.0.0 --port 5173'
# SSH Tunnel
Start-Sleep -Seconds 5
Start-Process powershell -ArgumentList '-NoExit', '-Command', 'ssh -f -N -L 3307:127.0.0.1:3306 root@144.126.146.250 -p 22 -i "C:\Users\sosai\.ssh\vicidial_key" -o StrictHostKeyChecking=no -o ServerAliveInterval=60'
Start-Sleep -Seconds 3
# NGROK — expone frontend al exterior
Start-Process powershell -ArgumentList '-NoExit', '-Command', 'ngrok http 5173 --log=stdout'
# Watchdog — reinicia backends si alguno cae
Start-Process powershell -ArgumentList '-NoExit', '-Command', 'C:\Users\sosai\BRICK\BRICK-watchdog.ps1'
Start-Sleep -Seconds 2
Start-Process "http://localhost:5173"
