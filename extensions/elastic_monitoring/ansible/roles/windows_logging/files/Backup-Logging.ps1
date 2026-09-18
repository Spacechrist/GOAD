[CmdletBinding()]
param([string]$StateRoot, [string]$RegistryJson, [string]$ChannelsJson)
$ErrorActionPreference = 'Stop'
$Ansible.Changed = $false
$baseline = Join-Path $StateRoot 'logging-baseline.json'
$auditBackup = Join-Path $StateRoot 'audit-policy-before.csv'
if (Test-Path -LiteralPath $baseline) {
    $saved = Get-Content -LiteralPath $baseline -Raw | ConvertFrom-Json
    if (-not (Test-Path -LiteralPath $auditBackup)) { throw 'Audit baseline is missing.' }
    if ((Get-FileHash -LiteralPath $auditBackup -Algorithm SHA256).Hash -ne $saved.audit_sha256) {
        throw 'Audit baseline changed; inspect before continuing.'
    }
    # New settings must not silently extend an old, incomplete rollback baseline.
    foreach ($entry in ($RegistryJson | ConvertFrom-Json)) {
        if (-not @($saved.registry | Where-Object { $_.path -eq $entry.path -and $_.name -eq $entry.name }).Count) {
            throw 'Logging scope changed; take a new reviewed baseline before proceeding.'
        }
    }
    foreach ($entry in ($ChannelsJson | ConvertFrom-Json)) {
        if (-not @($saved.channels | Where-Object { $_.name -eq $entry.name }).Count) {
            throw 'Channel scope changed; take a new reviewed baseline before proceeding.'
        }
    }
    return
}
$registry = foreach ($entry in ($RegistryJson | ConvertFrom-Json)) {
    $exists = $false
    $value = $null
    $kind = $null
    if (Test-Path -LiteralPath $entry.path) {
        $key = Get-Item -LiteralPath $entry.path
        $exists = $key.GetValueNames() -contains $entry.name
        if ($exists) {
            $value = $key.GetValue($entry.name, $null, 'DoNotExpandEnvironmentNames')
            $kind = [string]$key.GetValueKind($entry.name)
        }
    }
    @{ path = $entry.path; name = $entry.name; existed = $exists; value = $value; kind = $kind }
}
$channels = foreach ($entry in ($ChannelsJson | ConvertFrom-Json)) {
    # Missing requested channels fail before any configuration is applied.
    $log = Get-WinEvent -ListLog $entry.name -ErrorAction Stop
    @{ name = $entry.name; enabled = $log.IsEnabled;
       max_bytes = $log.MaximumSizeInBytes; mode = [string]$log.LogMode }
}
& auditpol.exe /backup "/file:$auditBackup" | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not back up audit policy.' }
@{
    created_at_utc = [DateTime]::UtcNow.ToString('o')
    hostname = $env:COMPUTERNAME
    audit_sha256 = (Get-FileHash -LiteralPath $auditBackup -Algorithm SHA256).Hash
    registry = @($registry)
    channels = @($channels)
} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath "$baseline.tmp" -Encoding UTF8
Move-Item -LiteralPath "$baseline.tmp" -Destination $baseline
$Ansible.Changed = $true
