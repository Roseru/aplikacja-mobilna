[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Python,
    [string]$Bundle = $PSScriptRoot,
    [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# This is a preparation gate. It never starts transport, services or a restore.
$bundleItem = Get-Item -LiteralPath $Bundle -Force
if (-not $bundleItem.PSIsContainer -or
    ($bundleItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
    throw 'Bundle must be an existing directory without redirection.'
}
$bundlePath = $bundleItem.FullName
$manifestPath = Join-Path $bundlePath 'manifest-demo.json'
$verifierPath = Join-Path $bundlePath 'local_demo_package.py'
foreach ($memberPath in @($manifestPath, $verifierPath)) {
    $member = Get-Item -LiteralPath $memberPath -Force
    if ($member.PSIsContainer -or
        ($member.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Manifest and verifier must be ordinary package-local files.'
    }
}
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$binding = $manifest.files.PSObject.Properties['local_demo_package.py']
if ($null -eq $binding) {
    throw 'Manifest does not bind the package-local verifier.'
}
$expected = $binding.Value
if ($expected.sha256 -isnot [string] -or
    $expected.sha256 -cnotmatch '^[0-9a-f]{64}$' -or
    $expected.bytes -isnot [ValueType] -or
    $expected.bytes -is [bool] -or
    [decimal]$expected.bytes -le 0 -or
    [decimal]$expected.bytes -ne [decimal]::Truncate([decimal]$expected.bytes)) {
    throw 'Invalid verifier SHA256 or byte count in manifest.'
}
$verifier = Get-Item -LiteralPath $verifierPath -Force
$actualHash = (Get-FileHash -LiteralPath $verifierPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualHash -cne $expected.sha256 -or
    [decimal]$verifier.Length -ne [decimal]$expected.bytes) {
    throw 'Package-local verifier differs from its manifest binding.'
}
$pythonItem = Get-Item -LiteralPath $Python -Force
if ($pythonItem.PSIsContainer) {
    throw 'Python must identify an existing interpreter file.'
}
$verifyArguments = @(
    '-I', '-B', $verifierPath, 'verify',
    '--bundle', $bundlePath, '--action', 'start'
)
if ($CheckOnly) {
    $verifyArguments += '--check-only'
}
$verifyOutput = @(& $pythonItem.FullName @verifyArguments)
$verifyExit = $LASTEXITCODE
$verifyOutput | Write-Output
if ($verifyExit -ne 0) {
    throw "Preparation gate refused start; verifier exit code $verifyExit. See its JSON blockers."
}
$result = ($verifyOutput -join [Environment]::NewLine) | ConvertFrom-Json
if ($result.integrity -cne 'PASS' -or
    $result.state -cne 'PREPARATION_ONLY' -or
    $result.action_authorized -isnot [bool] -or
    $result.action_authorized -ne $false) {
    throw 'Verifier did not return the expected preparation-only integrity result.'
}
if (-not $CheckOnly) {
    throw 'Preparation gate cannot authorize operational execution.'
}

