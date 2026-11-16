# Clear taskbar

A fully transparent taskbar via [TranslucentTB](https://github.com/TranslucentTB/TranslucentTB), on the desktop and with windows open.

```powershell
.\install.ps1   # winget install + drop settings.json in place + (re)start TranslucentTB
```

`settings.json` is TranslucentTB's own config file; it lives at
`%LOCALAPPDATA%\Packages\28017CharlesMilette.TranslucentTB_v826wp6bftszj\RoamingState\settings.json`.
Tweak it from the tray icon afterwards — TranslucentTB writes changes back to that file, so copy it here to keep them.
