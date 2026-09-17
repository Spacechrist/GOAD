param(
    [string] $Url, [string] $Destination, [string] $ExpectedSHA256 = '',
    [string] $MinimumVersion = '0.0', [string] $VersionPattern = '^.*$',
    [string] $OriginalName = '', [bool] $Refresh = $false
)
$ErrorActionPreference = 'Stop'
$Ansible.Changed = $false
if (([uri]$Url).Scheme -ne 'https') { throw 'Installer URL must use HTTPS' }
if ($ExpectedSHA256 -and $ExpectedSHA256 -notmatch '^[a-fA-F0-9]{64}$') { throw 'Invalid SHA256 pin' }
function Inspect-Installer([string] $Path) {
    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch '(^|,\s*)O=Microsoft Corporation(,|$)') {
        throw "Invalid Microsoft Authenticode signature: $Path"
    }
    $info = (Get-Item -LiteralPath $Path).VersionInfo
    if ($OriginalName -and $info.OriginalFilename -ine $OriginalName) { throw 'Unexpected installer product/edition' }
    $version = [regex]::Match($info.ProductVersion, '\d+\.\d+(?:\.\d+){0,2}').Value
    if (-not $version -or $version -notmatch $VersionPattern -or [version]$version -lt [version]$MinimumVersion) {
        throw "Unapproved installer version: $($info.ProductVersion)"
    }
    $sha = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($ExpectedSHA256 -and $sha -ine $ExpectedSHA256) { throw 'Installer SHA256 does not match the approved pin' }
    return @{ version = $version; sha256 = $sha; url = $Url; original_name = $info.OriginalFilename }
}
$directory = Split-Path -Parent $Destination
New-Item -ItemType Directory -Path $directory -Force | Out-Null
$lockPath = "$Destination.artifact.json"
$record = $null
$cached = $false
if ((Test-Path -LiteralPath $Destination) -and -not $Refresh) {
    if (Test-Path -LiteralPath $lockPath) {
        $saved = Get-Content -LiteralPath $lockPath -Raw | ConvertFrom-Json
        $actual = (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash
        if ($actual -ine $saved.sha256) { throw 'Cached installer changed since recording; inspect it or explicitly refresh' }
        if ($saved.url -eq $Url) {
            try { $record = Inspect-Installer $Destination; $cached = $true } catch { $cached = $false }
        }
    } else {
        try { $record = Inspect-Installer $Destination; $cached = $true } catch { $cached = $false }
    }
}
if (-not $cached) {
    $staged = Join-Path $directory ([guid]::NewGuid().ToString() + '.exe')
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $Url -OutFile $staged -UseBasicParsing -TimeoutSec 900
        $record = Inspect-Installer $staged
        if (Test-Path -LiteralPath $Destination) {
            $oldHash = (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash
            Copy-Item -LiteralPath $Destination -Destination "$Destination.previous-$oldHash" -Force
        }
        Move-Item -LiteralPath $staged -Destination $Destination -Force
        $Ansible.Changed = $true
    } finally {
        if (Test-Path -LiteralPath $staged) { Remove-Item -LiteralPath $staged -Force }
    }
}
if (-not (Test-Path -LiteralPath $lockPath) -or $Ansible.Changed) {
    $record | ConvertTo-Json | Set-Content -LiteralPath "$lockPath.pending" -Encoding UTF8
    Move-Item -LiteralPath "$lockPath.pending" -Destination $lockPath -Force
    $Ansible.Changed = $true
}
$Ansible.Result = $record
