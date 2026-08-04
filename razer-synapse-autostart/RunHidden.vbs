' Launches RazerSynapseWatcher.ps1 with zero visible window.
' wscript.exe has no console of its own, and WshShell.Run with windowStyle 0
' suppresses the child PowerShell console too -- unlike "powershell -WindowStyle
' Hidden" run directly from Task Scheduler, which can still flash a console
' window briefly before the flag takes effect.
Dim fso, scriptDir, psPath, cmd

Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
psPath = scriptDir & "\RazerSynapseWatcher.ps1"

cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & psPath & """"

CreateObject("WScript.Shell").Run cmd, 0, False
