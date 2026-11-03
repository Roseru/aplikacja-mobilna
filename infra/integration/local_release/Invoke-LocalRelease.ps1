[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidateSet('start','status','stop','backup')][string]$Action,
    [string]$Profile = (Join-Path $PSScriptRoot 'runtime.json'),
    [string]$Destination
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$launcher = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'launcher.private.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$arguments = @('-I', '-B', [string]$launcher.entrypoint, $Action, '--profile', $Profile)
if ($Action -eq 'backup') {
    if (-not $Destination) {
        $Destination = Join-Path $PSScriptRoot ('backups/' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ') + '-' + [guid]::NewGuid().ToString('N'))
    }
    $arguments += @('--backup', $Destination)
}
& ([string]$launcher.python) @arguments
if ($LASTEXITCODE -ne 0) {
    throw 'Local release operation refused or failed. No successful operation is declared.'
}
