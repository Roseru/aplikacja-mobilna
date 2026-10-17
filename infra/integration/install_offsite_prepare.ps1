param(
    [Parameter(Mandatory=$true)][string]$Python,
    [Parameter(Mandatory=$true)][string]$Settings
)
$ErrorActionPreference = 'Stop'
$checkout = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$settingsPath = (Resolve-Path -LiteralPath $Settings).Path
$settingsValue = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
$pythonPath = (Resolve-Path -LiteralPath $Python).Path
$pythonw = Join-Path (Split-Path -Parent $pythonPath) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonw -PathType Leaf)) { throw 'pythonw.exe is required.' }
$outgoing = (Resolve-Path -LiteralPath $settingsValue.outgoing).Path
if ($outgoing.StartsWith($checkout.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Private outgoing files must remain outside the checkout.'
}
$taskName = 'O3-Calorie-Offsite-Prepare'
$description = 'O3 prepare verified encrypted backups; no cloud upload or key recovery claim.'
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing -and $existing.Description -ne $description) { throw 'Task belongs to another workflow.' }
if ($existing -and $existing.State -eq 'Running') { throw 'Wait for existing preparation.' }
$revision = (& git -C $checkout rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Cannot identify committed sources.' }
& git -C $checkout diff --exit-code HEAD -- infra/integration
if ($LASTEXITCODE -ne 0) { throw 'Commit runtime sources before installation.' }
& git -C $checkout cat-file -e 'HEAD:infra/integration/offsite_delivery.py'
if ($LASTEXITCODE -ne 0) { throw 'Committed delivery tool is required.' }
$runtime = Join-Path (Split-Path -Parent $outgoing) "offsite-runtime-$revision"
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
if (-not (Test-Path -LiteralPath $runtime)) {
    New-Item -ItemType Directory -Path $runtime | Out-Null
    $sid = $identity.User.Value
    & icacls $runtime '/inheritance:r' '/grant:r' "*${sid}:(OI)(CI)F" '*S-1-5-18:(OI)(CI)F' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Private runtime ACL failed.' }
    $archive = Join-Path $runtime 'runtime.zip'
    & git -C $checkout archive --format=zip --output=$archive HEAD infra/integration infra/local
    if ($LASTEXITCODE -ne 0) { throw 'Cannot archive committed runtime.' }
    Expand-Archive -LiteralPath $archive -DestinationPath $runtime
    Remove-Item -LiteralPath $archive
    @{owner='calorie-o3-offsite-prepare-v1'; revision=$revision} | ConvertTo-Json |
        Set-Content -LiteralPath (Join-Path $runtime 'runtime-owner.json') -Encoding utf8
}
$item = Get-Item -LiteralPath $runtime
if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Runtime must not be redirected.' }
$owner = Get-Content -LiteralPath (Join-Path $runtime 'runtime-owner.json') -Raw | ConvertFrom-Json
if ($owner.owner -ne 'calorie-o3-offsite-prepare-v1' -or $owner.revision -ne $revision) {
    throw 'Runtime ownership differs.'
}
$script = Join-Path $runtime 'infra/integration/offsite_delivery.py'
if (-not (Test-Path -LiteralPath $script -PathType Leaf)) { throw 'Runtime script missing.' }
$arguments = '-I "{0}" prepare --settings "{1}"' -f $script, $settingsPath
$action = New-ScheduledTaskAction -Execute $pythonw -Argument $arguments -WorkingDirectory $runtime
$principal = New-ScheduledTaskPrincipal -UserId $identity.Name -LogonType Interactive -RunLevel Limited
$triggers = @((New-ScheduledTaskTrigger -Daily -At '03:20'), (New-ScheduledTaskTrigger -Daily -At '15:20'))
$common = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
Register-ScheduledTask -TaskName $taskName -Description $description -Action $action -Trigger $triggers -Settings $common -Principal $principal -Force | Out-Null
$registered = Get-ScheduledTask -TaskName $taskName
if ($registered.Actions.Execute -ne $pythonw -or $registered.Actions.Arguments -ne $arguments -or $registered.Principal.RunLevel -ne 'Limited') {
    throw 'Registered task differs.'
}
@{installed=$true; source_commit=$revision; runtime=$runtime; task=$taskName; cloud_upload=$false; console_windows=$false; requires_logged_in_user=$true} | ConvertTo-Json -Compress
