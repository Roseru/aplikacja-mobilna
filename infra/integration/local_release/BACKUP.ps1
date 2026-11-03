[CmdletBinding()]
param(
    [string]$Profile,
    [string]$Destination
)
if (-not $PSBoundParameters.ContainsKey('Profile')) {
    $Profile = Join-Path $PSScriptRoot 'runtime.json'
}
& (Join-Path $PSScriptRoot 'Invoke-LocalRelease.ps1') -Action backup -Profile $Profile -Destination $Destination
