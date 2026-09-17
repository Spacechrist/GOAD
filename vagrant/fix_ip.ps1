param ([Parameter(Mandatory = $true)][System.Net.IPAddress] $ip)
$ErrorActionPreference = 'Stop'
if ($ip.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) {
    throw 'An IPv4 address is required'
}
$desired = $ip.ToString()
$taskName = 'GOAD-Configure-Lab-IP'
$nic = Get-NetIPInterface -InterfaceAlias Ethernet1 -AddressFamily IPv4
$current = Get-NetIPAddress -InterfaceAlias Ethernet1 -AddressFamily IPv4 |
    Where-Object { $_.IPAddress -eq $desired -and $_.PrefixLength -eq 24 -and $_.AddressState -eq 'Preferred' }
if ($current -and $nic.Dhcp -eq 'Disabled') {
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    }
    Write-Output "Ethernet1 already configured as $desired/24; no change needed."
    exit 0
}
# Only a validated IPv4 literal is embedded. No writable script runs as SYSTEM.
# Vagrant reload disconnects WinRM before this startup task changes the address.
$code = @"
`$ErrorActionPreference = 'Stop'
& netsh.exe int ip set address Ethernet1 static $desired 255.255.255.0
if (`$LASTEXITCODE -ne 0) { exit `$LASTEXITCODE }
Unregister-ScheduledTask -TaskName '$taskName' -Confirm:`$false
"@
$encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($code))
$action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Argument "-NoProfile -NonInteractive -EncodedCommand $encoded"
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 2)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -User SYSTEM -RunLevel Highest -Force | Out-Null
Write-Output "Scheduled Ethernet1=$desired/24 for the following Vagrant reboot."
