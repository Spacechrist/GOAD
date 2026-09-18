[CmdletBinding(SupportsShouldProcess)]
param([string]$FleetUrl, [string]$ElasticsearchUrl)
$ErrorActionPreference = 'Stop'
$Ansible.Changed = $false

function Test-TcpUrl([string]$Url) {
    $uri = [uri]$Url
    $client = New-Object Net.Sockets.TcpClient
    $reachable = $false
    try {
        $task = $client.ConnectAsync($uri.DnsSafeHost, $uri.Port)
        if ($task.Wait(5000)) { $reachable = $client.Connected }
    } catch { $reachable = $false } finally { $client.Dispose() }
    return @{ host = $uri.DnsSafeHost; port = $uri.Port; tcp_reachable = $reachable }
}

$os = Get-CimInstance Win32_OperatingSystem
$computer = Get-CimInstance Win32_ComputerSystem
$drive = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='$($env:SystemDrive)'"
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
$services = @(Get-Service | Where-Object {
    $_.Name -match '^(Sysmon.*|elastic-agent|ElasticEndpoint|winlogbeat|filebeat)$'
} | ForEach-Object { @{ name = $_.Name; status = [string]$_.Status } })
$channels = @('Security', 'System', 'Application', 'Windows PowerShell',
    'Microsoft-Windows-PowerShell/Operational', 'Microsoft-Windows-Sysmon/Operational')
$logs = foreach ($channel in $channels) {
    try {
        $log = Get-WinEvent -ListLog $channel -ErrorAction Stop
        @{ name = $channel; exists = $true; enabled = $log.IsEnabled;
            maximum_bytes = $log.MaximumSizeInBytes; mode = [string]$log.LogMode }
    } catch { @{ name = $channel; exists = $false } }
}
$Ansible.Result = @{
    observed_at_utc = [DateTime]::UtcNow.ToString('o')
    hostname = $env:COMPUTERNAME
    os_caption = $os.Caption
    os_version = $os.Version
    build = [string]$os.BuildNumber
    os_language = [int]$os.OSLanguage
    x64 = [Environment]::Is64BitOperatingSystem -and ($env:PROCESSOR_ARCHITECTURE -eq 'AMD64')
    powershell_version = $PSVersionTable.PSVersion.ToString()
    is_admin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    is_dc = [int]$computer.DomainRole -in @(4, 5)
    free_gb = [math]::Round($drive.FreeSpace / 1GB, 2)
    services = $services
    collectors = @($services | Where-Object { $_.name -match '^(winlogbeat|filebeat)$' })
    event_logs = @($logs)
    connectivity = @((Test-TcpUrl $FleetUrl), (Test-TcpUrl $ElasticsearchUrl))
}
