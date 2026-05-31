# Tater Eye Wallpaper

A live desktop wallpaper that renders system-monitoring panels *behind* your icons — the numbers are always there, judging you, but politely, from the back.

Built for one 2560×1080 ultrawide (Ryzen 3700X + RTX 5070). Two panels ship:

- **LLM Inference** — LM Studio on the RTX 5070: VRAM ceiling, model footprint, prefill/decode phase, memory-bandwidth saturation, CPU-offload spill, thermal/power throttle.
- **System Health** — CPU (load + per-core + Core Temp), memory, GPU, storage, network — with diagnostics that connect the dots (*hot while idle = cooling fault*).

## How it works

`HudWallpaper.exe` (C# / GDI+) parents a native paint surface to the desktop's WorkerW — behind the icons — and supervises a small Python server (`server.py`, stdlib HTTP + two sampler threads). The server serves `/data`; the host paints it natively — **≈0 VRAM, GPU idles between updates** (we started on WebView2 and ditched it: ~420 MB RAM + 144 MB VRAM of Chromium, on the very GPU the LLM panel is trying to watch). The same `/data` also renders in a browser via `web/` for quick previewing.

## Requires (all already on this box)

- Python 3.12 + `psutil` (+ `nvidia-ml-py`, optional — in-process NVML instead of spawning `nvidia-smi`). Run `.\setup.ps1`.
- NVIDIA driver (`nvidia-smi` on PATH)
- .NET 9 SDK (to build/host)
- Core Temp (optional — per-core temps) · LM Studio (optional — richer LLM stats)

## Usage

```powershell
.\setup.ps1            # one-time: install python deps (psutil, nvidia-ml-py)
.\run-dev.ps1          # dashboard in a browser, no wallpaper layer
.\run-wallpaper.ps1    # the real thing (builds the host on first run)
.\stop.ps1             # make it stop
.\install-startup.ps1  # start at logon, forever, like a mortgage
```

Host log: `%TEMP%\hudwallpaper.log`.

## Adding a panel

Pure Python: drop a `server/hmi_<name>.py` with `build(snap) -> dict`, import it in `server.py`, append it to `State.render()`. The renderer lays out any number of panels in a grid — it draws whatever channels/notes come back in `/data`. No C#, no recompiling.

## Gotchas (handled — just so you know)

- Per-process VRAM comes from Windows PDH counters; `nvidia-smi` returns `N/A` per-process on consumer GPUs.
- LLM KV-cache / footprint numbers are **estimates** (labelled `est`).
- No split WorkerW? It parents to Progman and renders behind the icons anyway.
