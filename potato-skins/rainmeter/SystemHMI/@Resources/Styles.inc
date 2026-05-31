; =====================================================================
;  SystemHMI  -  Meter Styles
; =====================================================================

; ---- Section label (small, dim, uppercase look) ----
[sLabel]
FontFace=#FontMain#
FontSize=8
FontColor=#Dim#
StringStyle=Bold
StringCase=Upper
AntiAlias=1
X=#Pad#

; ---- Big primary readout (right-aligned mono) ----
[sBig]
FontFace=#FontMono#
FontSize=21
FontColor=#Text#
StringStyle=Bold
StringAlign=Right
AntiAlias=1
X=(#PanelW#-#Pad#)

; ---- Medium readout ----
[sMed]
FontFace=#FontMono#
FontSize=12
FontColor=#Text#
StringAlign=Right
AntiAlias=1
X=(#PanelW#-#Pad#)

; ---- Small detail text (left) ----
[sSmall]
FontFace=#FontMono#
FontSize=9
FontColor=#Dim#
AntiAlias=1
X=#Pad#

; ---- Small detail text (right) ----
[sSmallR]
FontFace=#FontMono#
FontSize=9
FontColor=#Dim#
StringAlign=Right
AntiAlias=1
X=(#PanelW#-#Pad#)

; ---- Horizontal alarm bar ----
[sBar]
Meter=Bar
BarColor=#Accent#
BarOrientation=Horizontal
SolidColor=#Track#
X=#Pad#
W=#Inner#
H=#BarH#

; ---- Thin section divider ----
[sDivider]
Meter=Image
SolidColor=#PanelEdge#
X=#Pad#
W=#Inner#
H=1
