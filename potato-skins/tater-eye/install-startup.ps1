# install-startup.ps1 - run the HUD wallpaper automatically at logon.
# Creates a shortcut in the user's Startup folder (no admin required).
$ErrorActionPreference = "Stop"
$exe = Join-Path $PSScriptRoot "host\bin\Release\net9.0-windows\win-x64\HudWallpaper.exe"
if (-not (Test-Path $exe)) { throw "Build first: run run-wallpaper.ps1 once. Missing $exe" }

$startup = [Environment]::GetFolderPath("Startup")
$lnk = Join-Path $startup "HudWallpaper.lnk"
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut($lnk)
$sc.TargetPath = $exe
$sc.WorkingDirectory = Split-Path $exe
$sc.WindowStyle = 7
$sc.Description = "Live system/LLM HUD wallpaper"
$sc.Save()
Write-Host "Installed startup shortcut: $lnk" -ForegroundColor Green
Write-Host "Remove with: Remove-Item '$lnk'"
