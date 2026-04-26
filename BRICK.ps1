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
Start-Process powershell -ArgumentList '-NoExit', '-Command', 'cd C:\Users\sosai\BRICK-frontend; git fetch origin main; git reset --hard origin/main; npm install --silent; npm run dev -- --host 0.0.0.0 --port 5173'
# SSH Tunnel
Start-Sleep -Seconds 5
Start-Process powershell -ArgumentList '-NoExit', '-Command', 'ssh -f -N -L 3307:127.0.0.1:3306 root@144.126.146.250 -p 22 -i "C:\Users\sosai\.ssh\vicidial_key" -o StrictHostKeyChecking=no -o ServerAliveInterval=60'
Start-Sleep -Seconds 3
# NGROK — expone frontend al exterior (puerto 5173 = Vite dev server)
$ngrokProcess = Get-Process ngrok -ErrorAction SilentlyContinue
if (-not $ngrokProcess) {
    Start-Process "ngrok" -ArgumentList "http 5173" -NoNewWindow
    Start-Sleep -Seconds 3
}
try {
    $tunnels   = Invoke-RestMethod -Uri "http://localhost:4040/api/tunnels" -TimeoutSec 5
    $publicUrl = $tunnels.tunnels | Where-Object { $_.proto -eq "https" } | Select-Object -ExpandProperty public_url
    if ($publicUrl) {
        Write-Host "BRICK Remote URL: $publicUrl" -ForegroundColor Green
        $publicUrl | Out-File -FilePath "C:\Users\sosai\brick_ngrok_url.txt" -Encoding utf8
    }
} catch {
    Write-Host "NGROK: no se pudo obtener URL — verificar manualmente en localhost:4040" -ForegroundColor Yellow
}
# Watchdog — reinicia backends si alguno cae
Start-Process powershell -ArgumentList '-NoExit', '-Command', 'C:\Users\sosai\BRICK\BRICK-watchdog.ps1'
Start-Sleep -Seconds 2
Start-Process "http://localhost:5173"
