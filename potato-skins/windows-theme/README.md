# Fibb Crystal Dark for Windows 11

Windows dressed in Fibb's dark design: "Crystal Dark" (Graphite + Instrument Blue), the default dark theme in
`fibbonacci-ui/src/data/designTokens.ts`.

```powershell
.\apply.ps1
```

| Part | How | Fibb token |
|---|---|---|
| Apps + system | Dark mode | — |
| Accent, active title bars + borders, Start | `Fibb Crystal Dark.theme` + DWM `ColorPrevalence` | primary `#a2cde2` |
| Inactive title bars | DWM `AccentColorInactive` | panel `#26323c` |
| Taskbar | TranslucentTB (`../taskbar`): clear on the desktop, acrylic with windows open | chassis `#141b21` |
| Wallpaper | Webb, young stars in Orion (`../wallpapers`) | — |
| Desktop panel | Rainmeter `SystemHMI/PanelNUC.ini` + `@Resources/Themes/FibbCrystalDark.inc` | full palette |

Apps that draw their own title bar (Chrome, VS Code, the Claude app) keep their own colours.

**Undo:** Settings > Personalization > Themes > Windows (dark); turn off "Show accent colour on title bars and window
borders" under Personalization > Colours.
