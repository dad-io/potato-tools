; =====================================================================
;  SystemHMI  -  Variables / Theme
;  Theme: Dark + Cyan (SCADA)   |   Target: 1080p right-edge strip
;  Edit values here to re-theme the whole panel.
; =====================================================================

[Variables]
; ---------- PALETTE (hex RRGGBB or RRGGBBAA) ----------
Bg=0E1116F2
PanelEdge=29E0D855
Track=1C232CFF
Accent=29E0D8FF
AccentDim=29E0D899
Text=E8EDF2FF
Dim=7A8694FF
OK=35E08AFF
Warn=FFB020FF
Crit=FF4D4DFF

; ---------- LAYOUT ----------
PanelW=190
Pad=14
Inner=162
BarH=7
Gap=10
; panel heights: collapsed (default) and expanded (hover)
PanelH=930
PanelHcmp=742
PanelHExp=930

; ---------- FONTS (system fonts, no install needed) ----------
FontMain=Segoe UI
FontMono=Consolas

; ---------- ALARM THRESHOLDS ----------
CpuWarn=60
CpuCrit=85
CpuTWarn=75
CpuTCrit=88
RamWarn=70
RamCrit=88
GpuWarn=70
GpuCrit=90
GpuTWarn=72
GpuTCrit=83
DiskWarn=85
DiskCrit=93

; ---------- GPU POLLER ----------
GpuFile=#@#gpu.txt
GpuScript=#@#Scripts\gpu.vbs
; (full data poller kept for later features)
DataFile=#@#data.txt
Poller=#@#Scripts\poll.ps1
Launcher=#@#Scripts\launch.vbs

; ---------- STATE ----------
Expanded=0
