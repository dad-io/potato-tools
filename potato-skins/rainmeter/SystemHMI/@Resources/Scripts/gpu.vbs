' ====================================================================
'  SystemHMI - gpu.vbs
'  Runs nvidia-smi completely hidden (no console flash) and writes a
'  one-line CSV to the file given as the first argument:
'     temperature.gpu, utilization.gpu, memory.used, memory.total, power.draw
'  Called by Rainmeter on a timer; one-shot, self-terminating.
' ====================================================================
Option Explicit
Dim sh, outFile, cmd
If WScript.Arguments.Count < 1 Then WScript.Quit
outFile = WScript.Arguments(0)
Set sh = CreateObject("WScript.Shell")
cmd = "cmd /c nvidia-smi --query-gpu=temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw --format=csv,noheader,nounits > """ & outFile & """"
' 0 = hidden window, True = wait so the file is fully written before exit
sh.Run cmd, 0, True
