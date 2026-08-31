param(
    [string]$Destination = ".runtime\backups"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Target = [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $Destination))
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$AllowedRoot = [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot ".runtime"))
if (-not $Target.StartsWith($AllowedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Backup destination must stay under $AllowedRoot"
}
New-Item -ItemType Directory -Path $Target -Force | Out-Null
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$Dump = Join-Path $Target "copilot-$Stamp.dump"
$ObjectManifest = Join-Path $Target "copilot-$Stamp-objects.json"
$ObjectArchive = Join-Path $Target "copilot-$Stamp-object-archive"
$Manifest = Join-Path $Target "copilot-$Stamp-manifest.json"
$ContainerDump = "/tmp/copilot-$Stamp.dump"

try {
    docker exec copilot-postgres pg_dump -U copilot -d copilot -Fc -f $ContainerDump
    if ($LASTEXITCODE -ne 0) { throw "PostgreSQL backup failed" }
    docker cp "copilot-postgres`:$ContainerDump" $Dump
    if ($LASTEXITCODE -ne 0) { throw "Could not copy PostgreSQL backup to host" }
} finally {
    docker exec copilot-postgres rm -f $ContainerDump 2>$null
}

$Hash = (Get-FileHash -LiteralPath $Dump -Algorithm SHA256).Hash.ToLowerInvariant()
& $Python -m scripts.export_object_manifest --output $ObjectManifest --archive-dir $ObjectArchive
if ($LASTEXITCODE -ne 0) { throw "Could not create the object-store version manifest" }
$ObjectManifestHash = (Get-FileHash -LiteralPath $ObjectManifest -Algorithm SHA256).Hash.ToLowerInvariant()
@{
    created_at = (Get-Date).ToUniversalTime().ToString("o")
    database_dump = [System.IO.Path]::GetFileName($Dump)
    sha256 = $Hash
    object_store_bucket = "copilot-documents"
    object_version_manifest = [System.IO.Path]::GetFileName($ObjectManifest)
    object_version_manifest_sha256 = $ObjectManifestHash
    object_archive = [System.IO.Path]::GetFileName($ObjectArchive)
    object_store_note = "Every MinIO object version is exported under object_archive and content-hashed; replicate this backup directory off-host."
} | ConvertTo-Json | Set-Content -LiteralPath $Manifest -Encoding utf8
Write-Host "Backup created: $Manifest"
