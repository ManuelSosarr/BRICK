# BRICK Watchdog — Reinicia ambos backends si cualquiera cae
# Se ejecuta desde BRICK.ps1 al inicio del sistema

while ($true) {
    $p8000 = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
    $p8001 = Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue

    if (-not $p8000 -or -not $p8001) {
        Write-Host "[BRICK Watchdog] Servicio caido detectado. Reiniciando ambos backends..." -ForegroundColor Red
        Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
        Start-Sleep -Seconds 3
        Start-Process powershell -ArgumentList '-NoExit','-Command','cd C:\Users\sosai\BRICK; uvicorn app.main:app --port 8000'
        Start-Process powershell -ArgumentList '-NoExit','-Command','cd C:\Users\sosai\BRICK-auth\backend; python main.py'
        Write-Host "[BRICK Watchdog] Backends reiniciados." -ForegroundColor Green
    }

    Start-Sleep -Seconds 30
}
