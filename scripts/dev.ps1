param(
    [ValidateSet("up", "down", "status")]
    [string]$Action = "up"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$RuntimeDir = Join-Path $ProjectRoot ".runtime\dev"
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Vite = Join-Path $ProjectRoot "web\node_modules\vite\bin\vite.js"
$NodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
$Node = if ($NodeCommand) { $NodeCommand.Source } else { $null }
$DockerComposeCommand = Get-Command docker-compose.exe -ErrorAction SilentlyContinue
$DockerCompose = if ($DockerComposeCommand) { $DockerComposeCommand.Source } else { $null }

# Every relative path used by Alembic, pydantic-settings and the helper modules
# is repository-relative.  Make the entry point independent of the caller's
# current directory so `& E:\...\scripts\dev.ps1 up` behaves exactly like the
# documented `cd <repo>; .\scripts\dev.ps1 up` workflow.
Set-Location -LiteralPath $ProjectRoot

function Stop-RecordedProcess([string]$Name) {
    $PidFile = Join-Path $RuntimeDir "$Name.pid"
    if (-not (Test-Path -LiteralPath $PidFile)) { return }

    $RecordedPid = [int](Get-Content -LiteralPath $PidFile)
    if ($RecordedPid -le 0) {
        Remove-Item -LiteralPath $PidFile -Force
        return
    }

    $Process = Get-Process -Id $RecordedPid -ErrorAction SilentlyContinue
    if ($Process) {
        try {
            # A Windows venv launcher may start the base interpreter as a child.
            # Stop descendants first so API and worker processes cannot be orphaned.
            $Descendants = @()
            $Frontier = @($RecordedPid)
            while ($Frontier.Count -gt 0) {
                $Next = @()
                foreach ($ParentPid in $Frontier) {
                    $Children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$ParentPid" `
                        -ErrorAction SilentlyContinue
                    foreach ($Child in $Children) {
                        $Descendants += [int]$Child.ProcessId
                        $Next += [int]$Child.ProcessId
                    }
                }
                $Frontier = $Next
            }
            foreach ($ChildPid in ($Descendants | Select-Object -Unique | Sort-Object -Descending)) {
                Stop-Process -Id $ChildPid -Force -ErrorAction SilentlyContinue
            }
            Stop-Process -Id $RecordedPid -Force
        } catch {
            throw "Cannot stop $Name (PID=$RecordedPid). Run this script from the same privilege level that started it, then retry."
        }
    }
    Remove-Item -LiteralPath $PidFile -Force
}

function Invoke-Checked([scriptblock]$Command, [string]$FailureMessage) {
    & $Command
    if ($LASTEXITCODE -ne 0) { throw $FailureMessage }
}

function Test-LocalPort([int]$Port) {
    $Client = [System.Net.Sockets.TcpClient]::new()
    try {
        $Connect = $Client.ConnectAsync("127.0.0.1", $Port)
        return $Connect.Wait(500) -and $Client.Connected
    } catch {
        return $false
    } finally {
        $Client.Dispose()
    }
}

function Test-DependencyPorts([bool]$ExpectedReachable) {
    $States = @(5432, 6379, 9000 | ForEach-Object { Test-LocalPort $_ })
    if ($ExpectedReachable) { return -not ($States -contains $false) }
    return -not ($States -contains $true)
}

function Stop-ProcessTree([int]$RootPid) {
    $Descendants = @()
    $Frontier = @($RootPid)
    while ($Frontier.Count -gt 0) {
        $Next = @()
        foreach ($ParentPid in $Frontier) {
            $Children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$ParentPid" `
                -ErrorAction SilentlyContinue
            foreach ($Child in $Children) {
                $Descendants += [int]$Child.ProcessId
                $Next += [int]$Child.ProcessId
            }
        }
        $Frontier = $Next
    }
    foreach ($ChildPid in ($Descendants | Select-Object -Unique | Sort-Object -Descending)) {
        Stop-Process -Id $ChildPid -Force -ErrorAction SilentlyContinue
    }
    Stop-Process -Id $RootPid -Force -ErrorAction SilentlyContinue
}

function Wait-ComposeProcess(
    [System.Diagnostics.Process]$Process,
    [bool]$PortsShouldBeReachable,
    [int]$TimeoutMilliseconds
) {
    $Deadline = (Get-Date).AddMilliseconds($TimeoutMilliseconds)
    $ExitedAt = $null
    do {
        if (Test-DependencyPorts $PortsShouldBeReachable) {
            # Compose on Docker Desktop for Windows can finish the operation but
            # leave its CLI process waiting on a dead IPC handle. Give it a short
            # grace period, then clean up only that command tree.
            if (-not $Process.HasExited -and -not $Process.WaitForExit(5000)) {
                Stop-ProcessTree $Process.Id
            }
            return $true
        }
        if ($Process.HasExited) {
            if ($null -eq $ExitedAt) { $ExitedAt = Get-Date }
            # Start-Process can expose a null/stale ExitCode on Windows when
            # stdout/stderr are redirected. The requested port state is the
            # acceptance condition; allow it a short propagation grace period.
            if ((Get-Date) -gt $ExitedAt.AddSeconds(10)) { return $false }
        }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $Deadline)
    Stop-ProcessTree $Process.Id
    return $false
}

function Wait-HttpReady([string]$Url, [int]$TimeoutSeconds, [string]$ProcessName) {
    $Deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        $PidFile = Join-Path $RuntimeDir "$ProcessName.pid"
        if (Test-Path -LiteralPath $PidFile) {
            $RecordedPid = [int](Get-Content -LiteralPath $PidFile)
            if ($RecordedPid -gt 0 -and -not (Get-Process -Id $RecordedPid -ErrorAction SilentlyContinue)) {
                throw "$ProcessName exited before becoming ready."
            }
        }
        try {
            $Response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
            if ($Response.StatusCode -ge 200 -and $Response.StatusCode -lt 300) { return }
        } catch {
            # The service may still be booting; retry until the bounded deadline.
        }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $Deadline)
    throw "$ProcessName did not become ready within $TimeoutSeconds seconds: $Url"
}

