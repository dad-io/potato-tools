# stop.ps1 - tear down the wallpaper host and its Python backend.
Get-Process HudWallpaper -ErrorAction SilentlyContinue | Stop-Process -Force

# The real interpreter is pythonw3.12.exe (the Store python alias trampolines to
# it), so a Name='pythonw.exe' filter misses it. Use the PID the server recorded,
# then sweep any python process whose command line still runs our server.py.
$pidFile = Join-Path $env:TEMP "hudwallpaper.server.pid"
if (Test-Path $pidFile) {
    $serverPid = (Get-Content $pidFile -ErrorAction SilentlyContinue).Trim()
    if ($serverPid) { Stop-Process -Id ([int]$serverPid) -Force -ErrorAction SilentlyContinue }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}
Get-CimInstance Win32_Process -Filter "Name LIKE 'python%'" |
    Where-Object { $_.CommandLine -match "server\.py" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Write-Host "HUD wallpaper stopped." -ForegroundColor Yellow
