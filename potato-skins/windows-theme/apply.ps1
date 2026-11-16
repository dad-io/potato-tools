# apply.ps1 - Fibb Crystal Dark: Windows theme + Rainmeter panel
# Copies the wallpaper where the .theme expects it, applies the theme, and (if Rainmeter is installed)
# loads the themed SystemHMI NUC panel.
$repo = Split-Path $PSScriptRoot -Parent
$pics = Join-Path $env:USERPROFILE 'Pictures\Wallpapers'
New-Item -ItemType Directory -Force $pics | Out-Null
Copy-Item (Join-Path $repo 'wallpapers\orion-young-stars-*.jpg') $pics -Force

# Dark mode + accent are set directly too, so they stick even if the Settings window is closed early.
$p = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize'
Set-ItemProperty $p AppsUseLightTheme 0 -Type DWord
Set-ItemProperty $p SystemUsesLightTheme 0 -Type DWord
Start-Process (Join-Path $PSScriptRoot 'Fibb Crystal Dark.theme')
Start-Sleep 3

# Window chrome: Instrument Blue on active title bars + borders, Fibb panel graphite (#26323c) when inactive,
# accent on Start. (A .theme file can't carry these switches.)
Set-ItemProperty $p ColorPrevalence 1 -Type DWord
reg add "HKCU\Software\Microsoft\Windows\DWM" /v ColorPrevalence /t REG_DWORD /d 1 /f | Out-Null
reg add "HKCU\Software\Microsoft\Windows\DWM" /v AccentColorInactive /t REG_DWORD /d 0xff3c3226 /f | Out-Null
Add-Type -Namespace FibbTheme -Name Native -MemberDefinition '[DllImport("user32.dll",CharSet=CharSet.Unicode)] public static extern System.IntPtr SendMessageTimeout(System.IntPtr h,uint m,System.UIntPtr w,string l,uint f,uint t,out System.UIntPtr r);'
$r = [UIntPtr]::Zero
[void][FibbTheme.Native]::SendMessageTimeout([IntPtr]0xffff, 0x1A, [UIntPtr]::Zero, 'ImmersiveColorSet', 2, 3000, [ref]$r)

# Taskbar: clear on the desktop, graphite acrylic with windows open (TranslucentTB)
& (Join-Path $repo 'taskbar\install.ps1')

$rm = Join-Path $env:ProgramFiles 'Rainmeter\Rainmeter.exe'
if (Test-Path $rm) {
    $skins = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'Rainmeter\Skins'
    Copy-Item (Join-Path $repo 'rainmeter\SystemHMI') $skins -Recurse -Force
    & $rm '!RefreshApp'
    Start-Sleep 3
    & $rm '!ActivateConfig' 'SystemHMI' 'PanelNUC.ini'
}
Write-Host 'Fibb Crystal Dark applied.'
