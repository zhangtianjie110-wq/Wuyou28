param(
    [string]$InstallPath = "",
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
$ProductName = (0x65E0, 0x5FE7, 0x32, 0x38 | ForEach-Object { [char]$_ }) -join ""
$currentIdentity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
$currentUser = $currentIdentity.Name
if ([string]::IsNullOrWhiteSpace($currentUser)) {
    throw "Unable to resolve the current Windows user"
}
if ([string]::IsNullOrWhiteSpace($InstallPath)) {
    $InstallPath = Join-Path $env:ProgramFiles $ProductName
}
$exe = Join-Path $InstallPath ($ProductName + ".exe")
$taskName = $ProductName + " AutoStart"
$runtimeRoot = Join-Path $env:LOCALAPPDATA $ProductName
$logDir = Join-Path $runtimeRoot "logs"
$logPath = Join-Path $logDir "autostart.log"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
function Write-AutostartLog([string]$Message) {
    Add-Content -LiteralPath $logPath -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message"
}

if (-not (Get-Command Register-ScheduledTask -ErrorAction SilentlyContinue)) {
    throw "ScheduledTasks cmdlets are unavailable on this Windows host"
}

if ($Remove) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-AutostartLog "REMOVE task=$taskName user=$currentUser"
    Write-Host "AUTOSTART = REMOVED"
    exit 0
}

if (-not (Test-Path -LiteralPath $exe)) { throw "EXE not found: $exe" }
$runnerSource = Join-Path $PSScriptRoot "start_wuyou28.ps1"
if (-not (Test-Path -LiteralPath $runnerSource)) { throw "Startup runner not found: $runnerSource" }
$runnerTarget = Join-Path $runtimeRoot "start_wuyou28.ps1"
Copy-Item -LiteralPath $runnerSource -Destination $runnerTarget -Force

$versionInfo = (Get-Item -LiteralPath $exe).VersionInfo
$version = [string]$versionInfo.ProductVersion
if ([string]::IsNullOrWhiteSpace($version)) { $version = [string]$versionInfo.ProductVersionRaw }
if ([string]::IsNullOrWhiteSpace($version)) { $version = "0.6.0" }
$powershell = Join-Path $env:WINDIR "System32\WindowsPowerShell\v1.0\powershell.exe"
$arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$runnerTarget`" -InstallPath `"$InstallPath`" -Reason scheduled-task"
$action = New-ScheduledTaskAction -Execute $powershell -Argument $arguments -WorkingDirectory $InstallPath

# GUI applications must start in the logged-in RDP user's interactive desktop.
# AtStartup runs in session 0 on Server 2022 and can leave the GUI process
# detached or immediately terminated, so the task is intentionally logon-only.
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $currentUser
$trigger.Delay = "PT30S"
$principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

# Remove an older definition first so obsolete AtStartup/non-interactive
# triggers cannot survive a forced update on an existing VPS installation.
$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($null -ne $existingTask) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-AutostartLog "REPLACE_OLD_TASK task=$taskName"
}

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "$ProductName $version VPS 自动启动" -Force | Out-Null
$registeredTask = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop

Write-AutostartLog "REGISTER task=$taskName version=$version user=$currentUser logonType=Interactive runLevel=Highest trigger=AtLogOn delay=PT30S action=$powershell runner=$runnerTarget"
Write-AutostartLog "CONTEXT sessionName=$env:SESSIONNAME sessionId=$env:SESSIONID computer=$env:COMPUTERNAME"
Write-AutostartLog "REGISTERED state=$($registeredTask.State) taskPath=$($registeredTask.TaskPath)"
Write-Host "AUTOSTART = PASS"
Write-Host "TASK = $taskName"
Write-Host "VERSION = $version"
Write-Host "LOG = $logPath"
