param(
    [Parameter(Mandatory=$true)][string]$Python,
    [Parameter(Mandatory=$true)][string]$State,
    [Parameter(Mandatory=$true)][string]$Backups,
    [string]$DockerDesktop = 'C:\Program Files\Docker\Docker\Docker Desktop.exe'
)
$ErrorActionPreference = 'Stop'
$checkout = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$statePath = (Resolve-Path -LiteralPath $State).Path
$pythonPath = (Resolve-Path -LiteralPath $Python).Path
$pythonw = Join-Path (Split-Path -Parent $pythonPath) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonw -PathType Leaf)) { throw 'pythonw.exe is required.' }
$docker = (Get-Command docker).Source
$desktop = (Resolve-Path -LiteralPath $DockerDesktop).Path
$operations = Join-Path $statePath 'operations'
$project = (Get-Content -LiteralPath (Join-Path $statePath 'config.json') -Raw | ConvertFrom-Json).project
$backupRoot = [IO.Path]::GetFullPath($Backups)
$checkoutPrefix = $checkout.TrimEnd('\') + '\'
if ($backupRoot.StartsWith($checkoutPrefix, [StringComparison]::OrdinalIgnoreCase) -or $backupRoot -eq $checkout) {
    throw 'Scheduled private backups must be outside the checkout.'
}
$taskNames = @('O3-Calorie-Local-Backup', 'O3-Calorie-Backup-Recovery', 'O3-Calorie-Integration-Startup')
$description = 'O3 existing local installation maintenance; current user only; no provisioning.'
foreach ($name in $taskNames) {
    $existing = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if ($existing -and $existing.Description -ne $description) { throw 'Task name belongs to another installation.' }
    if ($existing -and $existing.State -eq 'Running') { throw 'Wait for existing maintenance before updating its runtime.' }
}
$sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
foreach ($directory in @($operations, $backupRoot)) {
    if (-not (Test-Path -LiteralPath $directory)) { New-Item -ItemType Directory -Path $directory | Out-Null }
    $item = Get-Item -LiteralPath $directory
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Private directories must not be redirected.' }
    & icacls $directory '/inheritance:r' '/grant:r' "*${sid}:(OI)(CI)F" '*S-1-5-18:(OI)(CI)F' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Private ACL setup failed.' }
}
# Store the physical path: packaged desktop callers may virtualize LocalAppData,
# while Task Scheduler runs outside that package's filesystem view.
$backupRoot = (& $pythonPath -I -c 'import pathlib,sys; print(pathlib.Path(sys.argv[1]).resolve(strict=True))' $backupRoot).Trim()
if ($LASTEXITCODE -ne 0 -or -not [IO.Path]::IsPathFullyQualified($backupRoot)) { throw 'Cannot resolve the physical backup root.' }
$ownerPath = Join-Path $backupRoot 'owner.json'
if (Test-Path -LiteralPath $ownerPath) {
    $owner = Get-Content -LiteralPath $ownerPath -Raw | ConvertFrom-Json
    if ($owner.owner -ne 'calorie-o3-scheduled-backup-v1' -or $owner.project -ne $project) {
        throw 'Backup root belongs to another installation.'
    }
} elseif (@(Get-ChildItem -LiteralPath $backupRoot -Force).Count -gt 0) {
    throw 'Use a new private directory; existing backups are not adopted.'
} else {
    @{owner='calorie-o3-scheduled-backup-v1'; project=$project} | ConvertTo-Json | Set-Content -LiteralPath $ownerPath -Encoding utf8
}
# Install committed sources in an immutable private runtime, independent of branch switches.
$revision = (& git -C $checkout rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Cannot identify committed runtime.' }
$runtime = Join-Path $operations "runtime-$revision"
if (-not (Test-Path -LiteralPath $runtime)) {
    $archive = Join-Path $operations 'runtime.zip'
    & git -C $checkout archive --format=zip --output=$archive HEAD infra/integration infra/local backend/Dockerfile backend/pyproject.toml backend/uv.lock
    if ($LASTEXITCODE -ne 0) { throw 'Cannot prepare committed runtime.' }
    Expand-Archive -LiteralPath $archive -DestinationPath $runtime
    Remove-Item -LiteralPath $archive
}
$script = Join-Path $runtime 'infra/integration/maintenance.py'
if (-not (Test-Path -LiteralPath $script)) { throw 'Commit maintenance sources before installation.' }
$settingsPath = Join-Path $operations 'settings.json'
@{state=$statePath; backups=$backupRoot; docker=$docker; docker_desktop=$desktop;
  finalizer_disabled=$true; keep=14; source_commit=$revision} | ConvertTo-Json | Set-Content -LiteralPath $settingsPath -Encoding utf8
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$common = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 45)
# Docker can exit while its updater is running at login. Retry only a failed
# startup action; never turn a successful startup into a permanent watchdog.
$startupSettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 45) -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 1)
$atLogin = New-ScheduledTaskTrigger -AtLogOn -User $identity
$backupLogin = New-ScheduledTaskTrigger -AtLogOn -User $identity
$backupLogin.Delay = 'PT3M'
$triggers = @(
    @((New-ScheduledTaskTrigger -Daily -At '03:00'), (New-ScheduledTaskTrigger -Daily -At '15:00'), $backupLogin),
    @((New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1))),
    @($atLogin)
)
$commands = @('backup --due', 'recover', 'startup')
for ($index = 0; $index -lt $taskNames.Count; $index++) {
    $arguments = '-I "{0}" {1} --settings "{2}"' -f $script, $commands[$index], $settingsPath
    $action = New-ScheduledTaskAction -Execute $pythonw -Argument $arguments -WorkingDirectory $runtime
    $taskSettings = if ($index -eq 2) { $startupSettings } else { $common }
    Register-ScheduledTask -TaskName $taskNames[$index] -Description $description -Action $action -Trigger $triggers[$index] -Settings $taskSettings -Principal $principal -Force | Out-Null
    $registered = Get-ScheduledTask -TaskName $taskNames[$index]
    if ($registered.Actions.Execute -ne $pythonw -or $registered.Actions.Arguments -ne $arguments -or $registered.Principal.RunLevel -ne 'Limited') {
        throw 'Registered task differs from requested maintenance.'
    }
    if ($index -eq 2 -and ($registered.Settings.RestartCount -ne 2 -or $registered.Settings.RestartInterval -ne 'PT1M')) {
        throw 'Registered startup retry policy differs from requested maintenance.'
    }
}
@{installed=$true; tasks=$taskNames; source_commit=$revision; backup_interval_hours=12;
  retained_verified_copies=14; startup_retries=2; startup_retry_seconds=60;
  offsite=$false; requires_logged_in_user=$true; console_windows=$false} | ConvertTo-Json -Compress
