param(
    [string]$BackupManifest = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot
$BackupRoot = [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot ".runtime\backups"))
if (-not $BackupManifest) {
    $Latest = Get-ChildItem -LiteralPath $BackupRoot -Filter "copilot-*-manifest.json" |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $Latest) { throw "No backup manifest found under $BackupRoot" }
    $ManifestPath = $Latest.FullName
} else {
    $ManifestPath = [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $BackupManifest))
}
if (-not $ManifestPath.StartsWith($BackupRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Restore drill only accepts manifests under $BackupRoot"
}
$Manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
$Directory = Split-Path -Parent $ManifestPath
$Dump = Join-Path $Directory $Manifest.database_dump
$Objects = Join-Path $Directory $Manifest.object_version_manifest
if ((Get-FileHash -LiteralPath $Dump -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Manifest.sha256) {
    throw "Database dump hash mismatch"
}
if ((Get-FileHash -LiteralPath $Objects -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Manifest.object_version_manifest_sha256) {
    throw "Object manifest hash mismatch"
}

$Stamp = Get-Date -Format "yyyyMMddHHmmssfff"
$Container = "copilot-restore-drill-$Stamp"
if ($Container -notmatch '^copilot-restore-drill-[0-9]{17}$') { throw "Unsafe drill container name" }
$ContainerDump = "/tmp/copilot-restore.dump"
try {
    docker run -d --name $Container -e POSTGRES_USER=copilot -e POSTGRES_PASSWORD=copilot `
        -e POSTGRES_DB=copilot_restore pgvector/pgvector:0.8.6-pg16-bookworm | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not create isolated restore container" }
    $Deadline = (Get-Date).AddSeconds(60)
    do {
        docker exec $Container pg_isready -U copilot -d copilot_restore 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { break }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $Deadline)
    if ($LASTEXITCODE -ne 0) { throw "Isolated PostgreSQL did not become ready" }
    docker cp $Dump "$Container`:$ContainerDump"
    if ($LASTEXITCODE -ne 0) { throw "Could not copy dump into restore container" }
    docker exec $Container pg_restore -U copilot -d copilot_restore --clean --if-exists $ContainerDump
    if ($LASTEXITCODE -ne 0) { throw "pg_restore failed in isolated container" }

    $Head = (docker exec $Container psql -U copilot -d copilot_restore -Atc `
        "select version_num from alembic_version;").Trim()
    if (-not $Head) { throw "Restored database has no Alembic version" }
    $Rows = @(docker exec $Container psql -U copilot -d copilot_restore -At -F "|" -c `
        "select object_key,coalesce(object_version_id,''),content_hash from document_revision where object_key is not null order by object_key;")
    $ObjectManifest = Get-Content -LiteralPath $Objects -Raw | ConvertFrom-Json
    $VersionMap = @{}
    foreach ($Version in $ObjectManifest.versions) {
        if ($Version.kind -eq "object") {
            $VersionMap["$($Version.key)|$($Version.version_id)"] = $Version
        }
    }
    $Checked = 0
    foreach ($Row in $Rows) {
        if (-not $Row) { continue }
        $Parts = $Row -split '\|', 3
        $Key = "$($Parts[0])|$($Parts[1])"
        if (-not $VersionMap.ContainsKey($Key)) { throw "Missing archived object version: $Key" }
        $Version = $VersionMap[$Key]
        $ArchiveFile = Join-Path $Directory $Manifest.object_archive | Join-Path -ChildPath $Version.backup_path
        $Actual = (Get-FileHash -LiteralPath $ArchiveFile -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($Actual -ne $Version.content_sha256 -or $Actual -ne $Parts[2]) {
            throw "Object content hash mismatch: $($Parts[0])"
        }
        $Checked += 1
    }
    Write-Host "Restore drill passed: alembic=$Head database_objects=$($Rows.Count) content_hashes=$Checked"
} finally {
    docker rm -f $Container 2>$null | Out-Null
}
