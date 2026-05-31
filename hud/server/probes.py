#!/usr/bin/env python3
"""
probes.py - raw Windows telemetry layer for the wallpaper HUD.

Every probe is exception-safe and returns plain numbers in base units
(bytes, percent, MHz, watts, degrees C). It does NOT compute rates,
ratios, or diagnoses - that is the job of the HMI modules. Rate-based
signals (net throughput, disk I/O, pageins) need a previous sample and
are derived one layer up, in the server snapshot assembler.

Sources, in order of preference:
  - psutil           CPU / RAM / disk / net / process tables
  - nvidia-smi       GPU totals, thermals, clocks, power, PCIe, throttle bitmask
  - PDH counters     per-process dedicated VRAM  (nvidia-smi returns N/A on WDDM)
  - Core Temp shmem  per-core package temperatures
  - LM Studio API    loaded model, context window, runtime state
"""

import ctypes
import json
import mmap
import struct
import subprocess
import sys
import time
import urllib.request
from ctypes import wintypes

try:
    import psutil
except Exception:  # pragma: no cover - psutil is a hard dependency, but degrade
    psutil = None


CREATE_NO_WINDOW = 0x08000000  # keep nvidia-smi from flashing a console


def _run(args, timeout=2.0, default=""):
    """Run a console command without spawning a visible window."""
    try:
        r = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        )
        return r.stdout
    except Exception:
        return default


# ======================================================================
#  CPU
# ======================================================================

def cpu_sample():
    """Per-core and aggregate CPU. percpu percentages are since last call,
    so the sampler must call this on a fixed cadence for them to mean
    'utilisation over the last interval'."""
    if not psutil:
        return {}
    try:
        per = psutil.cpu_percent(percpu=True)
        freq = psutil.cpu_freq()
        stats = psutil.cpu_stats()
        return {
            "overall": sum(per) / len(per) if per else 0.0,
            "per_core": per,
            "core_count": len(per),
            "freq_mhz": freq.current if freq else 0.0,
            "freq_max_mhz": freq.max if freq else 0.0,
            "ctx_switches": stats.ctx_switches,
            "interrupts": stats.interrupts,
        }
    except Exception:
        return {}


# ======================================================================
#  Memory  (psutil + GlobalMemoryStatusEx for commit charge)
# ======================================================================

class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _commit_charge():
    """Returns (commit_used_bytes, commit_limit_bytes). The commit limit is
    physical RAM + page file; commit charge crossing it is the real Windows
    out-of-memory wall, well before RAM 'used' looks alarming."""
    try:
        m = _MEMORYSTATUSEX()
        m.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            limit = m.ullTotalPageFile
            used = m.ullTotalPageFile - m.ullAvailPageFile
            return used, limit
    except Exception:
        pass
    return 0, 0


def mem_sample():
    if not psutil:
        return {}
    try:
        vm = psutil.virtual_memory()
        sw = psutil.swap_memory()
        commit_used, commit_limit = _commit_charge()
        return {
            "total": vm.total,
            "available": vm.available,   # Windows 'available' = free + reclaimable standby
            "used": vm.used,
            "percent": vm.percent,
            "swap_total": sw.total,
            "swap_used": sw.used,
            "swap_sin": sw.sin,          # cumulative bytes paged in
            "swap_sout": sw.sout,        # cumulative bytes paged out
            "commit_used": commit_used,
            "commit_limit": commit_limit,
        }
    except Exception:
        return {}


# ======================================================================
#  Disks  (capacity per fixed drive + cumulative I/O counters)
# ======================================================================

def disk_sample(drives):
    out = {"vols": {}, "io": {}}
    if not psutil:
        return out
    for d in drives:
        try:
            u = psutil.disk_usage(d + ":\\")
            out["vols"][d] = {"total": u.total, "used": u.used,
                              "free": u.free, "percent": u.percent}
        except Exception:
            pass
    try:
        io = psutil.disk_io_counters(perdisk=False)
        if io:
            out["io"] = {"read_bytes": io.read_bytes, "write_bytes": io.write_bytes,
                         "read_time": io.read_time, "write_time": io.write_time,
                         "busy_time": getattr(io, "busy_time", 0)}
    except Exception:
        pass
    return out


