# run_bot.ps1
param(
    [string]$RepoPath = "C:\Users\marcn\Desktop\LRE-Pomobot-main"
)
$ErrorActionPreference = 'Stop'
$activate = Join-Path $RepoPath 'venv\Scripts\Activate.ps1'

while ($true) {
    Write-Host "[$(Get-Date)] → Pull origin main…" -ForegroundColor Cyan
    Set-Location $RepoPath
    git pull origin main

    Write-Host "[$(Get-Date)] → Activation du venv…" -ForegroundColor Cyan
    . $activate

    Write-Host "[$(Get-Date)] → Démarrage de bot.py…" -ForegroundColor Green
    python .\bot.py

    Write-Host "[$(Get-Date)] → Bot arrêté, relance dans 5 s…" -ForegroundColor Yellow
    Start-Sleep -Seconds 5
}
