param ([Parameter(Mandatory = $true)][System.Net.IPAddress] $ip)
$ErrorActionPreference = 'Stop'
$deadline = (Get-Date).AddSeconds(120)
do {
    $nic = Get-NetIPInterface -InterfaceAlias Ethernet1 -AddressFamily IPv4
    $address = Get-NetIPAddress -InterfaceAlias Ethernet1 -AddressFamily IPv4 |
        Where-Object { $_.IPAddress -eq $ip.ToString() -and $_.PrefixLength -eq 24 -and $_.AddressState -eq 'Preferred' }
    if ($address -and $nic.Dhcp -eq 'Disabled') {
        Write-Output "Verified Ethernet1=$ip/24 after reboot."
        exit 0
    }
    Start-Sleep -Seconds 2
} while ((Get-Date) -lt $deadline)
throw "Ethernet1 did not acquire $ip/24. Inspect task GOAD-Configure-Lab-IP; do not recreate the VM."
