<#
.SYNOPSIS
    Potato Audit - reusable, native, version-proof Windows hardware + OS auditor.

.DESCRIPTION
    Re-runnable snapshot of this machine's hardware and OS configuration, with
    severity-coded findings and recommendations. Read-only by default.

    Design goals (why this is built the way it is):
      * Pure Windows PowerShell 5.1 - present in-box on every Win10/11/Server since 2016.
      * Uses Get-CimInstance only (no Get-WmiObject) so it ALSO runs on PowerShell 7.
      * Every probe is guarded; a missing module/cmdlet degrades gracefully, never fatal.
      * No external modules, no installs, no internet required.

    Outputs (all optional except console):
      * Console report (always)
      * HTML report  -> reports\audit-<timestamp>.html   (open in any browser)
      * JSON snapshot-> reports\audit-<timestamp>.json   (diff the box over time)

.PARAMETER Fix
    Self-elevates and runs the reversible tuning pass (..\potato-launcher\tune.ps1).

.PARAMETER NoHtml
    Skip the HTML report.

.PARAMETER NoJson
    Skip the JSON snapshot.

.PARAMETER Quiet
    Do not auto-open the HTML report.

.PARAMETER OutDir
    Where reports are written. Default: .\reports

.EXAMPLE
    .\Potato-Audit.ps1
        Full read-only audit, writes + opens an HTML report and a JSON snapshot.

.EXAMPLE
    .\Potato-Audit.ps1 -NoHtml -NoJson
        Console only.

.EXAMPLE
    .\Potato-Audit.ps1 -Fix
        Apply the reversible tuning pass (elevates).
#>
[CmdletBinding()]
param(
    [switch]$Fix,
    [switch]$NoHtml,
    [switch]$NoJson,
    [switch]$Quiet,
    [string]$OutDir
)

$ErrorActionPreference = 'Continue'
if (-not $OutDir) { $OutDir = Join-Path $PSScriptRoot 'reports' }

# --------------------------------------------------------------------------
#  -Fix : delegate to the proven reversible tuning script, elevated.
# --------------------------------------------------------------------------
if ($Fix) {
    $tune = Join-Path $PSScriptRoot '..\potato-launcher\tune.ps1'
    if (-not (Test-Path $tune)) { $tune = Join-Path $PSScriptRoot 'tune.ps1' }   # fallback if co-located
    if (-not (Test-Path $tune)) { Write-Host "tune.ps1 not found (looked in ..\potato-launcher\ and beside this script)." -ForegroundColor Red; return }
    Write-Host "Launching reversible tuning pass (UAC prompt incoming)..." -ForegroundColor Cyan
    Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File',"`"$tune`""
    return
}

# --------------------------------------------------------------------------
#  Collectors write into these. Sections = ordered map of name -> rows.
# --------------------------------------------------------------------------
$script:Sections = [ordered]@{}
$script:Findings = New-Object System.Collections.ArrayList

function Add-Section {
    param([string]$Name, $Rows)
    $script:Sections[$Name] = @($Rows)
}

function Add-Finding {
    param(
        [ValidateSet('CRIT','WARN','INFO','OK')] [string]$Level,
        [string]$Area,
        [string]$Message,
        [string]$Fix = ''
    )
    [void]$script:Findings.Add([pscustomobject]@{
        Level = $Level; Area = $Area; Message = $Message; Recommendation = $Fix
    })
}

function Try-Cim {
    param([scriptblock]$Block)
    try { & $Block } catch { $null }
}

function Has-Cmd { param([string]$Name) [bool](Get-Command $Name -ErrorAction SilentlyContinue) }

function Row { param($Name, $Value) [pscustomobject]@{ Property = $Name; Value = "$Value" } }

# ==========================================================================
#  COLLECTORS
# ==========================================================================

