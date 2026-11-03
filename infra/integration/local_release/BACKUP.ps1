[CmdletBinding()]
param(
    [string]$Profile = (Join-Path $PSScriptRoot 'runtime.json'),
    [string]$Destination
)
& (Join-Path $PSScriptRoot 'Invoke-LocalRelease.ps1') -Action backup -Profile $Profile -Destination $Destination
