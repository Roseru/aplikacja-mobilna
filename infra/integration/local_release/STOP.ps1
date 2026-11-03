[CmdletBinding()]
param([string]$Profile)
if (-not $PSBoundParameters.ContainsKey('Profile')) {
    $Profile = Join-Path $PSScriptRoot 'runtime.json'
}
& (Join-Path $PSScriptRoot 'Invoke-LocalRelease.ps1') -Action stop -Profile $Profile