function Collect-System {
    $cs  = Try-Cim { Get-CimInstance Win32_ComputerSystem }
    $os  = Try-Cim { Get-CimInstance Win32_OperatingSystem }
    $bios= Try-Cim { Get-CimInstance Win32_BIOS }
    $bb  = Try-Cim { Get-CimInstance Win32_BaseBoard }
    $rows = @(
        Row 'Machine'      ($cs.Name)
        Row 'Manufacturer' ($cs.Manufacturer)
        Row 'Model'        ($cs.Model)
        Row 'Motherboard'  ("{0} {1}" -f $bb.Manufacturer, $bb.Product)
        Row 'BIOS'         ("{0}  (released {1:yyyy-MM-dd})" -f $bios.SMBIOSBIOSVersion, $bios.ReleaseDate)
        Row 'OS'           ("{0} ({1})" -f $os.Caption, $os.Version)
    )
    Add-Section 'System' $rows

    # OS end-of-life rule
    if ($os.Caption -match 'Windows 10') {
        Add-Finding 'WARN' 'OS' 'Windows 10 reached end of support (Oct 2025) - no more security updates.' 'Plan a move to Windows 11 (this hardware qualifies).'
    }
    # BIOS age rule
    if ($bios.ReleaseDate) {
        $age = ((Get-Date) - $bios.ReleaseDate).Days / 365.0
        if ($age -ge 3) {
            Add-Finding 'WARN' 'BIOS' ("BIOS is ~{0:N1} years old ({1:yyyy-MM-dd})." -f $age, $bios.ReleaseDate) 'Check the vendor for a newer BIOS (required before any CPU-family upgrade).'
        }
    }
}

function Collect-CPU {
    $cpu = Try-Cim { Get-CimInstance Win32_Processor | Select-Object -First 1 }
    if (-not $cpu) { return }
    Add-Section 'CPU' @(
        Row 'Name'    ($cpu.Name.Trim())
        Row 'Socket'  ($cpu.SocketDesignation)
        Row 'Cores'   ("{0} cores / {1} threads" -f $cpu.NumberOfCores, $cpu.NumberOfLogicalProcessors)
        Row 'Clock'   ("{0} MHz base" -f $cpu.MaxClockSpeed)
        Row 'L3 cache'("{0} KB" -f $cpu.L3CacheSize)
    )
}

function Collect-GPU {
    $gpus = Try-Cim { Get-CimInstance Win32_VideoController |
        Where-Object { $_.Name -notmatch 'Remote|Virtual|Basic Display|Mirror|Meta' } }
    if (-not $gpus) { $gpus = Try-Cim { Get-CimInstance Win32_VideoController } }
    $rows = @()
    foreach ($g in $gpus) {
        $rows += Row $g.Name ("driver {0}  ({1})" -f $g.DriverVersion, $g.VideoProcessor)
        if ($g.CurrentRefreshRate) {
            $res = "{0}x{1} @ {2}Hz" -f $g.CurrentHorizontalResolution, $g.CurrentVerticalResolution, $g.CurrentRefreshRate
            $rows += Row "  active display" $res
            if ([int]$g.CurrentRefreshRate -le 60) {
                Add-Finding 'WARN' 'Display' ("Active display runs at only {0}Hz ({1})." -f $g.CurrentRefreshRate, $res) 'A high-refresh (144Hz+) panel is the biggest perceived upgrade for a strong GPU.'
            }
        }
    }
    Add-Section 'GPU / Display' $rows
}

function Collect-Memory {
    $os = Try-Cim { Get-CimInstance Win32_OperatingSystem }
    $arr= Try-Cim { Get-CimInstance Win32_PhysicalMemoryArray | Select-Object -First 1 }
    $dimms = @(Try-Cim { Get-CimInstance Win32_PhysicalMemory })
    $totalGB = if ($os) { [math]::Round($os.TotalVisibleMemorySize/1MB,1) } else { 0 }
    $rows = @( Row 'Installed' ("{0} GB across {1} module(s)" -f $totalGB, $dimms.Count) )
    $minSpeed = 99999
    foreach ($d in $dimms) {
        $cap = [math]::Round($d.Capacity/1GB)
        $spd = if ($d.ConfiguredClockSpeed) { $d.ConfiguredClockSpeed } else { $d.Speed }
        if ($spd -and $spd -lt $minSpeed) { $minSpeed = $spd }
        $rows += Row $d.DeviceLocator ("{0} GB @ {1} MHz  {2}" -f $cap, $spd, $d.Manufacturer)
    }
    if ($arr) { $rows += Row 'DIMM slots' ("{0} used / {1} total" -f $dimms.Count, $arr.MemoryDevices)
        if ($dimms.Count -lt $arr.MemoryDevices) {
            Add-Finding 'INFO' 'Memory' ("{0} of {1} DIMM slots free." -f ($arr.MemoryDevices-$dimms.Count), $arr.MemoryDevices) 'Room to add RAM without removing existing sticks.'
        }
    }
    Add-Section 'Memory' $rows
    if ($totalGB -gt 0 -and $totalGB -lt 24) {
        Add-Finding 'WARN' 'Memory' ("Only {0} GB RAM installed." -f $totalGB) '32 GB is the comfortable baseline for dev/engineering + gaming.'
    }
    if ($minSpeed -ne 99999 -and $minSpeed -lt 3200) {
        Add-Finding 'WARN' 'Memory' ("RAM running at {0} MHz." -f $minSpeed) 'DDR4-3600 CL16 (with XMP/DOCP on) is the Ryzen sweet spot.'
    }
}

