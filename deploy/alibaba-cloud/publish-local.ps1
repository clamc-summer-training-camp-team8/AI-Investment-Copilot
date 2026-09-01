[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ServerAddress,

    [ValidatePattern('^[a-z_][a-z0-9_-]*$')]
    [string]$SshUser = 'root',

    [Parameter(Mandatory = $true)]
    [string]$IdentityFile,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9.-]+$')]
    [string]$SiteAddress,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[^@\s]+@[^@\s]+$')]
    [string]$AcmeEmail,

    [ValidatePattern('^[A-Za-z0-9_.-]+$')]
    [string]$InitialUser = 'integration_admin'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$IdentityPath = (Resolve-Path $IdentityFile).Path
$RuntimeRoot = Join-Path $ProjectRoot '.runtime\alibaba-cloud-publish'
$ReleaseId = '{0}-{1}' -f (Get-Date -Format 'yyyyMMddHHmmss'), ((git -C $ProjectRoot rev-parse --short HEAD).Trim())
$StagePath = Join-Path $RuntimeRoot "ai-copilot-release-$ReleaseId"
$StageFull = [IO.Path]::GetFullPath($StagePath)
$AllowedFull = [IO.Path]::GetFullPath($RuntimeRoot)
if (-not $StageFull.StartsWith($AllowedFull + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "非法发布暂存目录: $StageFull"
}
New-Item -ItemType Directory -Path $StageFull -Force | Out-Null

$SshTarget = '{0}@{1}' -f $SshUser, $ServerAddress
$SshCommon = @(
    '-i', $IdentityPath,
    '-o', 'BatchMode=yes',
    '-o', 'StrictHostKeyChecking=accept-new',
    '-o', 'ConnectTimeout=10'
)

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments
    )
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Command failed with exit code $LASTEXITCODE"
    }
}

