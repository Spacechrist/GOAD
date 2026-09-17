# Run on Windows PowerShell 5.1 before a canary deployment. Does not execute files.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$repository = Split-Path -Parent (Split-Path -Parent $root)
$failed = $false
$paths = @((Join-Path $root 'ansible'),
           (Join-Path $repository 'vagrant'),
           (Join-Path $repository 'ansible\roles\verified_installer'))
Get-ChildItem -LiteralPath $paths -Recurse -Filter '*.ps1' | ForEach-Object {
    $tokens = $null
    $parseErrors = $null
    [System.Management.Automation.Language.Parser]::ParseFile($_.FullName, [ref]$tokens, [ref]$parseErrors) | Out-Null
    foreach ($problem in $parseErrors) {
        Write-Output "$($_.FullName): $($problem.Message)"
        $failed = $true
    }
}
if ($failed) { throw 'PowerShell syntax validation failed.' }
Write-Output 'All PowerShell files parsed. Runtime behavior still requires canary testing.'
