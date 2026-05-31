# 🥔 Potato Peeler

Peels the lid off the machine and tells you what's actually in there. A re-runnable, **read-only** hardware + OS auditor: severity-coded findings and recommendations, every run.

- **`Potato-Audit.ps1`** — the auditor. A rules engine over live Windows telemetry.
- **`Potato-Audit.cmd`** — double-click launcher (no right-click ritual).
- **`reports\`** — generated `audit-*.html` (open anywhere) + `audit-*.json` (diff over time).

## Run it

```powershell
# easiest: double-click Potato-Audit.cmd   (read-only; opens the HTML report)
powershell -NoProfile -ExecutionPolicy Bypass -File ".\Potato-Audit.ps1"

.\Potato-Audit.ps1 -NoHtml -NoJson   # console only
.\Potato-Audit.ps1 -Quiet            # don't auto-open the browser
.\Potato-Audit.ps1 -Fix              # hand off to ..\potato-launcher\tune.ps1 (elevates)
```

It reads **live** state, so re-run it after any change to see the box as it is right now. Keep the JSON snapshots to diff over time.

## Why it's built this way

- **Windows PowerShell 5.1** — in-box on every Win10/11 since 2016. No installs, no modules, no internet.
- **`Get-CimInstance` only** — modern, stable, runs in both PowerShell 5.1 and 7.
- **Every probe guarded** — a missing cmdlet/namespace degrades gracefully; one failure never kills the report.

Tuning lives next door in [`../potato-launcher`](../potato-launcher); `-Fix` just calls it.
