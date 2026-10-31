[CmdletBinding()]
param([string]$Profile = (Join-Path $PSScriptRoot 'runtime.json'))
& (Join-Path $PSScriptRoot 'Invoke-LocalRelease.ps1') -Action stop -Profile $Profile
