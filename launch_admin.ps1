# Pushkey Admin Console Launcher
$root = "C:\Users\aware\bots\pushkey"

# Kill any existing instances on these ports first
$ports = @(8000, 3000)
foreach ($port in $ports) {
    $pid = (Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue).OwningProcess | Select-Object -First 1
    if ($pid) { Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue }
}

# Start cloud API (minimized terminal)
Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "Set-Location '$root'; Write-Host 'Pushkey API starting...' -ForegroundColor Cyan; uvicorn pushkey_cloud_api:app --host 0.0.0.0 --port 8000"
) -WindowStyle Minimized

# Start Next.js dev server (minimized terminal)
Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "Set-Location '$root\web'; Write-Host 'Pushkey Admin UI starting...' -ForegroundColor Cyan; npm run dev"
) -WindowStyle Minimized

# Poll until Next.js is ready (max 60s)
$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 1
    try {
        $null = (New-Object System.Net.WebClient).DownloadString("http://localhost:3000/admin/login")
        $ready = $true
        break
    } catch { }
}

# Open admin console in default browser
Start-Process "http://localhost:3000/admin"
