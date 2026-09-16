[CmdletBinding()]
param(
    [string]$StateRoot,
    [ValidatePattern('^[0-9a-f]{64}$')][string]$ZipHash,
    [ValidatePattern('^[0-9a-f]{64}$')][string]$ConfigHash,
    [ValidatePattern('^[0-9a-f]{40}$')][string]$HartongRevision
)
$ErrorActionPreference = 'Stop'
$Ansible.Changed = $false
$zip = Join-Path $StateRoot "$ZipHash.zip"
$config = Join-Path $StateRoot "$ConfigHash.xml"
$statePath = Join-Path $StateRoot 'sysmon-state.json'
foreach ($pair in @(@($zip, $ZipHash), @($config, $ConfigHash))) {
    if ((Get-FileHash -LiteralPath $pair[0] -Algorithm SHA256).Hash -ne $pair[1]) {
        throw 'Transferred artifact checksum mismatch.'
    }
}
# Parse without resolving external entities. Sysmon itself validates the schema.
$settings = New-Object Xml.XmlReaderSettings
$settings.DtdProcessing = [Xml.DtdProcessing]::Prohibit
$settings.XmlResolver = $null
$reader = [Xml.XmlReader]::Create($config, $settings)
try { while ($reader.Read()) { } } finally { $reader.Dispose() }

Add-Type -AssemblyName System.IO.Compression.FileSystem
$exe = Join-Path $StateRoot "$ZipHash-Sysmon64.exe"
$archive = [IO.Compression.ZipFile]::OpenRead($zip)
try {
    $entries = @($archive.Entries | Where-Object { $_.FullName -ceq 'Sysmon64.exe' })
    if ($entries.Count -ne 1 -or $entries[0].Length -gt 32MB) { throw 'Invalid Sysmon archive.' }
    $stream = $entries[0].Open()
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $archiveBinaryHash = ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-', '') }
    finally { $stream.Dispose(); $sha.Dispose() }
    if (-not (Test-Path -LiteralPath $exe)) {
        [IO.Compression.ZipFileExtensions]::ExtractToFile($entries[0], $exe, $false)
        $Ansible.Changed = $true
    }
} finally { $archive.Dispose() }
if ((Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash -ne $archiveBinaryHash) {
    throw 'Staged executable differs from the locked archive.'
}
$signature = Get-AuthenticodeSignature -LiteralPath $exe
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation(?:,|$)') {
    throw 'Sysmon must have a valid Microsoft Authenticode signature. Check trust/revocation connectivity.'
}
$binaryHash = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash
$services = @(Get-CimInstance Win32_Service | Where-Object { $_.Name -like 'Sysmon*' })
$state = $null
if (Test-Path -LiteralPath $statePath) {
    $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
}
if ($services.Count -gt 1) { throw 'Multiple Sysmon services detected; review manually.' }
if ($services.Count -eq 1 -and $null -eq $state) {
    throw 'Existing unmanaged Sysmon detected. No adoption or replacement is performed.'
}
if ($null -ne $state -and $state.binary_sha256 -ne $binaryHash) {
    throw 'Binary upgrade requires a separately reviewed maintenance procedure; configuration-only updates are supported.'
}
if ($services.Count -eq 1) {
    $servicePath = $services[0].PathName
    if ($servicePath -match '^"([^"]+)"') { $installedExe = $Matches[1] }
    elseif ($servicePath -match '^(.+?\.exe)(?:\s|$)') { $installedExe = $Matches[1] }
    else { throw 'Cannot resolve installed Sysmon binary.' }
    if ((Get-FileHash -LiteralPath $installedExe -Algorithm SHA256).Hash -ne $binaryHash) {
        throw 'Installed Sysmon binary differs from the managed artifact.'
    }
}

function Invoke-Sysmon([string[]]$Arguments) {
    # Windows PowerShell 5.1 can wrap native stderr as ErrorRecord even on
    # success. Use the process exit code rather than treating banners as errors.
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $output = & $exe @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    } finally { $ErrorActionPreference = $previousPreference }
    if ($exitCode -ne 0) { throw "Sysmon returned exit code $exitCode. Inspect locally before retrying." }
    return ($output -join "`n")
}

function Get-ActiveConfigHash([string]$Dump) {
    # Match a hash field, not a hash embedded in the content-addressed XML path.
    $pattern = '(?im)^\s*[^\r\n]*config(?:uration)?[^\r\n]*hash\s*:\s*(?:SHA256=)?([a-f0-9]{64})\s*$'
    $fields = [regex]::Matches($Dump, $pattern)
    if ($fields.Count -ne 1) { throw 'Cannot unambiguously read the active Sysmon configuration hash.' }
    return $fields[0].Groups[1].Value
}

if ($services.Count -eq 0) {
    $null = Invoke-Sysmon -Arguments @('-accepteula', '-i', $config)
    $Ansible.Changed = $true
} else {
    $dump = Invoke-Sysmon -Arguments @('-c')
    if ((Get-ActiveConfigHash $dump) -ne $ConfigHash) {
        # Every previous managed XML remains in the content-addressed state directory.
        $null = Invoke-Sysmon -Arguments @('-c', $config)
        $Ansible.Changed = $true
    }
}
$service = Get-Service -Name Sysmon64 -ErrorAction Stop
if ($service.Status -ne 'Running') { throw 'Sysmon64 is not running.' }
$applied = Invoke-Sysmon -Arguments @('-c')
if ((Get-ActiveConfigHash $applied) -ne $ConfigHash) {
    throw 'Sysmon did not report the expected configuration hash. No success state was recorded.'
}
$newState = @{
    binary_sha256 = $binaryHash
    binary_version = (Get-Item -LiteralPath $exe).VersionInfo.FileVersion
    config_sha256 = $ConfigHash
    hartong_revision = $HartongRevision
    executable = $exe
    config_path = $config
}
if ($null -eq $state -or $state.config_sha256 -ne $ConfigHash -or $state.hartong_revision -ne $HartongRevision) {
    if (Test-Path -LiteralPath $statePath) {
        Copy-Item -LiteralPath $statePath -Destination (Join-Path $StateRoot "sysmon-state-$($state.config_sha256).json")
    }
    $newState | ConvertTo-Json | Set-Content -LiteralPath "$statePath.tmp" -Encoding UTF8
    Move-Item -LiteralPath "$statePath.tmp" -Destination $statePath -Force
    $Ansible.Changed = $true
}
$Ansible.Result = $newState
