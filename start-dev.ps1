param (
    [switch]$Headless
)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "Starting backend (FastAPI)..." -ForegroundColor Cyan
$backendScript = "cd `"$root\backend`"; uv run uvicorn app.main:app --reload --port 8866"

Write-Host "Starting frontend (Vite)..." -ForegroundColor Cyan
$frontendScript = "cd `"$root\frontend`"; npm run dev"

if ($Headless) {
    $backendJob = Start-Job -ScriptBlock { param($cmd) powershell -NoProfile -Command $cmd } -ArgumentList $backendScript
    $frontendJob = Start-Job -ScriptBlock { param($cmd) powershell -NoProfile -Command $cmd } -ArgumentList $frontendScript

    Write-Host "Jobs launched. Use 'Receive-Job -Id $($backendJob.Id)' to see output."
    Wait-Job -Job $backendJob, $frontendJob
} else {
    Start-Process pwsh -ArgumentList "-NoExit", "-Command", $backendScript -WindowStyle Normal -WorkingDirectory "$root\backend" -Verb RunAs:$false
    Start-Process pwsh -ArgumentList "-NoExit", "-Command", $frontendScript -WindowStyle Normal -WorkingDirectory "$root\frontend" -Verb RunAs:$false
    Write-Host "Both servers launched in new PowerShell windows."
}

