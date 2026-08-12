param(
    [ValidateSet("up", "down", "status")]
    [string]$Action = "up"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$RuntimeDir = Join-Path $ProjectRoot ".runtime\dev"
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Arq = Join-Path $ProjectRoot ".venv\Scripts\arq.exe"
$Npm = "npm.cmd"

function Stop-RecordedProcess([string]$Name) {
    $PidFile = Join-Path $RuntimeDir "$Name.pid"
    if (-not (Test-Path -LiteralPath $PidFile)) { return }
    $RecordedPid = [int](Get-Content -LiteralPath $PidFile)
    $Process = Get-Process -Id $RecordedPid -ErrorAction SilentlyContinue
    if ($Process) { Stop-Process -Id $RecordedPid -Force }
    Remove-Item -LiteralPath $PidFile -Force
}

function Invoke-Checked([scriptblock]$Command, [string]$FailureMessage) {
    & $Command
    if ($LASTEXITCODE -ne 0) { throw $FailureMessage }
}

if ($Action -eq "down") {
    Stop-RecordedProcess "api"
    Stop-RecordedProcess "worker"
    Stop-RecordedProcess "web"
    if (Get-Command docker -ErrorAction SilentlyContinue) {
        docker compose -f (Join-Path $ProjectRoot "deploy\docker-compose.local.yml") down
    }
    Write-Host "Local services stopped."
    exit 0
}

if ($Action -eq "status") {
    foreach ($Name in @("api", "worker", "web")) {
        $PidFile = Join-Path $RuntimeDir "$Name.pid"
        if (Test-Path -LiteralPath $PidFile) {
            $RecordedPid = [int](Get-Content -LiteralPath $PidFile)
            $Running = Get-Process -Id $RecordedPid -ErrorAction SilentlyContinue
            Write-Host "$Name`t$([bool]$Running)`tPID=$RecordedPid"
        } else {
            Write-Host "$Name`tFalse"
        }
    }
    exit 0
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker was not found. Install and start Docker Desktop, then retry."
}
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Missing .venv. Install Python dependencies first."
}

New-Item -ItemType Directory -Path $RuntimeDir -Force | Out-Null
$ComposeFile = Join-Path $ProjectRoot "deploy\docker-compose.local.yml"
Invoke-Checked { docker compose -f $ComposeFile up -d --wait } "PostgreSQL or Redis did not become healthy."
Invoke-Checked { & $Python -m alembic upgrade head } "Database migration failed."
Invoke-Checked { & $Python -m scripts.seed_sample_pack } "Sample-pack import failed."
Invoke-Checked { & $Python -m scripts.import_industry_dataset } "Industry dataset import failed."

$Api = Start-Process -FilePath $Python -ArgumentList @("-m", "uvicorn", "app.api.main:app", "--host", "127.0.0.1", "--port", "8000") -WorkingDirectory $ProjectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $RuntimeDir "api.log") -RedirectStandardError (Join-Path $RuntimeDir "api-error.log") -PassThru
$Worker = Start-Process -FilePath $Arq -ArgumentList @("app.workers.settings.WorkerSettings") -WorkingDirectory $ProjectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $RuntimeDir "worker.log") -RedirectStandardError (Join-Path $RuntimeDir "worker-error.log") -PassThru
$Web = Start-Process -FilePath $Npm -ArgumentList @("run", "dev", "--", "--host", "127.0.0.1") -WorkingDirectory (Join-Path $ProjectRoot "web") -WindowStyle Hidden -RedirectStandardOutput (Join-Path $RuntimeDir "web.log") -RedirectStandardError (Join-Path $RuntimeDir "web-error.log") -PassThru
$Api.Id | Set-Content (Join-Path $RuntimeDir "api.pid")
$Worker.Id | Set-Content (Join-Path $RuntimeDir "worker.pid")
$Web.Id | Set-Content (Join-Path $RuntimeDir "web.pid")
Write-Host "Started: http://127.0.0.1:5173 (logs: .runtime/dev/)"
