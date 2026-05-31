#!/usr/bin/env python3
"""
hmi_llm.py - local LLM inference-health HMI (LM Studio on discrete NVIDIA).

The Mac original reasoned about Apple unified memory: one pool, a soft
iogpu wired limit, a compressor, and swap. A discrete RTX 5070 is a
different and richer machine to model:

  - A HARD 12 GB VRAM wall. Cross it and CUDA allocation fails outright;
    there is no compressor cushioning the fall.
  - Two memory tiers: weights+KV live in VRAM; any layers that don't fit
    spill to 16 GB system RAM and run on the CPU ("partial offload").
  - Token generation (decode) is MEMORY-BANDWIDTH bound, not compute bound.
    Prompt processing (prefill) is the opposite. The util/power/clock
    signature tells you which phase you're in.
  - Partial offload streams weights across PCIe every token, so the PCIe
    link state plus CPU busyness reveals a bottleneck the GPU gauges hide.
  - KV cache grows linearly with context. VRAM that fits at 1K tokens can
    OOM at 8K. We project the peak and warn BEFORE it crashes.

Model geometry (layers / d_model / bytes-per-weight) is estimated from the
model name + quant when the runtime doesn't report it. Estimates are
labelled "est" everywhere they surface.
"""

import re

from hmi_common import (GB, MB, channel, clamp01, fmt_gb, note, sev_by_ratio,
                        sort_notes, worst)

HMI_ID = "llm"

# Idle baselines for the RTX 5070 (desktop compositor etc.). Used to tell
# "model resident" from "just the OS" and "generating" from "idle".
IDLE_VRAM = 0.6 * GB
IDLE_POWER_W = 25.0

# bits-per-weight by quant family (effective, incl. scales/zeros overhead)
_QUANT_BPW = {
    "f32": 32.0, "f16": 16.0, "bf16": 16.0, "fp16": 16.0,
    "q8": 8.5, "q6": 6.6, "q5": 5.5, "q4": 4.7, "q3": 3.5, "q2": 2.8,
    "iq4": 4.3, "iq3": 3.3, "iq2": 2.4, "iq1": 1.7,
}

# params(B) -> (n_layers, d_model). Nearest bucket; covers common families.
_GEOMETRY = [
    (0.5, (24, 896)), (1.5, (28, 1536)), (3.0, (28, 2048)),
    (3.8, (32, 3072)), (7.0, (32, 4096)), (8.0, (32, 4096)),
    (9.0, (42, 3584)), (13.0, (40, 5120)), (14.0, (48, 5120)),
    (20.0, (44, 6144)), (27.0, (46, 4608)), (32.0, (64, 5120)),
    (34.0, (48, 7168)), (70.0, (80, 8192)), (123.0, (88, 12288)),
]
# Average grouped-query-attention factor: KV heads << query heads on modern
# models, so the KV cache is a fraction of the naive MHA size.
_GQA_FACTOR = 0.34
_CUDA_OVERHEAD = 0.7 * GB  # context + cuBLAS workspaces, roughly


def _parse_params_b(name):
    """Pull a parameter count in billions out of a model id, e.g.
    'qwen2.5-7b-instruct' -> 7.0, 'phi-3.5-mini' -> None."""
    if not name:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*[bB](?![a-zA-Z])", name)
    if m:
        try:
            v = float(m.group(1))
            if 0.1 <= v <= 1000:
                return v
        except Exception:
            pass
    return None


def _quant_bpw(name, quant):
    blob = f"{name or ''} {quant or ''}".lower()
    for key in ("iq1", "iq2", "iq3", "iq4", "q2", "q3", "q4", "q5", "q6",
                "q8", "bf16", "fp16", "f16", "f32"):
        if key in blob:
            return _QUANT_BPW[key], key.upper()
    return _QUANT_BPW["q4"], "Q4?"  # most local models default to ~Q4


def _geometry(params_b):
    best = min(_GEOMETRY, key=lambda g: abs(g[0] - params_b))
    return best[1]


