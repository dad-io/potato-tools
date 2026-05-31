$src = @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public class W {
  [DllImport("user32.dll")] public static extern IntPtr FindWindowEx(IntPtr p,IntPtr a,string c,string w);
  public delegate bool EnumProc(IntPtr h,IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb,IntPtr l);
  [DllImport("user32.dll",CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr h,StringBuilder s,int m);
  [DllImport("user32.dll",CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h,StringBuilder s,int m);
  public static string Cls(IntPtr h){var s=new StringBuilder(256);GetClassName(h,s,256);return s.ToString();}
  public static string Txt(IntPtr h){var s=new StringBuilder(256);GetWindowText(h,s,256);return s.ToString();}
}
"@
Add-Type -TypeDefinition $src

# find Progman handle via enumeration (FindWindow null-marshaling is flaky in PS)
$script:progman = [IntPtr]::Zero
$cb = [W+EnumProc]{ param($h,$l)
  if ([W]::Cls($h) -eq 'Progman') { $script:progman = $h; return $false }
  return $true
}
[W]::EnumWindows($cb,[IntPtr]::Zero) | Out-Null
"Progman = 0x{0:X}" -f $script:progman.ToInt64()
"--- direct children of Progman, Z-order front(0) -> back ---"
$child = [IntPtr]::Zero; $z = 0
$defZ = -1; $hudZ = -1
$NUL = [NullString]::Value   # PS marshals bare $null to "" which matches no class
while ($true) {
  $child = [W]::FindWindowEx($script:progman, $child, $NUL, $NUL)
  if ($child -eq [IntPtr]::Zero) { break }
  $c = [W]::Cls($child); $t = [W]::Txt($child)
  $tag = ''
  if ($c -eq 'SHELLDLL_DefView') { $defZ = $z; $tag = '   <== DESKTOP ICONS' }
  if ($t -eq 'HudWallpaper')     { $hudZ = $z; $tag = '   <== HUD WALLPAPER' }
  "Z={0,-3} hwnd=0x{1:X} cls={2,-34} title='{3}'{4}" -f $z, $child.ToInt64(), $c, $t, $tag
  $z++
}
""
if ($defZ -ge 0 -and $hudZ -ge 0) {
  if ($hudZ -gt $defZ) { "RESULT: OK - HUD (Z=$hudZ) is BEHIND icons (Z=$defZ). Icons render in front. [PASS]" }
  else                 { "RESULT: BAD - HUD (Z=$hudZ) is IN FRONT of icons (Z=$defZ). Icons hidden. [FAIL]" }
} else {
  "RESULT: could not locate both (defZ=$defZ hudZ=$hudZ)"
}
