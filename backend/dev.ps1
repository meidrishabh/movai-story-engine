# Starts the API and the job runner, each in its own window.
# Run from anywhere:  powershell -File C:\MovAi\backend\dev.ps1
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$activate = Join-Path $here ".venv\Scripts\Activate.ps1"
$prefix = ""
if (Test-Path $activate) { $prefix = "& '$activate'; " }

Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$here'; $prefix uvicorn app.main:app --reload"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$here'; $prefix python -m app.workers.job_runner"

Write-Host "API:    http://127.0.0.1:8000/ui/"
Write-Host "Review: http://127.0.0.1:8000/ui/review.html"
Write-Host "Close the two windows to stop."
