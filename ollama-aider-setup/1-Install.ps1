# 1-Install.ps1
# Installs everything needed to run a local LLM with Ollama + Aider.
# You only need to run this script once, during initial setup.

param(
    [string]$Model = "qwen2.5-coder:7b"
)

$ErrorActionPreference = "Stop"

function Test-Command($name) {
    return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

Write-Host "=== 1) Checking Ollama ===" -ForegroundColor Cyan
if (-not (Test-Command "ollama")) {
    if (-not (Test-Command "winget")) {
        Write-Host "winget not found. Download and install Ollama manually from https://ollama.com/download." -ForegroundColor Red
        exit 1
    }
    Write-Host "Ollama not found, installing via winget..." -ForegroundColor Yellow
    winget install --id Ollama.Ollama -e --accept-source-agreements --accept-package-agreements
    Write-Host "Install complete. Waiting a few seconds for the Ollama service to start..." -ForegroundColor Yellow
    Start-Sleep -Seconds 5
} else {
    Write-Host "Ollama is already installed." -ForegroundColor Green
}

Write-Host ""
Write-Host "=== 2) Checking Python / pip ===" -ForegroundColor Cyan
if (-not (Test-Command "python") -and -not (Test-Command "py")) {
    if (-not (Test-Command "winget")) {
        Write-Host "Python not found and winget isn't available. Install Python 3.10+ from https://www.python.org/downloads/ and re-run this script." -ForegroundColor Red
        exit 1
    }
    Write-Host "Python not found, installing via winget..." -ForegroundColor Yellow
    winget install --id Python.Python.3.13 -e --accept-source-agreements --accept-package-agreements

    $machinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machinePath;$userPath"

    if (-not (Test-Command "python") -and -not (Test-Command "py")) {
        Write-Host "Python was installed but isn't on PATH yet. Close and reopen your terminal (or log off/on), then re-run this script." -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "Python is already installed." -ForegroundColor Green
}

Write-Host ""
Write-Host "=== 3) Installing Aider (pip) ===" -ForegroundColor Cyan
if (Test-Command "python") {
    python -m pip install --upgrade pip
    python -m pip install -U aider-chat
} else {
    py -m pip install --upgrade pip
    py -m pip install -U aider-chat
}

Write-Host ""
Write-Host "=== 4) Pulling model: $Model ===" -ForegroundColor Cyan
Write-Host "(This can take a while depending on model size and requires an internet connection.)" -ForegroundColor Yellow
ollama pull $Model

Write-Host ""
Write-Host "=== Setup complete ===" -ForegroundColor Green
Write-Host "You can now start Aider by running 2-Run-Aider.ps1 in the same folder." -ForegroundColor Green
Write-Host "Example: .\2-Run-Aider.ps1 -Model `"$Model`" -ProjectPath `"C:\my-projects\project1`"" -ForegroundColor Green
