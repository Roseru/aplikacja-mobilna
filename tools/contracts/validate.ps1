$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
Push-Location $repoRoot
try {
    $uvCommand = Get-Command uv -ErrorAction SilentlyContinue
    $uvPath = if ($uvCommand) { $uvCommand.Source } else { Join-Path $repoRoot '.tools/uv/bin/uv.exe' }
    if (-not (Test-Path -LiteralPath $uvPath)) { throw 'Brak uv. Zainstaluj uv 0.9.5 i wykonaj uv sync --project tools/contracts --locked --python 3.13.' }
    & $uvPath run --project tools/contracts --locked --offline --cache-dir .uv-cache python tools/contracts/validate.py
    if ($LASTEXITCODE -ne 0) { throw "Walidacja E0 nie powiodła się: exit $LASTEXITCODE" }
} finally { Pop-Location }