function Collect-Storage {
    if (Has-Cmd 'Get-PhysicalDisk') {
        $disks = Try-Cim { Get-PhysicalDisk }
        $rows = @()
        foreach ($d in $disks) {
            $rows += Row $d.FriendlyName ("{0}  {1}  {2} GB  [{3}]" -f $d.MediaType, $d.BusType, [math]::Round($d.Size/1GB), $d.HealthStatus)
            if ($d.HealthStatus -and $d.HealthStatus -ne 'Healthy') {
                Add-Finding 'CRIT' 'Storage' ("Disk '{0}' health is {1}." -f $d.FriendlyName, $d.HealthStatus) 'Back up and replace this drive.'
            }
        }
        Add-Section 'Storage (disks)' $rows
    }
    if (Has-Cmd 'Get-Volume') {
        $vols = Try-Cim { Get-Volume | Where-Object DriveLetter }
        $rows = @()
        foreach ($v in $vols) {
            $sizeGB = [math]::Round($v.Size/1GB); $freeGB = [math]::Round($v.SizeRemaining/1GB)
            $pct = if ($v.Size) { [math]::Round(100*$v.SizeRemaining/$v.Size) } else { 0 }
            $rows += Row ("{0}:  {1}" -f $v.DriveLetter, $v.FileSystemLabel) ("{0} GB free / {1} GB  ({2}%)" -f $freeGB, $sizeGB, $pct)
            if ($v.Size -and $pct -lt 10) {
                Add-Finding 'WARN' 'Storage' ("Drive {0}: is {1}% free." -f $v.DriveLetter, $pct) 'Free space or move data; <10% hurts performance.'
            }
        }
        Add-Section 'Storage (volumes)' $rows
    }
    # TRIM
    $trim = & fsutil behavior query DisableDeleteNotify 2>$null | Out-String
    if ($trim -match 'NTFS DisableDeleteNotify = (\d)') {
        $on = ($matches[1] -eq '0')
        Add-Section 'TRIM' @( Row 'NTFS TRIM' $(if ($on) { 'Enabled' } else { 'DISABLED' }) )
        if (-not $on) { Add-Finding 'WARN' 'Storage' 'SSD TRIM is disabled.' 'Run: fsutil behavior set DisableDeleteNotify 0' }
    }
}

