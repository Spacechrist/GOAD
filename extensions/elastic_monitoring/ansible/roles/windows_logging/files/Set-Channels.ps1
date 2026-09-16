[CmdletBinding(SupportsShouldProcess)]
param([string]$ChannelsJson, [bool]$VerifyOnly = $false)
$ErrorActionPreference = 'Stop'
$Ansible.Changed = $false
foreach ($entry in ($ChannelsJson | ConvertFrom-Json)) {
    $desiredBytes = [long]$entry.max_bytes
    if ($desiredBytes -lt 1MB -or $desiredBytes -gt 4294901760 -or ($desiredBytes % 65536) -ne 0) {
        throw 'Channel size must be a supported 64-KiB multiple.'
    }
    $log = Get-WinEvent -ListLog $entry.name -ErrorAction Stop
    $needsChange = -not $log.IsEnabled -or $log.MaximumSizeInBytes -lt $desiredBytes
    if ($needsChange -and $VerifyOnly) { throw "Channel configuration mismatch: $($entry.name)" }
    if ($needsChange) {
        if (-not $Ansible.CheckMode) {
            $log.IsEnabled = $true
            # No reduction or retention change; either can discard or stall logs.
            $log.MaximumSizeInBytes = [math]::Max($log.MaximumSizeInBytes, $desiredBytes)
            $log.SaveChanges()
        }
        $Ansible.Changed = $true
    }
}