# ======================================================================
#  Network  (cumulative counters; rates derived upstream)
# ======================================================================

def net_sample():
    if not psutil:
        return {}
    try:
        n = psutil.net_io_counters()
        return {"bytes_sent": n.bytes_sent, "bytes_recv": n.bytes_recv,
                "errin": n.errin, "errout": n.errout,
                "dropin": n.dropin, "dropout": n.dropout}
    except Exception:
        return {}


# ======================================================================
#  GPU  (nvidia-smi: one call, all the fields the algorithms need)
# ======================================================================

# clocks_event_reasons.active is a 64-bit bitmask. Decode the bits that
# matter for LLM inference health.
THROTTLE_BITS = [
    (0x0000000000000001, "gpu_idle"),
    (0x0000000000000002, "app_clocks"),
    (0x0000000000000004, "sw_power_cap"),       # hitting the power limit
    (0x0000000000000008, "hw_slowdown"),        # generic hardware slowdown
    (0x0000000000000010, "sync_boost"),
    (0x0000000000000020, "sw_thermal"),         # driver thermal management
    (0x0000000000000040, "hw_thermal"),         # hardware thermal slowdown (hot!)
    (0x0000000000000080, "hw_power_brake"),     # external power brake
    (0x0000000000000100, "display_clocks"),
]

_GPU_FIELDS = [
    "utilization.gpu", "utilization.memory",
    "memory.used", "memory.free", "memory.total",
    "temperature.gpu", "temperature.memory",
    "power.draw", "power.limit", "enforced.power.limit",
    "clocks.sm", "clocks.mem", "clocks.gr",
    "clocks.max.sm", "clocks.max.mem",
    "pcie.link.gen.current", "pcie.link.gen.max",
    "pcie.link.width.current", "pcie.link.width.max",
    "fan.speed",
    "clocks_event_reasons.active",
]


def _f(s):
    try:
        return float(str(s).strip().split()[0])
    except Exception:
        return 0.0


def gpu_smi():
    out = _run(["nvidia-smi", "--query-gpu=" + ",".join(_GPU_FIELDS),
                "--format=csv,noheader,nounits"], timeout=2.5)
    if not out.strip():
        return {}
    parts = [p.strip() for p in out.strip().splitlines()[0].split(",")]
    if len(parts) < len(_GPU_FIELDS):
        return {}
    g = dict(zip(_GPU_FIELDS, parts))
    try:
        mask = int(g["clocks_event_reasons.active"], 16)
    except Exception:
        mask = 0
    reasons = [name for bit, name in THROTTLE_BITS if mask & bit]
    return {
        "util": _f(g["utilization.gpu"]),
        "mem_util": _f(g["utilization.memory"]),       # % of mem bandwidth in use
        "vram_used": _f(g["memory.used"]) * 1024 ** 2,
        "vram_free": _f(g["memory.free"]) * 1024 ** 2,
        "vram_total": _f(g["memory.total"]) * 1024 ** 2,
        "temp": _f(g["temperature.gpu"]),
        "temp_mem": _f(g["temperature.memory"]),
        "power": _f(g["power.draw"]),
        "power_limit": _f(g["enforced.power.limit"]) or _f(g["power.limit"]),
        "clock_sm": _f(g["clocks.sm"]),
        "clock_mem": _f(g["clocks.mem"]),
        "clock_gr": _f(g["clocks.gr"]),
        "clock_sm_max": _f(g["clocks.max.sm"]),
        "clock_mem_max": _f(g["clocks.max.mem"]),
        "pcie_gen": _f(g["pcie.link.gen.current"]),
        "pcie_gen_max": _f(g["pcie.link.gen.max"]),
        "pcie_width": _f(g["pcie.link.width.current"]),
        "pcie_width_max": _f(g["pcie.link.width.max"]),
        "fan": _f(g["fan.speed"]),
        "throttle_mask": mask,
        "throttle": reasons,
    }


