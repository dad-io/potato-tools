# 🥔 Potato Launcher

The tuning + upgrade kit. Turns the rig into something that can eat potatoes for every meal — twice, and three times on Tuesdays.

**`tune.ps1`** — one reversible Windows tuning pass. Run elevated. Backs everything up to a timestamped folder first; we're reckless, not stupid.

## What it changes

1. **Pagefile** → fixed 8–32 GB on C: (was 2.6 GB — a crash waiting for a Docker/LLM excuse). *Reboot.*
2. **Fast Startup** → off (clean cold boots; required before a BIOS flash). *Reboot.*
3. **Autostarts** → Steam / Epic / EA / Docker / LM Studio off. Launch them yourself; you have hands.
4. **Ultimate Performance** power plan → on.
5. **Bloat purge** → ~12 stock UWP apps (Bing, Solitaire, 3D Viewer, Skype, Zune, YourPhone…). Xbox / Game Bar spared.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File ".\tune.ps1"   # or right-click > Run with PowerShell
```

## Undo

Backups land in `…\Documents\pc-tune\backup-<timestamp>\`. Re-enable autostarts via Task Manager → Startup. Pagefile: System Properties → Advanced → Performance → Virtual Memory → "Automatically manage".

## Upgrade path (AM4 — no new platform needed)

| # | Move | Why |
|---|---|---|
| 1 | **Ethernet cable** | Free. Retires the sad AC 3168 Wi-Fi (~175 Mbps). Biggest real-world win. |
| 2 | **Ryzen 7 5700X3D** (~$200) | Drop-in on B450. Frees the CPU-starved RTX 5070. **Flash BIOS first** while the 3700X is installed (P1.50 won't boot 5000-series). |
| 3 | **32 GB DDR4-3600 CL16** | Double + faster RAM; enable XMP/DOCP. X3D loves fast memory. |
| 4 | **1440p 144 Hz+ monitor** | 2560×1080 @ 60 Hz throws away most of the GPU's frames. |
| 5 | Consolidate SSDs, retire the ~12yo 840 EVO, enable ReBAR, move to Win11 | Cleanup + free performance. |

**Don't bother:** new motherboard / AM5 / DDR5 / a bigger GPU. Fix the feeding tube first.
