' Double-click entry point for starting the battery tray monitor manually
' with zero visible console window. Delegates to Start-BatteryTray.ps1,
' which installs Python/the venv/requirements if needed (same as
' Install-BatteryTrayAutostart.ps1) before launching the app via
' pythonw.exe.
Dim fso, scriptDir, ps1Path, cmd

Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
ps1Path = scriptDir & "\Start-BatteryTray.ps1"

cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & ps1Path & """"

CreateObject("WScript.Shell").Run cmd, 0, False