# ----------------------------------------------------------------------
#  NVML path: same data as nvidia-smi but in-process (no subprocess spawn
#  every tick). Preferred when nvidia-ml-py is installed; gpu() falls back
#  to gpu_smi() otherwise.
# ----------------------------------------------------------------------

_nvml = None
_nvml_handle = None
_nvml_ok = None


def _nvml_init():
    global _nvml, _nvml_handle, _nvml_ok
    if _nvml_ok is not None:
        return _nvml_ok
    try:
        import pynvml
        pynvml.nvmlInit()
        _nvml = pynvml
        _nvml_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        _nvml_ok = True
    except Exception:
        _nvml_ok = False
    return _nvml_ok


def gpu_nvml():
    if not _nvml_init():
        return {}
    n, h = _nvml, _nvml_handle

    def g(fn, *a, default=0):
        try:
            return fn(*a)
        except Exception:
            return default

    try:
        util = g(n.nvmlDeviceGetUtilizationRates, h, default=None)
        mem = g(n.nvmlDeviceGetMemoryInfo, h, default=None)
        if util is None or mem is None:
            return {}
        sm = g(n.nvmlDeviceGetClockInfo, h, n.NVML_CLOCK_SM)
        mclk = g(n.nvmlDeviceGetClockInfo, h, n.NVML_CLOCK_MEM)
        gr = g(n.nvmlDeviceGetClockInfo, h, n.NVML_CLOCK_GRAPHICS)
        sm_max = g(n.nvmlDeviceGetMaxClockInfo, h, n.NVML_CLOCK_SM)
        mclk_max = g(n.nvmlDeviceGetMaxClockInfo, h, n.NVML_CLOCK_MEM)
        try:
            mask = n.nvmlDeviceGetCurrentClocksThrottleReasons(h)
        except Exception:
            try:
                mask = n.nvmlDeviceGetCurrentClocksEventReasons(h)
            except Exception:
                mask = 0
        plimit = g(n.nvmlDeviceGetEnforcedPowerLimit, h) or g(n.nvmlDeviceGetPowerManagementLimit, h)
        reasons = [name for bit, name in THROTTLE_BITS if mask & bit]
        return {
            "util": float(util.gpu),
            "mem_util": float(util.memory),
            "vram_used": float(mem.used),
            "vram_free": float(mem.free),
            "vram_total": float(mem.total),
            "temp": float(g(n.nvmlDeviceGetTemperature, h, n.NVML_TEMPERATURE_GPU)),
            "temp_mem": 0.0,
            "power": g(n.nvmlDeviceGetPowerUsage, h) / 1000.0,
            "power_limit": plimit / 1000.0 if plimit else 0.0,
            "clock_sm": float(sm), "clock_mem": float(mclk), "clock_gr": float(gr),
            "clock_sm_max": float(sm_max), "clock_mem_max": float(mclk_max),
            "pcie_gen": float(g(n.nvmlDeviceGetCurrPcieLinkGeneration, h)),
            "pcie_gen_max": float(g(n.nvmlDeviceGetMaxPcieLinkGeneration, h)),
            "pcie_width": float(g(n.nvmlDeviceGetCurrPcieLinkWidth, h)),
            "pcie_width_max": float(g(n.nvmlDeviceGetMaxPcieLinkWidth, h)),
            "fan": float(g(n.nvmlDeviceGetFanSpeed, h)),
            "throttle_mask": int(mask),
            "throttle": reasons,
        }
    except Exception:
        return {}


def gpu():
    """Preferred GPU probe: NVML in-process, nvidia-smi fallback."""
    d = gpu_nvml()
    return d if d else gpu_smi()


# ======================================================================
#  Per-process dedicated VRAM via PDH  (Task Manager's data source)
#  nvidia-smi cannot report per-process memory under WDDM on consumer GPUs,
#  so we read \GPU Process Memory(*)\Dedicated Usage directly.
# ======================================================================

