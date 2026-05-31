# setup.ps1 - install the Python runtime dependencies for the HUD backend.
# psutil is required; nvidia-ml-py enables the in-process NVML GPU path
# (otherwise the backend falls back to spawning nvidia-smi).
$ErrorActionPreference = "Stop"
Write-Host "Installing Python dependencies (psutil, nvidia-ml-py)..." -ForegroundColor Cyan
python -m pip install --user --upgrade psutil nvidia-ml-py
Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "  Preview in a browser : .\run-dev.ps1"
Write-Host "  Run as wallpaper      : .\run-wallpaper.ps1   (builds the .NET host on first run)"
