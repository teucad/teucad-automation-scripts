# 2-Run-Aider.ps1
# Starts Aider against a model already running in Ollama.
# You must have already run 1-Install.ps1.

param(
    [string]$Model = "",
    [string]$ProjectPath = "",
    [string]$OllamaApiBase = "http://localhost:11434"
)

$ErrorActionPreference = "Stop"

function Test-Command($name) {
    return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

if (-not (Test-Command "ollama")) {
    Write-Host "Ollama not found. Run 1-Install.ps1 first." -ForegroundColor Red
    exit 1
}

if (-not (Test-Command "aider")) {
    Write-Host "Aider not found. Run 1-Install.ps1 first." -ForegroundColor Red
    exit 1
}

Write-Host "=== Checking Ollama service ===" -ForegroundColor Cyan
$ollamaRunning = $false
try {
    $response = Invoke-WebRequest -Uri "$OllamaApiBase/api/tags" -UseBasicParsing -TimeoutSec 3
    if ($response.StatusCode -eq 200) { $ollamaRunning = $true }
} catch {
    $ollamaRunning = $false
}

if (-not $ollamaRunning) {
    Write-Host "Ollama service isn't running, starting it in the background..." -ForegroundColor Yellow
    Start-Process "ollama" -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 5
} else {
    Write-Host "Ollama service is running." -ForegroundColor Green
}

$env:OLLAMA_API_BASE = $OllamaApiBase

if ([string]::IsNullOrWhiteSpace($Model)) {
    $rawList = ollama list | Select-Object -Skip 1 | Where-Object { $_.Trim() -ne "" }
    $modelNames = @($rawList | ForEach-Object { ($_ -split '\s+')[0] })

    if ($modelNames.Count -eq 0) {
        Write-Host "No installed models found. Pull one first with 'ollama pull <model-name>'." -ForegroundColor Red
        exit 1
    }

    Write-Host ""
    Write-Host "=== Installed Ollama models ===" -ForegroundColor Cyan
    for ($i = 0; $i -lt $modelNames.Count; $i++) {
        Write-Host "$($i + 1). $($modelNames[$i])"
    }
    Write-Host ""

    $selection = Read-Host "Enter the number of the model you want to use"
    $selectionIndex = 0
    if (-not [int]::TryParse($selection, [ref]$selectionIndex) -or $selectionIndex -lt 1 -or $selectionIndex -gt $modelNames.Count) {
        Write-Host "Invalid selection: $selection" -ForegroundColor Red
        exit 1
    }
    $Model = $modelNames[$selectionIndex - 1]
}

if ([string]::IsNullOrWhiteSpace($ProjectPath)) {
    Write-Host ""
    $inputPath = Read-Host "Enter the project folder path (press Enter to use the current directory: $((Get-Location).Path))"
    if ([string]::IsNullOrWhiteSpace($inputPath)) {
        $ProjectPath = (Get-Location).Path
    } else {
        $ProjectPath = $inputPath
    }
}

if (-not (Test-Path $ProjectPath -PathType Container)) {
    Write-Host "Folder not found: $ProjectPath" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=== Starting Aider ===" -ForegroundColor Cyan
Write-Host "Model       : ollama/$Model" -ForegroundColor Green
Write-Host "Project path: $ProjectPath" -ForegroundColor Green
Write-Host ""

Set-Location $ProjectPath
aider --model "ollama/$Model"