PDH_FMT_LARGE = 0x00000400
PDH_MORE_DATA = 0x800007D2
ERROR_SUCCESS = 0


class _PDH_U(ctypes.Union):
    _fields_ = [("longValue", wintypes.LONG),
                ("doubleValue", ctypes.c_double),
                ("largeValue", ctypes.c_longlong),
                ("AnsiStringValue", ctypes.c_char_p),
                ("WideStringValue", ctypes.c_wchar_p)]


class _PDH_FMT_COUNTERVALUE(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("CStatus", wintypes.DWORD), ("u", _PDH_U)]


class _PDH_FMT_COUNTERVALUE_ITEM_W(ctypes.Structure):
    _fields_ = [("szName", wintypes.LPWSTR), ("FmtValue", _PDH_FMT_COUNTERVALUE)]


_pdh = None


def _pdh_lib():
    global _pdh
    if _pdh is None:
        _pdh = ctypes.windll.pdh
        # PDH_STATUS codes use the high bit (e.g. PDH_MORE_DATA 0x800007D2).
        # ctypes defaults to a signed return, so those compare as negative and
        # never match the positive constants. Force unsigned return values.
        for fn in ("PdhOpenQueryW", "PdhAddEnglishCounterW",
                   "PdhCollectQueryData", "PdhGetFormattedCounterArrayW",
                   "PdhGetFormattedCounterValue", "PdhCloseQuery"):
            try:
                getattr(_pdh, fn).restype = ctypes.c_uint32
            except Exception:
                pass
    return _pdh


def gpu_proc_vram():
    """Returns {pid: dedicated_vram_bytes} for every process holding GPU memory.
    Empty dict if PDH is unavailable for any reason."""
    counter_path = r"\GPU Process Memory(*)\Dedicated Usage"
    pdh = _pdh_lib()
    hquery = wintypes.HANDLE()
    if pdh.PdhOpenQueryW(None, 0, ctypes.byref(hquery)) != ERROR_SUCCESS:
        return {}
    try:
        hcounter = wintypes.HANDLE()
        if pdh.PdhAddEnglishCounterW(hquery, counter_path, 0,
                                     ctypes.byref(hcounter)) != ERROR_SUCCESS:
            return {}
        # Wildcard multi-instance counters need TWO collects: the first call
        # enumerates the instance list, the second fills in the values.
        if pdh.PdhCollectQueryData(hquery) != ERROR_SUCCESS:
            return {}
        time.sleep(0.12)
        if pdh.PdhCollectQueryData(hquery) != ERROR_SUCCESS:
            return {}

        size = wintypes.DWORD(0)
        count = wintypes.DWORD(0)
        rc = pdh.PdhGetFormattedCounterArrayW(
            hcounter, PDH_FMT_LARGE, ctypes.byref(size),
            ctypes.byref(count), None)
        if rc != PDH_MORE_DATA:
            return {}

        buf = ctypes.create_string_buffer(size.value)
        rc = pdh.PdhGetFormattedCounterArrayW(
            hcounter, PDH_FMT_LARGE, ctypes.byref(size),
            ctypes.byref(count), buf)
        if rc != ERROR_SUCCESS:
            return {}

        items = ctypes.cast(
            buf, ctypes.POINTER(_PDH_FMT_COUNTERVALUE_ITEM_W * count.value)).contents
        result = {}
        for it in items:
            name = it.szName or ""
            # instance name looks like: pid_7464_luid_0x..._0x..._phys_0
            if "pid_" not in name:
                continue
            try:
                pid = int(name.split("pid_")[1].split("_")[0])
            except Exception:
                continue
            val = int(it.FmtValue.largeValue)
            if val <= 0:
                continue
            result[pid] = result.get(pid, 0) + val
        return result
    finally:
        pdh.PdhCloseQuery(hquery)


PDH_FMT_DOUBLE = 0x00000200