function Collect-Power {
    $active = (& powercfg /getactivescheme 2>$null | Out-String)
    $name = if ($active -match '\((.+)\)') { $matches[1] } else { 'unknown' }
    $hiber = (Try-Cim { Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power' -Name HiberbootEnabled -ErrorAction SilentlyContinue }).HiberbootEnabled
    $pf = @(Try-Cim { Get-CimInstance Win32_PageFileUsage })
    $pfTotal = ($pf | Measure-Object AllocatedBaseSize -Sum).Sum
    $os = Try-Cim { Get-CimInstance Win32_OperatingSystem }
    $ramGB = if ($os) { [math]::Round($os.TotalVisibleMemorySize/1MB) } else { 0 }
    Add-Section 'Power & Memory tuning' @(
        Row 'Active power plan' $name
        Row 'Fast Startup'      $(if ($hiber -eq 1) { 'ON' } elseif ($hiber -eq 0) { 'off' } else { 'default' })
        Row 'Pagefile total'    ("{0} MB" -f ([int]$pfTotal))
    )
    if ($name -match 'Balanced|Power saver') {
        Add-Finding 'WARN' 'Power' ("Active plan is '$name'.") 'Switch to High or Ultimate Performance on a desktop.'
    }
    if ($hiber -eq 1) {
        Add-Finding 'INFO' 'Power' 'Fast Startup is enabled.' 'Disable for clean cold boots; REQUIRED off before a BIOS flash.'
    }
    if ($pfTotal -and $ramGB -and ($pfTotal -lt 4096 -or $pfTotal -lt ($ramGB*1024*0.25))) {
        Add-Finding 'WARN' 'Memory' ("Pagefile is only {0} MB on {1} GB RAM." -f [int]$pfTotal, $ramGB) 'Set a fixed pagefile (e.g. 8-32 GB) to prevent out-of-memory crashes.'
    }
}

function Collect-GpuTuning {
    $hags = (Try-Cim { Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\GraphicsDrivers' -Name HwSchMode -ErrorAction SilentlyContinue }).HwSchMode
    $gmode= (Try-Cim { Get-ItemProperty 'HKCU:\Software\Microsoft\GameBar' -Name AutoGameModeEnabled -ErrorAction SilentlyContinue }).AutoGameModeEnabled
    $vbs  = Try-Cim { Get-CimInstance -Namespace root\Microsoft\Windows\DeviceGuard -ClassName Win32_DeviceGuard }
    $vbsState = switch ($vbs.VirtualizationBasedSecurityStatus) { 2 {'Running'} 1 {'Enabled (not running)'} 0 {'Off'} default {'Unknown'} }
    Add-Section 'GPU / Security tuning' @(
        Row 'HW GPU scheduling (HAGS)' $(if ($hags -eq 2) {'On'} elseif ($hags -eq 1) {'Off'} else {'default'})
        Row 'Game Mode'                $(if ($gmode -eq 1) {'On'} else {'Off'})
        Row 'VBS (core isolation)'     $vbsState
    )
    if ($hags -ne 2) { Add-Finding 'INFO' 'GPU' 'Hardware-accelerated GPU scheduling is off.' 'Enable for a modern GPU (Settings > Display > Graphics).' }
    if ($vbs.VirtualizationBasedSecurityStatus -eq 2) {
        Add-Finding 'INFO' 'Performance' 'VBS is running (~5-8% gaming cost).' 'Tradeoff: tied to WSL2/Docker. Disable only on a pure gaming box.'
    }
}

function Collect-Startup {
    $heavy = 'Docker','LM Studio','Steam','Epic','EADM','EA Desktop','GalaxyClient','Ubisoft','Riot','LMStudio'
    $rows = @(); $enabledHeavy = @()
    $saRun = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run'
    $sa = Try-Cim { Get-ItemProperty $saRun -ErrorAction SilentlyContinue }
    foreach ($hive in 'HKCU','HKLM') {
        $run = Try-Cim { Get-Item "${hive}:\Software\Microsoft\Windows\CurrentVersion\Run" }
        if (-not $run) { continue }
        foreach ($name in $run.Property) {
            $state = 'enabled'
            $b = if ($sa) { $sa.$name } else { $null }
            if ($b -and $b[0] -eq 3) { $state = 'disabled' }
            $rows += Row $name $state
            if ($state -eq 'enabled' -and ($heavy | Where-Object { $name -match [regex]::Escape($_) })) {
                $enabledHeavy += $name
            }
        }
    }
    Add-Section 'Startup items' $rows
    if ($enabledHeavy.Count) {
        Add-Finding 'INFO' 'Startup' ("Heavy auto-start apps enabled: {0}." -f ($enabledHeavy -join ', ')) 'Launch these on demand to cut boot time and free RAM (run with -Fix).'
    }
}

function Collect-Network {
    if (-not (Has-Cmd 'Get-NetAdapter')) { return }
    $ad = @(Try-Cim { Get-NetAdapter | Where-Object Status -eq 'Up' })
    $rows = @(); $hasFastWired = $false; $slowActive = $false; $wirelessActive = $false
    foreach ($a in $ad) {
        $rows += Row $a.Name ("{0}  -  {1}" -f $a.InterfaceDescription, $a.LinkSpeed)
        if ($a.Speed -and $a.Speed -lt 1000000000) { $slowActive = $true }
        if ($a.InterfaceDescription -match 'Wireless|Wi-?Fi|802\.11') { $wirelessActive = $true }
    }
    $eth = @(Try-Cim { Get-NetAdapter | Where-Object { $_.InterfaceDescription -match 'Ethernet|GbE|Realtek PCIe|Intel.*I2' -and $_.InterfaceDescription -notmatch 'Wireless' } })
    if ($eth) { $hasFastWired = $true }
    Add-Section 'Network (active)' $rows
    if ($slowActive) { Add-Finding 'WARN' 'Network' 'Active link is below 1 Gbps.' 'Use wired Gigabit Ethernet, or a Wi-Fi 6E card (AX210).' }
    if ($wirelessActive -and $hasFastWired) { Add-Finding 'INFO' 'Network' 'On Wi-Fi while an Ethernet port exists.' 'A cable gives lower latency and zero packet loss - the biggest free win.' }
}

function Collect-Security {
    if (Has-Cmd 'Get-MpComputerStatus') {
        $mp = Try-Cim { Get-MpComputerStatus }
        if ($mp) {
            Add-Section 'Security (Defender)' @(
                Row 'Antivirus'    $(if ($mp.AntivirusEnabled) {'Enabled'} else {'DISABLED'})
                Row 'Real-time'    $(if ($mp.RealTimeProtectionEnabled) {'On'} else {'OFF'})
                Row 'Signature age'("{0} day(s)" -f $mp.AntivirusSignatureAge)
            )
            if (-not $mp.RealTimeProtectionEnabled) { Add-Finding 'CRIT' 'Security' 'Real-time protection is OFF.' 'Re-enable Defender real-time protection.' }
            if ($mp.AntivirusSignatureAge -gt 3) { Add-Finding 'WARN' 'Security' ("AV signatures are {0} days old." -f $mp.AntivirusSignatureAge) 'Run Windows Update / signature update.' }
        }
    }
    if (Has-Cmd 'Get-AppxPackage') {
        $bloatRx = 'BingWeather|BingSearch|GetHelp|Getstarted|3DViewer|SolitaireCollection|MixedReality|People$|SkypeApp|FeedbackHub|YourPhone|ZuneMusic|ZuneVideo'
        $bloat = @(Try-Cim { Get-AppxPackage | Where-Object { $_.Name -match $bloatRx } })
        Add-Section 'Bloatware' @( Row 'Removable stock apps present' $bloat.Count )
        if ($bloat.Count -gt 0) { Add-Finding 'INFO' 'Bloat' ("{0} removable stock UWP apps present." -f $bloat.Count) 'Purge with -Fix (Xbox/Game Bar preserved).' }
    }
}

# ==========================================================================
#  RENDERERS
# ==========================================================================

function Write-Console {
    $sev = @{ CRIT='Red'; WARN='Yellow'; INFO='Cyan'; OK='Green' }
    Write-Host ""
    Write-Host "  POTATO AUDIT  -  $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor White
    Write-Host "  =======================================================" -ForegroundColor DarkGray
    foreach ($name in $script:Sections.Keys) {
        Write-Host "`n  [$name]" -ForegroundColor White
        foreach ($r in $script:Sections[$name]) {
            Write-Host ("    {0,-26} {1}" -f $r.Property, $r.Value) -ForegroundColor Gray
        }
    }
    Write-Host "`n  FINDINGS" -ForegroundColor White
    Write-Host "  --------" -ForegroundColor DarkGray
    if ($script:Findings.Count -eq 0) { Write-Host "    Nothing flagged. This box is a unit." -ForegroundColor Green }
    foreach ($f in ($script:Findings | Sort-Object { @{CRIT=0;WARN=1;INFO=2;OK=3}[$_.Level] })) {
        Write-Host ("    [{0}] {1}: {2}" -f $f.Level, $f.Area, $f.Message) -ForegroundColor $sev[$f.Level]
        if ($f.Recommendation) { Write-Host ("           -> {0}" -f $f.Recommendation) -ForegroundColor DarkGray }
    }
    Write-Host ""
}

function Write-HtmlReport {
    param([string]$Path)
    $css = @"
<style>
 body{font-family:Segoe UI,Arial,sans-serif;background:#1b1b1b;color:#e6e6e6;margin:24px;}
 h1{font-weight:600} h2{border-bottom:1px solid #3a3a3a;padding-bottom:4px;margin-top:28px}
 table{border-collapse:collapse;width:100%;margin:8px 0} td,th{padding:6px 10px;border-bottom:1px solid #2c2c2c;text-align:left;font-size:13px}
 th{color:#9ad;}
 .CRIT{color:#ff6b6b;font-weight:600}.WARN{color:#ffcf5c;font-weight:600}.INFO{color:#7fd3ff}.OK{color:#7CFC8A}
 .tag{display:inline-block;min-width:46px;text-align:center;border-radius:4px;padding:1px 6px;margin-right:8px}
 .muted{color:#888;font-size:12px}
</style>
"@
    $sb = New-Object System.Text.StringBuilder
    [void]$sb.AppendLine("<html><head><meta charset='utf-8'>$css</head><body>")
    [void]$sb.AppendLine("<h1>&#127813; Potato Audit</h1><div class='muted'>$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') &middot; $env:COMPUTERNAME</div>")
    [void]$sb.AppendLine("<h2>Findings</h2><table><tr><th>Level</th><th>Area</th><th>Finding</th><th>Recommendation</th></tr>")
    foreach ($f in ($script:Findings | Sort-Object { @{CRIT=0;WARN=1;INFO=2;OK=3}[$_.Level] })) {
        [void]$sb.AppendLine("<tr><td><span class='tag $($f.Level)'>$($f.Level)</span></td><td>$([System.Web.HttpUtility]::HtmlEncode($f.Area))</td><td>$([System.Web.HttpUtility]::HtmlEncode($f.Message))</td><td class='muted'>$([System.Web.HttpUtility]::HtmlEncode($f.Recommendation))</td></tr>")
    }
    [void]$sb.AppendLine("</table>")
    foreach ($name in $script:Sections.Keys) {
        [void]$sb.AppendLine("<h2>$([System.Web.HttpUtility]::HtmlEncode($name))</h2><table>")
        foreach ($r in $script:Sections[$name]) {
            [void]$sb.AppendLine("<tr><td style='width:240px;color:#9ad'>$([System.Web.HttpUtility]::HtmlEncode($r.Property))</td><td>$([System.Web.HttpUtility]::HtmlEncode($r.Value))</td></tr>")
        }
        [void]$sb.AppendLine("</table>")
    }
    [void]$sb.AppendLine("</body></html>")
    $sb.ToString() | Out-File -FilePath $Path -Encoding utf8
}

function Write-JsonSnapshot {
    param([string]$Path)
    $snap = [ordered]@{
        timestamp = (Get-Date -Format 'o')
        computer  = $env:COMPUTERNAME
        sections  = [ordered]@{}
        findings  = @($script:Findings)
    }
    foreach ($name in $script:Sections.Keys) {
        $snap.sections[$name] = @($script:Sections[$name] | ForEach-Object { @{ ($_.Property) = $_.Value } })
    }
    $snap | ConvertTo-Json -Depth 6 | Out-File -FilePath $Path -Encoding utf8
}

# ==========================================================================
#  RUN
# ==========================================================================
try { Add-Type -AssemblyName System.Web -ErrorAction SilentlyContinue } catch {}

Collect-System
Collect-CPU
Collect-GPU
Collect-Memory
Collect-Storage
Collect-Power
Collect-GpuTuning
Collect-Startup
Collect-Network
Collect-Security

Write-Console

if (-not $NoHtml -or -not $NoJson) { New-Item -ItemType Directory -Force $OutDir | Out-Null }
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
if (-not $NoHtml) {
    $html = Join-Path $OutDir "audit-$stamp.html"
    Write-HtmlReport -Path $html
    Write-Host "  HTML report : $html" -ForegroundColor Green
    if (-not $Quiet) { try { Start-Process $html } catch {} }
}
if (-not $NoJson) {
    $json = Join-Path $OutDir "audit-$stamp.json"
    Write-JsonSnapshot -Path $json
    Write-Host "  JSON snapshot: $json" -ForegroundColor Green
}
Write-Host ""
