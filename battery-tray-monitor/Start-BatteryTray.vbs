' Double-click entry point for starting the battery tray monitor manually
' with zero visible console window. Prefers pythonw.exe (no console by
' design, same as the scheduled-task autostart in
' Install-BatteryTrayAutostart.ps1) over python.exe, whose console would
' otherwise stay open for as long as the tray app runs.
Dim fso, scriptDir, repoRoot, venvPythonw, pyExe, scriptPath, cmd

Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
repoRoot = fso.GetParentFolderName(scriptDir)
venvPythonw = repoRoot & "\.venv\Scripts\pythonw.exe"
scriptPath = scriptDir & "\battery_tray.py"

If fso.FileExists(venvPythonw) Then
    pyExe = venvPythonw
Else
    pyExe = "pythonw.exe"
End If

cmd = """" & pyExe & """ """ & scriptPath & """"

CreateObject("WScript.Shell").Run cmd, 0, False
