param(
    [Parameter(Mandatory=$true)][string]$Python,
    [Parameter(Mandatory=$true)][string]$State,
    [Parameter(Mandatory=$true)][string]$Settings
)
$ErrorActionPreference = 'Stop'
$taskName = 'O3-Calorie-Integration-Monitor'
$taskDescription = 'O3 read-only local integration monitor; GitHub incidents; current user only.'
$pythonPath = (Resolve-Path -LiteralPath $Python).Path
$windowlessPython = Join-Path (Split-Path -Parent $pythonPath) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $windowlessPython -PathType Leaf)) {
    throw 'Monitoring requires pythonw.exe beside the supplied Python to run without console windows.'
}
$pythonPath = (Resolve-Path -LiteralPath $windowlessPython).Path
$statePath = (Resolve-Path -LiteralPath $State).Path
$settingsPath = (Resolve-Path -LiteralPath $Settings).Path
$runtimePath = Join-Path (Split-Path -Parent $settingsPath) 'runtime.py'
$sourcePath = Join-Path $PSScriptRoot 'monitor.py'
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing -and $existing.Description -ne $taskDescription) {
    throw 'Task name belongs to another installation.'
}
Copy-Item -LiteralPath $sourcePath -Destination $runtimePath
$configuration = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
$configuration | Add-Member -NotePropertyName git -NotePropertyValue (Get-Command git).Source -Force
$configuration | Add-Member -NotePropertyName docker -NotePropertyValue (Get-Command docker).Source -Force
$configuration | ConvertTo-Json | Set-Content -LiteralPath $settingsPath -Encoding UTF8
# Local state inherits the integration directory's private ACL. No credential is copied.
$arguments = '-I "{0}" once --state "{1}" --settings "{2}" --notify' -f $runtimePath,$statePath,$settingsPath
$action = New-ScheduledTaskAction -Execute $pythonPath -Argument $arguments -WorkingDirectory $configuration.checkout
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1)
$taskSettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 3)
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Description $taskDescription -Action $action -Trigger $trigger -Settings $taskSettings -Principal $principal -Force | Out-Null
$registered = Get-ScheduledTask -TaskName $taskName
if ($registered.Actions.Execute -ne $pythonPath -or $registered.Actions.Arguments -ne $arguments -or $registered.Principal.RunLevel -ne 'Limited') {
    throw 'Registered action differs from requested monitoring.'
}
Start-ScheduledTask -TaskName $taskName
@{task=$taskName; installed=$true; interval_seconds=60; elevated=$false; requires_logged_in_user=$true; console_windows=$false} | ConvertTo-Json -Compress