function Show-RecentErrors {
    foreach ($Service in @("api", "worker", "web")) {
        $LogFile = Get-ChildItem -LiteralPath $RuntimeDir -Filter "$Service-error-*.log" `
            -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($LogFile) {
            Write-Host "[$($LogFile.Name)]"
            Get-Content -LiteralPath $LogFile.FullName -Tail 20
        }
    }
}

function Stop-LocalContainers {
    if (-not $DockerCompose) { return }
    $ComposeFile = Join-Path $ProjectRoot "deploy\docker-compose.local.yml"
    $Stdout = Join-Path $RuntimeDir "docker-down.log"
    $Stderr = Join-Path $RuntimeDir "docker-down-error.log"
    $Docker = Start-Process -FilePath $DockerCompose -ArgumentList @(
        "-f", ('"' + $ComposeFile + '"'), "down"
    ) -WorkingDirectory $ProjectRoot -WindowStyle Hidden -RedirectStandardOutput $Stdout `
        -RedirectStandardError $Stderr -PassThru
    if (-not (Wait-ComposeProcess $Docker $false 30000)) {
        Write-Warning "Docker compose down timed out after 30 seconds; API, worker and web are stopped, but PostgreSQL/Redis containers may still be running."
        return
    }
}

function Start-LocalContainers {
    $ComposeFile = Join-Path $ProjectRoot "deploy\docker-compose.local.yml"
    $Stdout = Join-Path $RuntimeDir "docker-up.log"
    $Stderr = Join-Path $RuntimeDir "docker-up-error.log"
    $Docker = Start-Process -FilePath $DockerCompose -ArgumentList @(
        "-f", ('"' + $ComposeFile + '"'), "up", "-d"
    ) -WorkingDirectory $ProjectRoot -WindowStyle Hidden -RedirectStandardOutput $Stdout `
        -RedirectStandardError $Stderr -PassThru
    if (-not (Wait-ComposeProcess $Docker $true 180000)) {
        throw "Docker compose up timed out after 180 seconds; inspect .runtime/dev/docker-up-error.log."
    }
}

if ($Action -eq "down") {
    Stop-RecordedProcess "api"
    Stop-RecordedProcess "worker"
    Stop-RecordedProcess "web"
    Stop-LocalContainers
    Write-Host "Local services stopped."
    exit 0
}

if ($Action -eq "status") {
    foreach ($Name in @("api", "worker", "web")) {
        $PidFile = Join-Path $RuntimeDir "$Name.pid"
        if (Test-Path -LiteralPath $PidFile) {
            $RecordedPid = [int](Get-Content -LiteralPath $PidFile)
            $Running = if ($RecordedPid -gt 0) { Get-Process -Id $RecordedPid -ErrorAction SilentlyContinue } else { $null }
            Write-Host "$Name`t$([bool]$Running)`tPID=$RecordedPid"
        } else {
            Write-Host "$Name`tFalse"
        }
    }
    try {
        $Ready = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health/ready" -TimeoutSec 2
        Write-Host "readiness`t$($Ready.status)`tdatabase=$($Ready.database.ready) redis=$($Ready.queue.ready) worker=$($Ready.worker.ready) object_store=$($Ready.object_store.ready)"
    } catch {
        Write-Host "readiness`tFalse"
    }
    exit 0
}

