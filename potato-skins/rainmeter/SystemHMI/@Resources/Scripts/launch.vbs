' ====================================================================
'  SystemHMI - launch.vbs
'  Starts the background poller (poll.ps1) completely hidden.
'  Args: [0] = full path to poll.ps1   [1] = full path to data.txt
'  poll.ps1 self-guards with a mutex, so repeated launches are no-ops.
' ====================================================================
Option Explicit
Dim sh, ps1, data, cmd
If WScript.Arguments.Count < 2 Then WScript.Quit
ps1 = WScript.Arguments(0)
data = WScript.Arguments(1)
Set sh = CreateObject("WScript.Shell")
cmd = "powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & ps1 & """ """ & data & """"
sh.Run cmd, 0, False