def _estimate_footprint(name, quant, ctx_max, ctx_now):
    """Return an estimate dict: weights, kv_per_tok, kv_now, kv_full, peak."""
    params_b = _parse_params_b(name)
    if not params_b:
        return None
    bpw, qlabel = _quant_bpw(name, quant)
    layers, d_model = _geometry(params_b)
    weights = params_b * 1e9 * bpw / 8.0
    # KV per token (fp16 cache): 2 tensors (K,V) * layers * d_model * 2 bytes,
    # reduced by the GQA factor.
    kv_per_tok = 2 * layers * d_model * 2 * _GQA_FACTOR
    ctx_max = ctx_max or 4096
    ctx_now = ctx_now or 0
    kv_full = kv_per_tok * ctx_max
    kv_now = kv_per_tok * ctx_now
    peak = weights + kv_full + _CUDA_OVERHEAD
    return {
        "params_b": params_b, "quant": qlabel, "bpw": bpw,
        "layers": layers, "d_model": d_model,
        "weights": weights, "kv_per_tok": kv_per_tok,
        "kv_now": kv_now, "kv_full": kv_full, "peak": peak,
        "ctx_max": ctx_max, "ctx_now": ctx_now,
    }


def build(snap):
    gpu = snap.get("gpu", {}) or {}
    mem = snap.get("mem", {}) or {}
    lms = snap.get("lmstudio", {}) or {}
    lm_vram = snap.get("lm_vram", 0)     # per-proc dedicated VRAM, LM Studio tree
    lm_rss = snap.get("lm_rss", 0)       # CPU-side RSS of the tree
    lm_cpu = snap.get("lm_cpu", 0.0)     # CPU% of the tree

    vused = gpu.get("vram_used", 0)
    vtotal = gpu.get("vram_total", 12 * GB) or 12 * GB
    vfree = gpu.get("vram_free", max(0, vtotal - vused))
    util = gpu.get("util", 0.0)
    mem_util = gpu.get("mem_util", 0.0)
    power = gpu.get("power", 0.0)
    plimit = gpu.get("power_limit", 250) or 250
    temp = gpu.get("temp", 0.0)
    sm = gpu.get("clock_sm", 0.0)
    sm_max = gpu.get("clock_sm_max", 1) or 1
    mclk = gpu.get("clock_mem", 0.0)
    mclk_max = gpu.get("clock_mem_max", 1) or 1
    pcie_gen = gpu.get("pcie_gen", 0.0)
    pcie_gen_max = gpu.get("pcie_gen_max", pcie_gen) or pcie_gen
    throttle = gpu.get("throttle", []) or []

    channels = []
    notes = []

    # ---------------- STATE MACHINE ----------------
    loaded_models = lms.get("loaded", []) or []
    model = loaded_models[0] if loaded_models else None
    model_name = (model or {}).get("id") if model else None
    has_proc = bool(snap.get("lm_pids"))
    model_resident = lm_vram >= 0.8 * GB or (vused - IDLE_VRAM) >= 0.8 * GB
    generating = (power > IDLE_POWER_W * 1.6 and util >= 12) or util >= 25

    if not has_proc and not model_resident:
        state, state_sev = "OFFLINE", "info"
    elif not model_resident:
        state, state_sev = "STANDBY", "info"
    elif generating:
        state, state_sev = "INFERENCE", "ok"
    else:
        state, state_sev = "RESIDENT", "ok"
    snap["lm_active"] = generating  # let the sys HMI know the GPU load is "ours"

    # model VRAM footprint = measured dedicated VRAM if we have it, else
    # carve the OS baseline out of total used.
    model_vram = lm_vram if lm_vram >= 0.5 * GB else max(0, vused - IDLE_VRAM)

    # ---------------- footprint estimate ----------------
    ctx_max = (model or {}).get("ctx_max")
    ctx_now = (model or {}).get("ctx_loaded")
    est = _estimate_footprint(model_name, (model or {}).get("quant"),
                              ctx_max, ctx_now) if model_name else None

    # ---------------- CH 1: VRAM CEILING (the hard wall) ----------------
    vratio = vused / vtotal if vtotal else 0
    v_sev = sev_by_ratio(vratio, 0.85, 0.94)
    channels.append(channel(
        "vram", "VRAM Ceiling", f"{fmt_gb(vfree)} GB free of {vtotal/GB:.0f} GB · hard wall",
        f"{vused/GB:.1f}", "GB", vratio,
        f"{vratio*100:.0f}% · model {model_vram/GB:.1f} GB", v_sev))

    if vratio >= 0.94:
        notes.append(note("alert", f"VRAM at {vratio*100:.0f}% · {vfree/GB:.1f} GB free · next allocation may CUDA-OOM", "vram-wall"))
    elif vratio >= 0.85:
        notes.append(note("warn", f"VRAM {vratio*100:.0f}% · {vfree/GB:.1f} GB free · little room for context growth", "vram-tight"))

    # ---------------- CH 2: MODEL FOOTPRINT + FIT ----------------
    if est:
        peak = est["peak"]
        fit_ratio = peak / vtotal
        fits = peak <= vtotal
        fit_sev = "ok" if fit_ratio < 0.85 else ("warn" if fits else "alert")
        sub = (f"{est['params_b']:g}B {est['quant']} · "
               f"~{est['weights']/GB:.1f} GB wt + {est['kv_full']/GB:.1f} GB KV est")
        channels.append(channel(
            "model", "Model Footprint", sub,
            f"{peak/GB:.1f}", "GB", fit_ratio,
            ("FITS" if fits else "SPILLS") + f" @ {est['ctx_max']//1024 if est['ctx_max']>=1024 else est['ctx_max']}K", fit_sev))

        if not fits:
            deficit = peak - vtotal
            notes.append(note("warn",
                f"{est['params_b']:g}B {est['quant']} needs ~{peak/GB:.1f} GB at {est['ctx_max']}-tok context · {deficit/GB:.1f} GB over the 12 GB wall · layers will offload to CPU", "fit-spill"))
        elif fit_ratio >= 0.85:
            notes.append(note("info",
                f"Tight fit · ~{peak/GB:.1f} GB est of 12 GB at full context · headroom {(vtotal-peak)/GB:.1f} GB", "fit-tight"))

        # KV growth projection: room left for context to expand
        if model_resident and est["kv_per_tok"] > 0:
            room_tokens = max(0, vfree) / est["kv_per_tok"]
            if 0 < room_tokens < est["ctx_max"] * 0.5:
                notes.append(note("warn",
                    f"KV headroom ~{room_tokens/1024:.1f}K tokens · prompts beyond that will OOM (KV grows {est['kv_per_tok']/MB:.1f} MB/tok est)", "kv-room"))
    elif model_resident:
        # resident but no name to estimate from - report measured only
        channels.append(channel(
            "model", "Model Footprint", "measured · geometry unknown",
            f"{model_vram/GB:.1f}", "GB", model_vram / vtotal,
            "RESIDENT", "ok"))

    # ---------------- CH 3: GPU COMPUTE + phase ----------------
    sm_ratio = sm / sm_max if sm_max else 0
    # prefill = compute bound (high util + high power + high clock);
    # decode = bandwidth bound (modest util, high mem_util).
    if generating:
        if util >= 70 and power >= plimit * 0.6:
            phase = "PREFILL · compute-bound"
        elif mem_util >= 55:
            phase = "DECODE · bandwidth-bound"
        else:
            phase = "DECODE"
    else:
        phase = "idle" if model_resident else "—"
    comp_sev = "ok"
    channels.append(channel(
        "compute", "GPU Compute", f"{phase} · {sm:.0f}/{sm_max:.0f} MHz",
        f"{util:.0f}", "%", util / 100,
        f"{power:.0f}/{plimit:.0f} W", comp_sev))

    # ---------------- CH 4: MEMORY BANDWIDTH (decode bottleneck) ----------------
    mclk_ratio = mclk / mclk_max if mclk_max else 0
    bw_sev = "ok"
    channels.append(channel(
        "bandwidth", "Mem Bandwidth", f"{mclk:.0f}/{mclk_max:.0f} MHz mem clock",
        f"{mem_util:.0f}", "%", mem_util / 100,
        "decode rate driver" if generating else "—", bw_sev))
    if generating and mem_util >= 80:
        notes.append(note("info", f"Decode is memory-bandwidth bound at {mem_util:.0f}% · this is the healthy steady state · tokens/s tracks mem clock", "bw-bound"))

    # ---------------- CH 5: OFFLOAD / RAM SPILL ----------------
    avail = mem.get("available", 0)
    spill_sev = "ok"
    # partial offload signature: model resident, big CPU-side RSS, CPU busy
    # while generating, and measured VRAM below the weight estimate.
    partial = False
    if est and model_resident:
        partial = model_vram < est["weights"] * 0.85 and lm_rss > 1.5 * GB
    cpu_layers_txt = "—"
    if partial:
        offloaded = clamp01(1 - model_vram / max(est["weights"], 1))
        cpu_layers_txt = f"~{offloaded*100:.0f}% on CPU"
        spill_sev = "warn"
    channels.append(channel(
        "offload", "CPU Offload", f"RAM {lm_rss/GB:.1f} GB · {avail/GB:.1f} GB sys free",
        cpu_layers_txt if partial else f"{lm_cpu:.0f}", "%" if not partial else "",
        clamp01(lm_rss / (16 * GB)),
        "PARTIAL OFFLOAD" if partial else ("CPU idle" if generating else "—"), spill_sev))

    if partial:
        notes.append(note("warn",
            f"Partial offload · ~{(1-model_vram/max(est['weights'],1))*100:.0f}% of weights on CPU · tokens bottlenecked by PCIe + CPU, not GPU", "offload"))
        # RAM spill into system pressure is the catastrophic case
        if avail < 2 * GB:
            notes.append(note("alert",
                f"Offload RAM spill · only {avail/GB:.1f} GB system RAM free · risk of system-wide paging · throughput collapse", "spill"))
        # PCIe streaming confirmation
        if pcie_gen >= max(3, pcie_gen_max) and generating:
            notes.append(note("info",
                f"PCIe at gen{pcie_gen:.0f}×{gpu.get('pcie_width',0):.0f} during decode · weights streaming host→device every token", "pcie"))

    # ---------------- CH 6: THERMAL / POWER ----------------
    t_ratio = temp / 88
    tp_sev = worst(sev_by_ratio(t_ratio, 0.86, 0.97),
                   "alert" if "hw_thermal" in throttle else "ok")
    channels.append(channel(
        "thermal", "Thermal / Power", f"{power:.0f}/{plimit:.0f} W · fan {gpu.get('fan',0):.0f}%",
        f"{temp:.0f}", "°C", t_ratio,
        ("THROTTLING" if ("hw_thermal" in throttle or "sw_thermal" in throttle) else f"{power/plimit*100:.0f}% TDP"), tp_sev))

    if "hw_thermal" in throttle or "sw_thermal" in throttle:
        notes.append(note("alert", f"GPU thermal throttle · {temp:.0f}° · SM clock cut to {sm:.0f} MHz · tokens/s dropping", "gpu-therm"))
    elif generating and "sw_power_cap" in throttle:
        notes.append(note("info", f"Power-capped at {plimit:.0f} W · SM {sm:.0f}/{sm_max:.0f} MHz · raise TDP for more throughput", "gpu-power"))

    # ---------------- state-level notes ----------------
    if state == "OFFLINE":
        notes.append(note("info", "LM Studio not running · no model resident", "off"))
    elif state == "STANDBY":
        notes.append(note("info", "LM Studio up · no model loaded · VRAM clear", "standby"))
    elif state == "RESIDENT" and not lms.get("server_up"):
        notes.append(note("info", f"Model resident · {model_vram/GB:.1f} GB VRAM · server idle (API off)", "resident"))

    if not notes:
        notes.append(note("ok", "Inference path nominal", "ok"))
    sort_notes(notes)

    name_disp = (model_name or ("— standby" if has_proc else "— offline"))
    if len(name_disp) > 38:
        name_disp = name_disp[:36] + "…"
    host = snap.get("host", {}) or {}
    subtitle = f"LM STUDIO · {host.get('gpu','GPU')} {vtotal/GB:.0f}GB · INFERENCE WATCH".upper()
    return {
        "id": HMI_ID,
        "title": "LLM Inference",
        "subtitle": subtitle,
        "channels": channels,
        "notes": notes,
        "header": {
            "STATE": state,
            "VRAM": f"{vratio*100:.0f}%",
            "MODEL": name_disp,
            "POWER": f"{power:.0f}W",
        },
        "state": state,
        "state_sev": state_sev,
    }
