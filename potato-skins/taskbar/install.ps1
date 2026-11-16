# install.ps1 - TranslucentTB with a clear taskbar
$pfn = '28017CharlesMilette.TranslucentTB_v826wp6bftszj'
if (-not (Get-AppxPackage *TranslucentTB*)) {
    winget install --id CharlesMilette.TranslucentTB -e --silent --accept-package-agreements --accept-source-agreements
}
$dir = Join-Path $env:LOCALAPPDATA "Packages\$pfn\RoamingState"
New-Item -ItemType Directory -Force $dir | Out-Null
Copy-Item (Join-Path $PSScriptRoot 'settings.json') (Join-Path $dir 'settings.json') -Force
Get-Process TranslucentTB -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Process "shell:AppsFolder\$pfn!TranslucentTB"
Write-Host "TranslucentTB running with a clear taskbar."
