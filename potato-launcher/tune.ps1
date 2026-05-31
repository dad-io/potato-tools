<#
  tune.ps1 - Reversible PC tuning pass
  Actions: (1) fix pagefile  (2) disable Fast Startup
           (3) trim 5 autostarts  (4) Ultimate Performance plan + AppX bloat purge
  A full backup of prior state is written to .\backup-<timestamp>\ first.
  Run elevated (script self-checks).
#>

$ErrorActionPreference = 'Continue'
$root = $PSScriptRoot   # backups + transcript land next to this script
$bk   = Join-Path $root ("backup-" + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Force $bk | Out-Null
Start-Transcript -Path (Join-Path $root 'last-run.log') -Force | Out-Null

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "ERROR: not elevated. Aborting." -ForegroundColor Red
    Stop-Transcript | Out-Null; exit 1
}

Write-Host "=== BACKUP -> $bk ===" -ForegroundColor Cyan
reg export "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" "$bk\Run.reg" /y *>$null
reg export "HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run" "$bk\StartupApproved-Run.reg" /y *>$null
powercfg /list | Out-File "$bk\powerschemes.txt"
"HiberbootEnabled=" + (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power' HiberbootEnabled).HiberbootEnabled | Out-File "$bk\fast-startup.txt"
$cs0 = Get-CimInstance Win32_ComputerSystem
"AutomaticManagedPagefile=$($cs0.AutomaticManagedPagefile)" | Out-File "$bk\pagefile.txt"
Get-CimInstance Win32_PageFileSetting | Select-Object Name,InitialSize,MaximumSize | Out-File "$bk\pagefile.txt" -Append
Get-AppxPackage | Select-Object Name,PackageFullName | Out-File "$bk\appx-before.txt"
Write-Host "Backup complete.`n"

# ---- 1) PAGEFILE: fixed 8 GB initial / 32 GB max on C: (reboot to apply) ----
Write-Host "=== [1/4] PAGEFILE ===" -ForegroundColor Cyan
try {
    $cs = Get-WmiObject Win32_ComputerSystem
    if ($cs.AutomaticManagedPagefile) { $cs.AutomaticManagedPagefile = $false; [void]$cs.Put() }
    $pf = Get-WmiObject Win32_PageFileSetting -Filter "Name='C:\\pagefile.sys'"
    if ($pf) { $pf.InitialSize = 8192; $pf.MaximumSize = 32768; [void]$pf.Put() }
    else     { Set-WmiInstance -Class Win32_PageFileSetting -Arguments @{Name='C:\pagefile.sys'; InitialSize=8192; MaximumSize=32768} | Out-Null }
    Write-Host "  Pagefile set to 8192-32768 MB on C: (takes effect after reboot)." -ForegroundColor Green
} catch { Write-Host "  Pagefile FAILED: $_" -ForegroundColor Red }

# ---- 2) FAST STARTUP off ----
Write-Host "`n=== [2/4] FAST STARTUP ===" -ForegroundColor Cyan
try {
    Set-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power' HiberbootEnabled 0 -Type DWord
    Write-Host "  Fast Startup disabled (HiberbootEnabled=0)." -ForegroundColor Green
} catch { Write-Host "  Fast Startup FAILED: $_" -ForegroundColor Red }

# ---- 3) TRIM AUTOSTARTS (reversible: flips StartupApproved state byte to 0x03) ----
Write-Host "`n=== [3/4] AUTOSTARTS ===" -ForegroundColor Cyan
$sa = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run'
$disabled = [byte[]](3,0,0,0,0,0,0,0,0,0,0,0)
$targets = 'Steam','EpicGamesLauncher','EADM','Docker Desktop','electron.app.LM Studio'
foreach ($t in $targets) {
    try {
        Set-ItemProperty -Path $sa -Name $t -Value $disabled -Type Binary
        Write-Host "  Disabled: $t" -ForegroundColor Green
    } catch { Write-Host "  $t FAILED: $_" -ForegroundColor Red }
}

# ---- 4a) ULTIMATE PERFORMANCE plan ----
Write-Host "`n=== [4/4] ULTIMATE PERFORMANCE + BLOAT ===" -ForegroundColor Cyan
$up = powercfg /list | Select-String 'Ultimate Performance'
if (-not $up) { powercfg -duplicatescheme e9a42b02-d5df-448d-aa00-03f14749eb61 *>$null; $up = powercfg /list | Select-String 'Ultimate Performance' }
if ($up -match '([0-9a-fA-F]{8}-[0-9a-fA-F-]{27})') {
    powercfg /setactive $matches[1] *>$null
    Write-Host "  Ultimate Performance unlocked and ACTIVE ($($matches[1]))." -ForegroundColor Green
} else { Write-Host "  Could not resolve Ultimate Performance GUID." -ForegroundColor Red }

# ---- 4b) APPX BLOAT PURGE (per-user; Xbox left intact to preserve Game Mode) ----
$bloat = 'BingWeather','BingSearch','GetHelp','Getstarted','Microsoft3DViewer',
         'MicrosoftSolitaireCollection','MixedReality.Portal','People','SkypeApp',
         'WindowsFeedbackHub','YourPhone','ZuneMusic','ZuneVideo'
foreach ($b in $bloat) {
    $pkgs = Get-AppxPackage "*$b*"
    foreach ($p in $pkgs) {
        try { Remove-AppxPackage $p.PackageFullName -ErrorAction Stop; Write-Host "  Removed: $($p.Name)" -ForegroundColor Green }
        catch { Write-Host "  Skip $($p.Name): $_" -ForegroundColor DarkYellow }
    }
}

Write-Host "`n=== DONE. Backup at: $bk ===" -ForegroundColor Cyan
Write-Host "REBOOT REQUIRED for the pagefile + Fast Startup changes to take effect." -ForegroundColor Yellow
Stop-Transcript | Out-Null
