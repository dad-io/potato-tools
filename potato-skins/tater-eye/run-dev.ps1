# run-dev.ps1 - fast UI/algorithm iteration WITHOUT the wallpaper layer.
# Starts the Python backend in a visible console and opens the HUD in your
# default browser. This is the easy way to see the dashboard while tuning.
$ErrorActionPreference = "Stop"
$server = Join-Path $PSScriptRoot "server"
Write-Host "Starting HUD backend (Ctrl-C to stop)..." -ForegroundColor Cyan
Start-Process "http://127.0.0.1:8765"
python (Join-Path $server "server.py")