def perf_doubles(paths, settle=0.25):
    """Read a list of formatted (rate/double) PDH counters in one query.
    Rate counters like '\\Memory\\Pages Output/sec' need two collects with a
    settle interval between them. Returns a list aligned with paths (0.0 on
    failure of any single counter)."""
    pdh = _pdh_lib()
    hquery = wintypes.HANDLE()
    if pdh.PdhOpenQueryW(None, 0, ctypes.byref(hquery)) != ERROR_SUCCESS:
        return [0.0] * len(paths)
    try:
        handles = []
        for p in paths:
            hc = wintypes.HANDLE()
            rc = pdh.PdhAddEnglishCounterW(hquery, p, 0, ctypes.byref(hc))
            handles.append(hc if rc == ERROR_SUCCESS else None)
        if pdh.PdhCollectQueryData(hquery) != ERROR_SUCCESS:
            return [0.0] * len(paths)
        time.sleep(settle)
        if pdh.PdhCollectQueryData(hquery) != ERROR_SUCCESS:
            return [0.0] * len(paths)
        out = []
        for hc in handles:
            if hc is None:
                out.append(0.0)
                continue
            val = _PDH_FMT_COUNTERVALUE()
            rc = pdh.PdhGetFormattedCounterValue(hc, PDH_FMT_DOUBLE, None,
                                                 ctypes.byref(val))
            out.append(float(val.doubleValue) if rc == ERROR_SUCCESS else 0.0)
        return out
    finally:
        pdh.PdhCloseQuery(hquery)


def paging_rates():
    """Hard-fault paging in pages/sec (4 KB pages). On Windows psutil reports
    swap sin/sout as 0, so we read the kernel counters directly."""
    out = perf_doubles([r"\Memory\Pages Output/sec",
                        r"\Memory\Pages Input/sec"])
    return {"pageout_pps": out[0], "pagein_pps": out[1]}


# ======================================================================
#  Core Temp shared memory  (per-core package temperatures)
#  Layout (CoreTempSharedDataEx), offsets confirmed empirically:
#    uiTjMax[0]   @ 1024  (uint32)
#    uiCoreCnt    @ 1536  (uint32)
#    fTemp[i]     @ 1544 + 4*i  (float32)
#    ucDeltaToTjMax flag @ 2685 (byte; 0 => fTemp already absolute degrees)
# ======================================================================

_CORETEMP_SIZE = 2856


def coretemp():
    mm = None
    for size in (_CORETEMP_SIZE, 4096, 2700, 2048):
        try:
            mm = mmap.mmap(-1, size, "CoreTempMappingObjectEx",
                           access=mmap.ACCESS_READ)
            break
        except Exception:
            mm = None
    if mm is None:
        return None
    try:
        data = mm.read(mm.size() if hasattr(mm, "size") else _CORETEMP_SIZE)
    except Exception:
        try:
            data = mm[:]
        except Exception:
            return None
    finally:
        try:
            mm.close()
        except Exception:
            pass

    def u32(off):
        return struct.unpack_from("<I", data, off)[0] if off + 4 <= len(data) else 0

    def f32(off):
        return struct.unpack_from("<f", data, off)[0] if off + 4 <= len(data) else 0.0

    try:
        tjmax = u32(1024)
        cnt = u32(1536)
        if not (0 < cnt <= 256):
            return None
        delta_flag = data[2685] if len(data) > 2685 else 0
        temps = []
        for i in range(cnt):
            v = f32(1544 + 4 * i)
            # delta mode reports degrees BELOW TjMax; convert to absolute
            if delta_flag and tjmax:
                v = tjmax - v
            if 0 < v < 130:
                temps.append(round(v, 1))
        if not temps:
            return None
        return {"tjmax": tjmax, "cores": temps,
                "max": max(temps), "avg": sum(temps) / len(temps)}
    except Exception:
        return None


# ======================================================================
#  LM Studio  (native /api/v0 first for rich fields, OpenAI /v1 fallback)
# ======================================================================

def _http_json(url, timeout=0.4):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return None


