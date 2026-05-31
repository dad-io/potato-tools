# stop.ps1 - tear down the wallpaper host and its Python backend.
Get-Process HudWallpaper -ErrorAction SilentlyContinue | Stop-Process -Force
# kill any python running our server.py (leaves other python alone)
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
    Where-Object { $_.CommandLine -match "server\.py" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Write-Host "HUD wallpaper stopped." -ForegroundColor Yellow
