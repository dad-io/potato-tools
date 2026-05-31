# ====================================================================
#  SystemHMI - poll.ps1
#  Persistent hidden background poller. Gathers all sensor/telemetry
#  data and writes a flat key=value file that Rainmeter reads.
#  Single instance enforced via a global mutex.
#
#  Args: [0] = output data file path
#        [1] = (optional) max iterations (for testing); 0/absent = forever
# ====================================================================
param([string]$OutFile, [int]$MaxIter = 0)

# --- single-instance guard ---
$created = $false
$mutex = New-Object System.Threading.Mutex($true, "Global\SystemHMI_Poller", [ref]$created)
if (-not $created) { return }   # another poller already running

$ErrorActionPreference = 'SilentlyContinue'
$cores = (Get-CimInstance Win32_Processor).NumberOfLogicalProcessors
if (-not $cores) { $cores = 16 }
$cpuBase = 3.6   # Ryzen 7 3700X base clock (GHz)

# --- native interop: Core Temp shared memory + foreground window ---
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
using System.Text;
public class HMI {
  [DllImport("kernel32.dll",SetLastError=true)] public static extern IntPtr OpenFileMapping(uint a,bool b,string n);
  [DllImport("kernel32.dll",SetLastError=true)] public static extern IntPtr MapViewOfFile(IntPtr h,uint a,uint hi,uint lo,UIntPtr sz);
  [DllImport("kernel32.dll")] public static extern bool UnmapViewOfFile(IntPtr p);
  [DllImport("kernel32.dll")] public static extern bool CloseHandle(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern IntPtr GetShellWindow();
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern IntPtr MonitorFromWindow(IntPtr h, uint f);
  [DllImport("user32.dll")] public static extern bool GetMonitorInfo(IntPtr m, ref MONITORINFO mi);
  public struct RECT { public int Left, Top, Right, Bottom; }
  public struct MONITORINFO { public int cbSize; public RECT rcMonitor; public RECT rcWork; public uint dwFlags; }
}
"@

function Read-CpuTemp {
  $h = [HMI]::OpenFileMapping(0x0004, $false, "CoreTempMappingObjectEx")
  if ($h -eq [IntPtr]::Zero) { return $null }
  try {
    $p = [HMI]::MapViewOfFile($h, 0x0004, 0, 0, [UIntPtr]::Zero)
    if ($p -eq [IntPtr]::Zero) { return $null }
    $coreCnt = [Runtime.InteropServices.Marshal]::ReadInt32($p, 1536)
    if ($coreCnt -le 0 -or $coreCnt -gt 128) { return $null }
    $max = 0.0
    for ($i = 0; $i -lt $coreCnt; $i++) {
      $bits = [Runtime.InteropServices.Marshal]::ReadInt32($p, 1544 + 4*$i)
      $t = [BitConverter]::ToSingle([BitConverter]::GetBytes($bits), 0)
      if ($t -gt $max) { $max = $t }
    }
    [HMI]::UnmapViewOfFile($p) | Out-Null
    return [int][math]::Round($max)
  } finally { [HMI]::CloseHandle($h) | Out-Null }
}

function Test-Fullscreen {
  $fg = [HMI]::GetForegroundWindow()
  if ($fg -eq [IntPtr]::Zero -or $fg -eq [HMI]::GetShellWindow()) { return 0 }
  $sb = New-Object System.Text.StringBuilder 256
  [HMI]::GetWindowText($fg, $sb, 256) | Out-Null
  $title = $sb.ToString()
  $r = New-Object HMI+RECT
  if (-not [HMI]::GetWindowRect($fg, [ref]$r)) { return 0 }
  $mon = [HMI]::MonitorFromWindow($fg, 2)
  $mi = New-Object HMI+MONITORINFO
  $mi.cbSize = [Runtime.InteropServices.Marshal]::SizeOf($mi)
  if (-not [HMI]::GetMonitorInfo($mon, [ref]$mi)) { return 0 }
  # window covers the whole monitor (>= full bounds) => fullscreen app/game
  if ($r.Left -le $mi.rcMonitor.Left -and $r.Top -le $mi.rcMonitor.Top -and `
      $r.Right -ge $mi.rcMonitor.Right -and $r.Bottom -ge $mi.rcMonitor.Bottom) { return 1 }
  return 0
}

function Get-TopCpu {
  $s = Get-Counter '\Process(*)\% Processor Time' -ErrorAction SilentlyContinue
  if (-not $s) { return '--' }
  $g = @{}
  foreach ($cs in $s.CounterSamples) {
    $n = $cs.InstanceName
    if ($n -in @('_total','idle')) { continue }
    $n = $n -replace '#\d+$',''
    $g[$n] = [double]$g[$n] + $cs.CookedValue
  }
  $top = $g.GetEnumerator() | Sort-Object Value -Descending | Select-Object -First 3 |
    ForEach-Object { '{0} {1:N0}%' -f $_.Key, ($_.Value / $cores) }
  return ($top -join '  ')
}

function Get-TopRam {
  $top = Get-Process | Group-Object ProcessName | ForEach-Object {
      [pscustomobject]@{ N = $_.Name; W = ($_.Group | Measure-Object WorkingSet64 -Sum).Sum }
    } | Sort-Object W -Descending | Select-Object -First 3 |
    ForEach-Object { '{0} {1:N1}G' -f $_.N, ($_.W / 1GB) }
  return ($top -join '  ')
}

function Get-TopVram {
  $s = Get-Counter '\GPU Process Memory(*)\Dedicated Usage' -ErrorAction SilentlyContinue
  if (-not $s) { return '--' }
  $byName = @{}
  foreach ($cs in $s.CounterSamples) {
    if ($cs.CookedValue -le 0) { continue }
    if ($cs.InstanceName -match 'pid_(\d+)') {
      $nm = (Get-Process -Id ([int]$Matches[1]) -ErrorAction SilentlyContinue).ProcessName
      if (-not $nm) { $nm = 'pid' + $Matches[1] }
      $byName[$nm] = [double]$byName[$nm] + $cs.CookedValue
    }
  }
  if ($byName.Count -eq 0) { return '--' }
  $top = $byName.GetEnumerator() | Sort-Object Value -Descending | Select-Object -First 3 |
    ForEach-Object { '{0} {1:N1}G' -f $_.Key, ($_.Value / 1GB) }
  return ($top -join '  ')
}

$iter = 0
while ($true) {
  $lines = New-Object System.Collections.Generic.List[string]

  # ---- GPU via nvidia-smi ----
  $g = & nvidia-smi --query-gpu=temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw,fan.speed,clocks.gr --format=csv,noheader,nounits 2>$null
  if ($g) {
    $f = ($g -split ',').Trim()
    $lines.Add("GPUTEMP=$($f[0])")
    $lines.Add("GPUUTIL=$($f[1])")
    $lines.Add("GPUMEMUSED=$($f[2])")
    $lines.Add("GPUMEMTOTAL=$($f[3])")
    $lines.Add("GPUPOWER=$($f[4])")
    $fan = $f[5]; if ($fan -match 'N/A') { $fan = '0' }
    $lines.Add("GPUFAN=$fan")
    $lines.Add("GPUCLOCK=$($f[6])")
  }

  # ---- CPU ----
  $ct = Read-CpuTemp
  $lines.Add("CPUTEMP=$(if ($null -ne $ct) { $ct } else { '--' })")
  $perf = (Get-Counter '\Processor Information(_Total)\% Processor Performance' -ErrorAction SilentlyContinue).CounterSamples[0].CookedValue
  if ($perf) { $lines.Add("CPUCLOCK=$('{0:N2}' -f ($cpuBase * $perf / 100))") } else { $lines.Add("CPUCLOCK=--") }

  # ---- fullscreen flag ----
  $lines.Add("FULLSCREEN=$(Test-Fullscreen)")

  # ---- top consumers ----
  $lines.Add("CPUTOP=$(Get-TopCpu)")
  $lines.Add("RAMTOP=$(Get-TopRam)")
  $lines.Add("VRAMTOP=$(Get-TopVram)")

  # ---- atomic write ----
  $tmp = "$OutFile.tmp"
  Set-Content -Path $tmp -Value $lines -Encoding ASCII -Force
  Move-Item -Path $tmp -Destination $OutFile -Force

  $iter++
  if ($MaxIter -gt 0 -and $iter -ge $MaxIter) { break }
  Start-Sleep -Milliseconds 1500
}