if (-not $DockerCompose) {
    throw "docker-compose.exe was not found. Install and start Docker Desktop, then retry."
}
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Missing .venv. Install Python dependencies first."
}
if (-not $Node -or -not (Test-Path -LiteralPath $Vite)) {
    throw "Missing Node.js or web dependencies. Run npm install in web first."
}

New-Item -ItemType Directory -Path $RuntimeDir -Force | Out-Null
$null = Stop-RecordedProcess "api"
$null = Stop-RecordedProcess "worker"
$null = Stop-RecordedProcess "web"
$RunId = Get-Date -Format "yyyyMMdd-HHmmss-fff"
# Reuse reachable PostgreSQL, Redis and MinIO services. Migrations and /health/ready
# still validate the actual dependencies before the script reports success.
$PortsReachable = Test-DependencyPorts $true
if ($PortsReachable) {
    # P1 requires the pgvector extension binaries.  A healthy old postgres:16
    # container is still the wrong environment and must be recreated by Compose
    # (the named data volume is preserved).
    & $Python -c 'import psycopg; from app.core.config import settings; c=psycopg.connect(settings.database_url.replace("+psycopg", ""), connect_timeout=2); row=c.execute("select extversion from pg_extension where extname=''vector''").fetchone(); c.close(); raise SystemExit(0 if row and row[0]=="0.8.6" else 1)'
    if ($LASTEXITCODE -ne 0) {
        $PortsReachable = $false
    }
}
if ($PortsReachable) {
    Write-Host "PostgreSQL, Redis and MinIO ports are reachable; reusing existing services."
} else {
    Start-LocalContainers
}
Invoke-Checked { & $Python -m alembic upgrade head } "Database migration failed."
Invoke-Checked {
    & $Python -c "from app.core.config import settings; from app.services.object_store import S3ObjectStore; S3ObjectStore(settings).ensure_bucket()"
} "Could not provision the versioned MinIO bucket."

# Import sample data only for an empty database. Explicit import commands remain
# available when a developer intentionally wants to rebuild the sample set.
$SeedCount = [int](& $Python -c "from app.db.session import engine; from sqlalchemy import text; c=engine.connect(); print(c.execute(text('select (select count(*) from security) + (select count(*) from document) + (select count(*) from thesis)')).scalar() or 0); c.close()")
if ($LASTEXITCODE -ne 0) { throw "Could not inspect database seed state." }
if ($SeedCount -eq 0) {
    Invoke-Checked { & $Python -m scripts.seed_sample_pack } "Sample-pack import failed."
    Invoke-Checked { & $Python -m scripts.import_industry_dataset } "Industry dataset import failed."
} else {
    Write-Host "Existing research data found; skipping sample and industry imports."
}

try {
    $Api = Start-Process -FilePath $Python -ArgumentList @("-m", "uvicorn", "app.api.main:app", "--host", "127.0.0.1", "--port", "8000") -WorkingDirectory $ProjectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $RuntimeDir "api-$RunId.log") -RedirectStandardError (Join-Path $RuntimeDir "api-error-$RunId.log") -PassThru
    $Api.Id | Set-Content (Join-Path $RuntimeDir "api.pid")

    $Worker = Start-Process -FilePath $Python -ArgumentList @("-m", "arq", "app.workers.settings.WorkerSettings") -WorkingDirectory $ProjectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $RuntimeDir "worker-$RunId.log") -RedirectStandardError (Join-Path $RuntimeDir "worker-error-$RunId.log") -PassThru
    $Worker.Id | Set-Content (Join-Path $RuntimeDir "worker.pid")

    # Record Node itself instead of the npm.cmd wrapper so shutdown always reaches Vite.
    $ViteArg = '"' + $Vite + '"'
    $WebArgs = @($ViteArg, "--host", "127.0.0.1", "--port", "5173", "--strictPort")
    $Web = Start-Process -FilePath $Node -ArgumentList $WebArgs -WorkingDirectory (Join-Path $ProjectRoot "web") -WindowStyle Hidden -RedirectStandardOutput (Join-Path $RuntimeDir "web-$RunId.log") -RedirectStandardError (Join-Path $RuntimeDir "web-error-$RunId.log") -PassThru
    $Web.Id | Set-Content (Join-Path $RuntimeDir "web.pid")

    # /health/ready covers PostgreSQL, Redis, MinIO and the live ARQ worker sentinel.
    Wait-HttpReady "http://127.0.0.1:8000/health/ready" 45 "api"
    Wait-HttpReady "http://127.0.0.1:5173" 45 "web"
} catch {
    Show-RecentErrors
    Stop-RecordedProcess "api"
    Stop-RecordedProcess "worker"
    Stop-RecordedProcess "web"
    throw
}
Write-Host "Ready: http://127.0.0.1:5173 (API, PostgreSQL, Redis, MinIO and worker healthy; logs: .runtime/dev/)"