def lmstudio(port=1234):
    """Returns runtime state. server_up=False when the local server is off
    (the common idle case) - the HMI must handle that gracefully."""
    base = f"http://localhost:{port}"
    native = _http_json(base + "/api/v0/models")
    if native and isinstance(native, dict) and "data" in native:
        models = []
        for m in native["data"]:
            models.append({
                "id": m.get("id"),
                "state": m.get("state"),               # "loaded" | "not-loaded"
                "type": m.get("type"),
                "arch": m.get("arch"),
                "quant": m.get("quantization"),
                "ctx_max": m.get("max_context_length"),
                "ctx_loaded": m.get("loaded_context_length"),
                "publisher": m.get("publisher"),
            })
        loaded = [m for m in models if m.get("state") == "loaded"]
        return {"server_up": True, "api": "native",
                "models": models, "loaded": loaded}

    v1 = _http_json(base + "/v1/models")
    if v1 and isinstance(v1, dict) and "data" in v1:
        models = [{"id": m.get("id"), "state": "unknown"} for m in v1["data"]]
        return {"server_up": True, "api": "openai",
                "models": models, "loaded": models}

    return {"server_up": False, "models": [], "loaded": []}


# ======================================================================
#  Process attribution  (which pids belong to LM Studio)
# ======================================================================

_LMSTUDIO_HINTS = ("lm studio", "lmstudio", "llama", "mlx", "lms-")


def lmstudio_pids():
    """pids of LM Studio and its inference backend children, used to attribute
    per-process VRAM/CPU/RAM to the runtime."""
    if not psutil:
        return set()
    pids = set()
    for p in psutil.process_iter(["pid", "name", "exe"]):
        try:
            blob = " ".join(str(p.info.get(k) or "") for k in ("name", "exe")).lower()
            if any(h in blob for h in _LMSTUDIO_HINTS):
                pids.add(p.info["pid"])
        except Exception:
            continue
    return pids


def proc_resource(pids):
    """Aggregate CPU%/RAM for a set of pids (e.g. the LM Studio tree)."""
    if not psutil or not pids:
        return {"rss": 0, "cpu": 0.0, "count": 0}
    rss = 0
    cpu = 0.0
    n = 0
    for pid in pids:
        try:
            p = psutil.Process(pid)
            rss += p.memory_info().rss
            cpu += p.cpu_percent(None)  # since last call on this Process obj
            n += 1
        except Exception:
            continue
    return {"rss": rss, "cpu": cpu, "count": n}


# ======================================================================
#  Host identity  (so panel subtitles aren't hardcoded to one machine)
# ======================================================================

_host_info = None


def host_info():
    """Detected once: CPU marketing name (registry), GPU name (NVML), RAM GB.
    Lets the HMIs label themselves with whatever box they're running on."""
    global _host_info
    if _host_info is not None:
        return _host_info

    cpu = "CPU"
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                           r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
        cpu = winreg.QueryValueEx(k, "ProcessorNameString")[0]
        winreg.CloseKey(k)
        for junk in ("(R)", "(TM)", "(r)", "(tm)", "CPU", "Processor"):
            cpu = cpu.replace(junk, "")
        cpu = " ".join(cpu.split())
    except Exception:
        pass

    gpu = "GPU"
    if _nvml_init():
        try:
            name = _nvml.nvmlDeviceGetName(_nvml_handle)
            if isinstance(name, bytes):
                name = name.decode("utf-8", "replace")
            gpu = name.replace("NVIDIA GeForce ", "").replace("NVIDIA ", "").strip()
        except Exception:
            pass

    ram_gb = 0
    try:
        ram_gb = round(psutil.virtual_memory().total / 1024 ** 3)
    except Exception:
        pass

    _host_info = {"cpu": cpu or "CPU", "gpu": gpu or "GPU", "ram_gb": ram_gb}
    return _host_info


if __name__ == "__main__":
    # quick smoke test
    print("host:", host_info())
    print("cpu:", cpu_sample())
    print("mem:", mem_sample())
    print("gpu:", gpu_smi())
    print("gpu_vram_by_pid:", gpu_proc_vram())
    print("coretemp:", coretemp())
    print("lmstudio:", lmstudio())
    print("lmstudio_pids:", lmstudio_pids())
