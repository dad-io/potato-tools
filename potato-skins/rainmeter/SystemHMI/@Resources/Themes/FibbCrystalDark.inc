; =====================================================================
;  SystemHMI theme - Fibb "Crystal Dark" (Graphite + Instrument Blue)
;  Source of truth: fibbonacci-ui/src/data/designTokens.ts, theme "crystal-dark".
;  Included AFTER Variables.inc, so these override the SCADA palette.
; =====================================================================

[Variables]
; plate = porcelain #202a32 (95% opaque), edge = divider #46545f, track = chassis #141b21
Bg=202A32F2
PanelEdge=46545FFF
Track=141B21FF
; primary (Instrument Blue) #a2cde2; dim fill at 60%
Accent=A2CDE2FF
AccentDim=A2CDE299
; ink #edf3f6 / inkSecondary #b6c5ce
Text=EDF3F6FF
Dim=B6C5CEFF
; state: success #91d4ad, warning #e6ca8b, error #ffb4b0
OK=91D4ADFF
Warn=E6CA8BFF
Crit=FFB4B0FF
; secondary (teal) #8ed2ca, used for the second trend line
Accent2=8ED2CAFF
; DESIGN_SCALE.radius.outer
Radius=12
FontMain=Segoe UI
FontMono=Consolas
