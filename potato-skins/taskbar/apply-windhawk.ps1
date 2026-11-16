# apply-windhawk.ps1 - write the Fibb Crystal Dark styles into the Windows 11 Taskbar Styler mod (run elevated).
# Needs Windhawk with the "Windows 11 Taskbar Styler" mod installed. Settings live flattened in the registry,
# the same way Windhawk's own settings page saves them.
$ErrorActionPreference = 'Stop'
$key = 'HKLM:\SOFTWARE\Windhawk\Engine\Mods\windows-11-taskbar-styler\Settings'
if (-not (Test-Path $key)) { throw 'Install the Windows 11 Taskbar Styler mod in Windhawk first.' }
$cfg = Get-Content (Join-Path $PSScriptRoot 'windhawk-taskbar-styler.json') -Raw | ConvertFrom-Json

# clear previous control styles, then write ours
(Get-Item $key).Property | Where-Object { $_ -like 'controlStyles*' } | ForEach-Object { Remove-ItemProperty $key -Name $_ }
Set-ItemProperty $key -Name 'theme' -Value $cfg.theme -Type String
for ($i = 0; $i -lt $cfg.controlStyles.Count; $i++) {
    $c = $cfg.controlStyles[$i]
    Set-ItemProperty $key -Name "controlStyles[$i].target" -Value $c.target -Type String
    for ($j = 0; $j -lt $c.styles.Count; $j++) {
        Set-ItemProperty $key -Name "controlStyles[$i].styles[$j]" -Value $c.styles[$j] -Type String
    }
}
# bump the mod's settings-changed counter if present so the engine reloads it, then restart Windhawk
$mod = Split-Path $key -Parent
$sc = (Get-ItemProperty $mod -ErrorAction SilentlyContinue).SettingsChangeTime
if ($null -ne $sc) { Set-ItemProperty $mod -Name SettingsChangeTime -Value ([int]([DateTimeOffset]::UtcNow.ToUnixTimeSeconds())) -Type DWord }
& (Join-Path $env:ProgramFiles 'Windhawk\windhawk.exe') -restart -tray-only
Write-Host "Taskbar Styler: $($cfg.controlStyles.Count) Fibb styles written."
