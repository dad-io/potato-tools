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
