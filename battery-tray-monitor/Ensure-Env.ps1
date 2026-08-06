<#
Ensures Python, the battery-tray-monitor virtual environment, and its pip
requirements are all present, installing whatever is missing. Installs
Python via winget if no interpreter is found at all. Outputs the path to
the venv's pythonw.exe on success, for callers to capture.
#>
param(
    [string]$RepoRoot = (Split-Path $PSScriptRoot -Parent)
)

$ErrorActionPreference = "Stop"

function Test-Command($name) {
    return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

function Update-PathFromRegistry {
    $machinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machinePath;$userPath"
}

$venvDir = Join-Path $RepoRoot ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$venvPythonw = Join-Path $venvDir "Scripts\pythonw.exe"
$requirementsPath = Join-Path $PSScriptRoot "requirements.txt"

if (-not (Test-Path $venvPython)) {
    if (-not (Test-Command "python") -and -not (Test-Command "py")) {
        if (-not (Test-Command "winget")) {
            throw "Python isn't installed and winget isn't available to install it. Install Python 3.9+ from https://www.python.org/downloads/ (check 'Add python.exe to PATH'), then re-run this script."
        }
        Write-Host "Python not found, installing via winget..." -ForegroundColor Yellow
        winget install --id Python.Python.3.13 -e --accept-source-agreements --accept-package-agreements
        Update-PathFromRegistry
        if (-not (Test-Command "python") -and -not (Test-Command "py")) {
            throw "Python was installed but isn't on PATH yet. Close and reopen your terminal (or log off/on), then re-run this script."
        }
    }

    $baseCmd = if (Test-Command "python") { "python" } else { "py" }

    Write-Host "Creating virtual environment at $venvDir..." -ForegroundColor Cyan
    & $baseCmd -m venv $venvDir
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create virtual environment at $venvDir"
    }
}

Write-Host "Installing requirements from $requirementsPath..." -ForegroundColor Cyan
& $venvPython -m pip install --quiet --disable-pip-version-check -r $requirementsPath
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install requirements from $requirementsPath"
}

if (-not (Test-Path $venvPythonw)) {
    throw "pythonw.exe not found in venv at $venvPythonw"
}

return $venvPythonw