function New-RandomSecret([int]$Length = 48) {
    $alphabet = 'abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    $bytes = [byte[]]::new($Length)
    [Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
    -join ($bytes | ForEach-Object { $alphabet[$_ % $alphabet.Length] })
}

$InitialPassword = $null
try {
    Write-Host "Checking SSH access to $SshTarget ..."
    Invoke-Native ssh @SshCommon $SshTarget 'true'

    $HostState = ((& ssh @SshCommon $SshTarget "sudo test -s /opt/ai-investment-copilot/.bootstrap-v1 && command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1 && echo ready || echo bootstrap") | Select-Object -Last 1).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw 'Unable to inspect Docker on the remote host.'
    }
    if ($HostState -ne 'ready') {
        $BootstrapRemote = '/tmp/ai-copilot-bootstrap.sh'
        Invoke-Native scp @SshCommon (Join-Path $PSScriptRoot 'bootstrap-ubuntu.sh') "${SshTarget}:$BootstrapRemote"
        Invoke-Native ssh @SshCommon $SshTarget "sudo env DEPLOY_USER='$SshUser' bash '$BootstrapRemote'"
    }

    $Existing = ((& ssh @SshCommon $SshTarget "sudo test -s /opt/ai-investment-copilot/deploy/.env.integration && echo existing || echo new") | Select-Object -Last 1).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw 'Unable to inspect the remote integration configuration.'
    }

    $AppImage = "ai-investment-copilot-app:$ReleaseId"
    $WebImage = "ai-investment-copilot-web:$ReleaseId"
    $RemoteDockerHost = "ssh://$SshTarget"
    & docker --host $RemoteDockerHost version --format '{{.Server.Version}}' *> $null
    $CanBuildRemotely = $LASTEXITCODE -eq 0
    if ($CanBuildRemotely) {
        # Docker 的 SSH transport 会把受 .dockerignore 过滤的构建上下文直接发往 ECS。
        # 当前上下文约数 MB，远小于 docker save 产生的数百 MB 镜像归档。
        Write-Host 'Building immutable application images on the remote Docker host ...'
        Invoke-Native docker --host $RemoteDockerHost build --file (Join-Path $ProjectRoot 'deploy\integration\Dockerfile.app') --tag $AppImage $ProjectRoot
        Invoke-Native docker --host $RemoteDockerHost build --file (Join-Path $ProjectRoot 'deploy\integration\Dockerfile.web') --tag $WebImage $ProjectRoot
    } else {
        Write-Host 'Remote Docker SSH transport unavailable; building and compressing images locally ...'
        Invoke-Native docker build --file (Join-Path $ProjectRoot 'deploy\integration\Dockerfile.app') --tag $AppImage $ProjectRoot
        Invoke-Native docker build --file (Join-Path $ProjectRoot 'deploy\integration\Dockerfile.web') --tag $WebImage $ProjectRoot
        $ImageTar = Join-Path $StageFull 'images.tar'
        $ImageArchive = Join-Path $StageFull 'images.tar.gz'
        Invoke-Native docker save --output $ImageTar $AppImage $WebImage
        $SourceStream = [IO.File]::OpenRead($ImageTar)
        try {
            $TargetStream = [IO.File]::Create($ImageArchive)
            try {
                $GzipStream = [IO.Compression.GZipStream]::new(
                    $TargetStream,
                    [IO.Compression.CompressionLevel]::Fastest
                )
                try {
                    $SourceStream.CopyTo($GzipStream)
                } finally {
                    $GzipStream.Dispose()
                }
            } finally {
                $TargetStream.Dispose()
            }
        } finally {
            $SourceStream.Dispose()
        }
        Remove-Item -LiteralPath $ImageTar -Force
    }

    Copy-Item (Join-Path $ProjectRoot 'deploy\docker-compose.integration.yml') (Join-Path $StageFull 'docker-compose.integration.yml')
    Copy-Item (Join-Path $ProjectRoot 'deploy\integration\Caddyfile') (Join-Path $StageFull 'Caddyfile')
    Copy-Item (Join-Path $ProjectRoot 'deploy\integration\backup.sh') (Join-Path $StageFull 'backup.sh')
    Copy-Item (Join-Path $ProjectRoot 'deploy\integration\restore-drill.sh') (Join-Path $StageFull 'restore-drill.sh')
    Copy-Item (Join-Path $PSScriptRoot 'install-release.sh') (Join-Path $StageFull 'install-release.sh')
    [IO.File]::WriteAllText(
        (Join-Path $StageFull 'release.env'),
        "APP_IMAGE=$AppImage`nWEB_IMAGE=$WebImage`n",
        [Text.UTF8Encoding]::new($false)
    )

    if ($Existing -eq 'new') {
        $JwtSecret = New-RandomSecret 64
        $PostgresPassword = New-RandomSecret 48
        $RedisPassword = New-RandomSecret 48
        $MinioPassword = New-RandomSecret 48
        $InitialPassword = New-RandomSecret 24
        $ParsedIp = $null
        $TlsArgument = if ([Net.IPAddress]::TryParse($SiteAddress, [ref]$ParsedIp)) { 'internal' } else { $AcmeEmail }
        $Environment = @"
INTEGRATION_SITE_ADDRESS=$SiteAddress
ACME_EMAIL=$AcmeEmail
INTEGRATION_TLS_ARGUMENT=$TlsArgument
AUTH_JWT_SECRET=$JwtSecret
POSTGRES_PASSWORD=$PostgresPassword
DATABASE_URL=postgresql+psycopg://copilot:${PostgresPassword}@postgres:5432/copilot
REDIS_PASSWORD=$RedisPassword
REDIS_URL=redis://:${RedisPassword}@redis:6379/0
MINIO_ROOT_USER=copilot-integration
MINIO_ROOT_PASSWORD=$MinioPassword
OBJECT_STORE_BUCKET=copilot-documents
CORS_ORIGINS=["https://$SiteAddress"]
LLM_PROVIDER=local
LLM_ENDPOINT=
LLM_API_KEY=
LLM_MODEL_VERSION=local-rule-v1
"@
        [IO.File]::WriteAllText(
            (Join-Path $StageFull '.env.integration'),
            $Environment.Replace("`r`n", "`n"),
            [Text.UTF8Encoding]::new($false)
        )
        [IO.File]::WriteAllText(
            (Join-Path $StageFull 'bootstrap-user'),
            "$InitialUser`n$InitialPassword`n",
            [Text.UTF8Encoding]::new($false)
        )
    } else {
        $HasJwtSecret = ((& ssh @SshCommon $SshTarget "sudo grep -q '^AUTH_JWT_SECRET=' /opt/ai-investment-copilot/deploy/.env.integration && echo yes || echo no") | Select-Object -Last 1).Trim()
        if ($LASTEXITCODE -ne 0) {
            throw 'Unable to inspect the remote JWT configuration.'
        }
        if ($HasJwtSecret -ne 'yes') {
            [IO.File]::WriteAllText(
                (Join-Path $StageFull 'auth-jwt-secret'),
                (New-RandomSecret 64) + "`n",
                [Text.UTF8Encoding]::new($false)
            )
        }
    }

    $RemoteStage = "/tmp/ai-copilot-release-$ReleaseId"
    Invoke-Native scp @SshCommon -r $StageFull "${SshTarget}:/tmp/"
    Invoke-Native ssh @SshCommon $SshTarget "sudo env DEPLOY_USER='$SshUser' bash '$RemoteStage/install-release.sh' '$RemoteStage'"

    Write-Host "Integration URL: https://$SiteAddress/operations"
    if ($InitialPassword) {
        Write-Host "Initial user: $InitialUser"
        Write-Host "Initial one-time password: $InitialPassword"
        Write-Host '请立即登录并按团队账号策略替换此临时账号。'
    } else {
        Write-Host '服务器已有运行密钥，本次未轮换；现有产品账号保持不变。'
    }
} finally {
    if (Test-Path -LiteralPath $StageFull) {
        $ResolvedStage = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $StageFull).Path)
        if ($ResolvedStage.StartsWith($AllowedFull + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $ResolvedStage -Recurse -Force
        }
    }
}
