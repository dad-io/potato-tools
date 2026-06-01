# run-wallpaper.ps1 - build (if needed) and launch the live wallpaper.
# The host process starts the Python backend itself and parents a native GDI+
# surface behind the desktop icons. Use stop.ps1 to tear it down.
$ErrorActionPreference = "Stop"
$host_dir = Join-Path $PSScriptRoot "host"
$exe = Join-Path $host_dir "bin\Release\net9.0-windows\win-x64\HudWallpaper.exe"

if (-not (Test-Path $exe)) {
    Write-Host "Building host..." -ForegroundColor Cyan
    dotnet build (Join-Path $host_dir "WallpaperHost.csproj") -c Release | Out-Null
}
Write-Host "Launching HudWallpaper..." -ForegroundColor Green
Start-Process $exe
Write-Host "Log: $env:TEMP\hudwallpaper.log"
