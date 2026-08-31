[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9.]+$')]
    [string]$ServerAddress,

    [Parameter(Mandatory = $true)]
    [string]$IdentityFile,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9.-]+$')]
    [string]$Domain,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+$')]
    [string]$AcmeEmail,

    [ValidatePattern('^[a-z_][a-z0-9_-]*$')]
    [string]$SshUser = 'root'
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$IdentityPath = (Resolve-Path $IdentityFile).Path
$Addresses = @(
    Resolve-DnsName $Domain -Type A -Server 8.8.8.8 -ErrorAction Stop |
        Where-Object Type -eq 'A' |
        Select-Object -ExpandProperty IPAddress -Unique
)
if ($ServerAddress -notin $Addresses) {
    throw "$Domain 尚未解析到 $ServerAddress；当前 A 记录: $($Addresses -join ', ')"
}

$Target = '{0}@{1}' -f $SshUser, $ServerAddress
$Common = @(
    '-i', $IdentityPath,
    '-o', 'BatchMode=yes',
    '-o', 'StrictHostKeyChecking=accept-new',
    '-o', 'ConnectTimeout=10'
)
$LocalScript = Join-Path $ProjectRoot 'deploy\alibaba-cloud\switch-domain.sh'
$RemoteScript = '/tmp/ai-copilot-switch-domain.sh'

& scp @Common $LocalScript "${Target}:$RemoteScript"
if ($LASTEXITCODE -ne 0) { throw '无法上传域名切换脚本。' }
try {
    & ssh @Common $Target "sudo bash '$RemoteScript' '$Domain' '$AcmeEmail' '$ServerAddress'"
    if ($LASTEXITCODE -ne 0) { throw '域名切换失败，服务器已自动恢复原配置。' }
} finally {
    & ssh @Common $Target "rm -f '$RemoteScript'" 2>$null
}

Write-Host "Domain ready: https://$Domain/operations"
