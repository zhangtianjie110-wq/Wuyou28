param(
    [string]$InstallPath = "",
    [string]$DailyTime = "02:30",
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
$ProductName = (0x65E0, 0x5FE7, 0x32, 0x38 | ForEach-Object { [char]$_ }) -join ""
$TaskName = $ProductName + " Strategy AutoRunner"
$CurrentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
if ([string]::IsNullOrWhiteSpace($InstallPath)) {
    $InstallPath = Join-Path $env:ProgramFiles $ProductName
}
$Exe = Join-Path $InstallPath ($ProductName + ".exe")
$RuntimeRoot = Join-Path $env:LOCALAPPDATA $ProductName
$LogDir = Join-Path $RuntimeRoot "logs"
$SetupLog = Join-Path $LogDir "strategy_task_setup.log"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-SetupLog([string]$Message) {
    Add-Content -LiteralPath $SetupLog -Encoding UTF8 -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message"
}

if (-not (Get-Command Register-ScheduledTask -ErrorAction SilentlyContinue)) {
    throw "ScheduledTasks cmdlets are unavailable on this Windows host"
}

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-SetupLog "REMOVE task=$TaskName"
    Write-Host "STRATEGY_AUTORUN = REMOVED"
    exit 0
}

if (-not (Test-Path -LiteralPath $Exe)) {
    throw "EXE not found: $Exe"
}
if ($DailyTime -notmatch '^([01]\d|2[0-3]):[0-5]\d$') {
    throw "DailyTime must use HH:mm format"
}

$Hour = [int]$DailyTime.Substring(0, 2)
$Minute = [int]$DailyTime.Substring(3, 2)
$DailyAt = (Get-Date).Date.AddHours($Hour).AddMinutes($Minute)
$Action = New-ScheduledTaskAction `
    -Execute $Exe `
    -Argument "--strategy-auto-run" `
    -WorkingDirectory $InstallPath
$StartupTrigger = New-ScheduledTaskTrigger -AtStartup
$StartupTrigger.Delay = "PT2M"
$DailyTrigger = New-ScheduledTaskTrigger -Daily -At $DailyAt
$Principal = New-ScheduledTaskPrincipal `
    -UserId $CurrentUser `
    -LogonType S4U `
    -RunLevel Highest
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 4)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger @($StartupTrigger, $DailyTrigger) `
    -Principal $Principal `
    -Settings $Settings `
    -Description "$ProductName 每日策略实验，只读分析 VIP100_HISTORY" `
    -Force | Out-Null

$Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
Write-SetupLog "REGISTER task=$TaskName user=$CurrentUser startupDelay=PT2M daily=$DailyTime restartCount=3 exe=$Exe"
Write-Host "STRATEGY_AUTORUN = PASS"
Write-Host "TASK = $TaskName"
Write-Host "STATE = $($Task.State)"
Write-Host "DAILY_TIME = $DailyTime"
Write-Host "LOG = $SetupLog"
