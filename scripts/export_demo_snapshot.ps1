param(
    [string]$Destination = ".runtime\demo-deploy"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$AllowedRoot = [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot ".runtime"))
$TargetRoot = [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $Destination))
if (-not $TargetRoot.StartsWith($AllowedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Snapshot destination must stay under $AllowedRoot"
}

$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$SnapshotDir = Join-Path $TargetRoot "copilot-demo-$Stamp"
$DatabaseDump = Join-Path $SnapshotDir "database.dump"
$MinioArchive = Join-Path $SnapshotDir "minio-volume.tar"
$SnapshotManifest = Join-Path $SnapshotDir "snapshot-manifest.json"
$ContainerDump = "/tmp/copilot-demo-$Stamp.dump"
$MinioWasRunning = $false
$StoppedProcesses = @()

New-Item -ItemType Directory -Path $SnapshotDir -Force | Out-Null

try {
    foreach ($PidFile in @("api.pid", "worker.pid")) {
        $PidPath = Join-Path $ProjectRoot ".runtime\dev\$PidFile"
        if (-not (Test-Path -LiteralPath $PidPath)) { continue }
        $CandidatePid = [int](Get-Content -LiteralPath $PidPath)
        $Process = Get-CimInstance Win32_Process -Filter "ProcessId = $CandidatePid" -ErrorAction SilentlyContinue
        if (-not $Process) { continue }
        $IsProjectProcess = $Process.Name -eq "python.exe" -and
            $Process.CommandLine -like "*$ProjectRoot*" -and
            ($Process.CommandLine -match "uvicorn app\.api\.main:app|arq app\.workers\.settings\.WorkerSettings")
        if (-not $IsProjectProcess) {
            throw "Refusing to stop unexpected process $CandidatePid from $PidPath"
        }
        Stop-Process -Id $CandidatePid -Force
        $StoppedProcesses += $PidFile
    }

    docker exec copilot-postgres pg_dump -U copilot -d copilot -Fc -f $ContainerDump
    if ($LASTEXITCODE -ne 0) { throw "PostgreSQL backup failed" }
    docker cp "copilot-postgres`:$ContainerDump" $DatabaseDump
    if ($LASTEXITCODE -ne 0) { throw "Could not copy PostgreSQL backup to host" }

    $MinioWasRunning = (docker inspect copilot-minio --format "{{.State.Running}}") -eq "true"
    if ($MinioWasRunning) {
        docker stop copilot-minio | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Could not stop local MinIO for a consistent snapshot" }
    }

    $DockerTarget = $SnapshotDir.Replace("\", "/")
    docker run --rm --entrypoint /bin/sh `
        -v "copilot-local_minio-data:/source:ro" `
        -v "${DockerTarget}:/snapshot" `
        pgvector/pgvector:0.8.6-pg16-bookworm `
        -c "tar -C /source -cf /snapshot/minio-volume.tar ."
    if ($LASTEXITCODE -ne 0) { throw "MinIO volume snapshot failed" }

    $DatabaseHash = (Get-FileHash -LiteralPath $DatabaseDump -Algorithm SHA256).Hash.ToLowerInvariant()
    $MinioHash = (Get-FileHash -LiteralPath $MinioArchive -Algorithm SHA256).Hash.ToLowerInvariant()
    @{
        created_at = (Get-Date).ToUniversalTime().ToString("o")
        source_database = "copilot"
        target_database = "copilot_demo"
        object_store_bucket = "copilot-documents"
        database_dump = "database.dump"
        database_dump_sha256 = $DatabaseHash
        minio_volume_archive = "minio-volume.tar"
        minio_volume_archive_sha256 = $MinioHash
        consistency = "API and worker stopped; PostgreSQL dumped; MinIO volume archived while stopped"
    } | ConvertTo-Json | Set-Content -LiteralPath $SnapshotManifest -Encoding utf8

    Write-Output $SnapshotDir
    Write-Output "database.dump sha256=$DatabaseHash"
    Write-Output "minio-volume.tar sha256=$MinioHash"
}
finally {
    docker exec copilot-postgres rm -f $ContainerDump 2>$null
    if ($MinioWasRunning) {
        docker start copilot-minio | Out-Null
    }
    if ($StoppedProcesses.Count -gt 0) {
        & (Join-Path $PSScriptRoot "dev.ps1") up
    }
}
