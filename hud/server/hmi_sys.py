#!/usr/bin/env python3
"""
hmi_sys.py - general system-health HMI.

Mirrors what the Rainmeter SystemHMI skin watches (CPU / RAM / GPU / disk /
net / thermals) but the diagnostics reason across variables rather than
reading each gauge in isolation. The interesting signal is almost always in
a RELATIONSHIP:

  - hot CPU + high load        => expected, working as designed
  - hot CPU + low load         => cooling fault (dust / fan / pump), flagged
  - commit high + RAM available => reservations, not real pressure
  - RAM low  + pageouts > 0     => genuine thrash, system stutter now
  - disk write spike + pageouts => the write IS the swap thrash (one cause)
  - GPU hot + util ~0          => background compute you didn't start
  - long uptime + commit creep  => leak suspicion, reboot resets it
"""

from hmi_common import (GB, MB, channel, clamp01, fmt_gb, note, sev_by_ratio,
                        sort_notes, worst)

HMI_ID = "sys"


def build(snap):
    cpu = snap.get("cpu", {}) or {}
    mem = snap.get("mem", {}) or {}
    gpu = snap.get("gpu", {}) or {}
    disk = snap.get("disk", {}) or {}
    net = snap.get("net", {}) or {}
    uptime_s = snap.get("uptime_s", 0.0)

    channels = []
    notes = []

    # ---------------- CPU ----------------
    overall = cpu.get("overall", 0.0)
    per = cpu.get("per_core", []) or []
    hot_core = max(per) if per else 0.0
    cold_core = min(per) if per else 0.0
    spread = hot_core - cold_core
    cpu_sev = sev_by_ratio(overall / 100, 0.80, 0.93)
    channels.append(channel(
        "cpu", "CPU Load", f"{cpu.get('core_count', 0)}T · {cpu.get('freq_mhz',0)/1000:.2f} GHz",
        f"{overall:.0f}", "%", overall / 100,
        f"peak core {hot_core:.0f}%", cpu_sev))

    # single-thread bottleneck: aggregate looks calm, one core is pinned
    if overall < 45 and hot_core >= 92:
        notes.append(note("info",
            f"Single-thread bottleneck · 1 core at {hot_core:.0f}% while load is {overall:.0f}% · app won't scale across cores", "cpu-st"))
    if overall >= 90:
        notes.append(note("warn", f"Sustained CPU saturation · {overall:.0f}% across all cores", "cpu-load"))

    # ---------------- CPU thermals ----------------
    temp = cpu.get("temp")  # dict from Core Temp, or None
    if temp:
        tmax = temp.get("max", 0.0)
        tjmax = temp.get("tjmax", 0) or 95
        head = tjmax - tmax
        t_ratio = tmax / tjmax if tjmax else 0
        t_sev = sev_by_ratio(t_ratio, 0.86, 0.95)
        channels.append(channel(
            "cputemp", "CPU Thermal", f"TjMax {tjmax}° · {head:.0f}° headroom",
            f"{tmax:.0f}", "°C", t_ratio,
            f"avg {temp.get('avg',0):.0f}°", t_sev))
        if t_ratio >= 0.95:
            notes.append(note("alert", f"CPU at thermal limit · {tmax:.0f}° / TjMax {tjmax}° · clock throttling", "cpu-therm"))
        elif t_ratio >= 0.86:
            notes.append(note("warn", f"CPU hot · {tmax:.0f}° · {head:.0f}° from throttle", "cpu-therm"))
        # SUBTLE: hot while idle => cooling fault, not workload
        if tmax >= tjmax * 0.80 and overall < 25:
            notes.append(note("warn",
                f"Thermal anomaly · {tmax:.0f}° at only {overall:.0f}% load · check fan/paste/dust", "cpu-cool"))

    # ---------------- RAM ----------------
    total = mem.get("total", 0)
    avail = mem.get("available", 0)
    used = total - avail
    used_ratio = used / total if total else 0
    commit_used = mem.get("commit_used", 0)
    commit_limit = mem.get("commit_limit", 0)
    commit_ratio = commit_used / commit_limit if commit_limit else 0
    pageout_rate = mem.get("pageout_rate", 0.0)  # bytes/sec to pagefile
    avail_gb = avail / GB
    ram_sev = worst(
        sev_by_ratio(used_ratio, 0.85, 0.94),
        sev_by_ratio(commit_ratio, 0.85, 0.95))
    channels.append(channel(
        "ram", "Memory", f"{fmt_gb(avail)} GB available · commit {commit_ratio*100:.0f}%",
        f"{used/GB:.1f}", "GB", used_ratio,
        f"/ {total/GB:.0f} GB", ram_sev))

    if commit_ratio >= 0.95:
        notes.append(note("alert", f"Commit charge {commit_ratio*100:.0f}% of limit · allocations will start failing", "mem-commit"))
    elif commit_ratio >= 0.85:
        notes.append(note("warn", f"Commit charge high · {commit_used/GB:.1f}/{commit_limit/GB:.1f} GB · pagefile filling", "mem-commit"))
    # DISTINGUISH reserved-but-fine from real exhaustion
    if avail_gb < 1.0:
        notes.append(note("alert", f"Only {avail_gb:.2f} GB available · system instability likely", "mem-low"))
    elif avail_gb < 2.0:
        notes.append(note("warn", f"Only {avail_gb:.2f} GB available · pressure building", "mem-low"))
    elif commit_ratio >= 0.85 and avail_gb > 4:
        notes.append(note("info", f"High commit but {avail_gb:.1f} GB still resident · reservations, not real pressure", "mem-resv"))

    # ---------------- GPU (system view) ----------------
    g_util = gpu.get("util", 0.0)
    vused = gpu.get("vram_used", 0)
    vtotal = gpu.get("vram_total", 1)
    vratio = vused / vtotal if vtotal else 0
    g_temp = gpu.get("temp", 0.0)
    g_power = gpu.get("power", 0.0)
    g_plimit = gpu.get("power_limit", 1) or 1
    throttle = gpu.get("throttle", []) or []
    g_sev = worst(
        sev_by_ratio(vratio, 0.85, 0.95),
        sev_by_ratio(g_temp / 90, 0.85, 0.97),
        "alert" if ("hw_thermal" in throttle) else "ok")
    channels.append(channel(
        "gpu", "GPU", f"{g_temp:.0f}° · {g_power:.0f}/{g_plimit:.0f} W · {gpu.get('clock_sm',0):.0f} MHz",
        f"{g_util:.0f}", "%", g_util / 100,
        f"VRAM {vused/GB:.1f}/{vtotal/GB:.0f} GB", g_sev))

    if "hw_thermal" in throttle or "sw_thermal" in throttle:
        notes.append(note("alert", f"GPU thermal throttle active · {g_temp:.0f}° · clocks reduced", "gpu-therm"))
    if "sw_power_cap" in throttle and g_util > 50:
        notes.append(note("info", f"GPU at power limit · {g_power:.0f}/{g_plimit:.0f} W · expected under load", "gpu-power"))
    # SUBTLE: GPU busy but you're not doing anything obvious
    if g_util >= 35 and g_temp >= 55 and not snap.get("lm_active"):
        notes.append(note("info", f"GPU at {g_util:.0f}% with no tracked workload · background compute?", "gpu-bg"))

    # ---------------- DISK ----------------
    vols = disk.get("vols", {}) or {}
    read_bps = disk.get("read_bps", 0.0)
    write_bps = disk.get("write_bps", 0.0)
    busy = disk.get("busy_pct", 0.0)
    # surface the fullest fixed drive as the headline channel
    fullest = max(vols.items(), key=lambda kv: kv[1].get("percent", 0), default=None)
    if fullest:
        dl, dv = fullest
        dpct = dv.get("percent", 0)
        d_sev = sev_by_ratio(dpct / 100, 0.90, 0.97)
        channels.append(channel(
            "disk", "Storage", f"{dl}: fullest · R {read_bps/MB:.0f} / W {write_bps/MB:.0f} MB/s",
            f"{dpct:.0f}", "%", dpct / 100,
            f"{dv.get('free',0)/GB:.0f} GB free", d_sev))
        if dpct >= 97:
            sysflag = " (system drive)" if dl.upper() == "C" else ""
            notes.append(note("alert", f"{dl}: {dpct:.0f}% full{sysflag} · {dv.get('free',0)/GB:.1f} GB left", "disk-full"))
        elif dpct >= 90:
            notes.append(note("warn", f"{dl}: {dpct:.0f}% full · {dv.get('free',0)/GB:.0f} GB left", "disk-full"))

    # CROSS-HMI: heavy pagefile write IS the disk thrash
    if pageout_rate > 20 * MB and write_bps > 30 * MB:
        notes.append(note("warn",
            f"Swap thrash · {pageout_rate/MB:.0f} MB/s to pagefile driving disk to {write_bps/MB:.0f} MB/s writes", "thrash"))
    elif busy >= 95:
        notes.append(note("info", f"Disk I/O saturated · {busy:.0f}% busy", "disk-busy"))

    # ---------------- NETWORK ----------------
    up_bps = net.get("up_bps", 0.0)
    down_bps = net.get("down_bps", 0.0)
    drops = net.get("dropin", 0) + net.get("dropout", 0)
    # scale bar against a 1 Gbit reference link
    nref = 1e9 / 8
    n_ratio = max(up_bps, down_bps) / nref
    channels.append(channel(
        "net", "Network", f"↑ {up_bps*8/1e6:.1f} · ↓ {down_bps*8/1e6:.1f} Mbps",
        f"{down_bps*8/1e6:.1f}", "Mbps", n_ratio,
        f"↑ {up_bps*8/1e6:.1f} Mbps", "ok"))

    # ---------------- UPTIME / leak heuristic ----------------
    up_h = uptime_s / 3600
    if up_h >= 168:
        notes.append(note("info", f"Uptime {up_h/24:.1f} days · long sessions accumulate fragmentation · reboot resets", "uptime"))
    elif up_h >= 72 and commit_ratio >= 0.80:
        notes.append(note("info", f"Uptime {up_h/24:.1f}d + commit {commit_ratio*100:.0f}% · possible memory creep", "leak"))

    if not notes:
        notes.append(note("ok", "All subsystems nominal", "ok"))
    sort_notes(notes)

    up_str = (f"{up_h/24:.1f}d" if up_h >= 24 else f"{up_h:.1f}h")
    host = snap.get("host", {}) or {}
    subtitle = f"{host.get('cpu','CPU')} · {host.get('gpu','GPU')} · CORE TELEMETRY".upper()
    return {
        "id": HMI_ID,
        "title": "System Health",
        "subtitle": subtitle,
        "channels": channels,
        "notes": notes,
        "header": {
            "CPU": f"{overall:.0f}%",
            "RAM": f"{used_ratio*100:.0f}%",
            "GPU": f"{g_util:.0f}%",
            "UP": up_str,
        },
    }
