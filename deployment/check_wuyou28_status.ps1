param(
    [string]$InstallPath = "",
    [switch]$Json,
    [switch]$FailIfNotRunning
)

$ErrorActionPreference = "Stop"
$ProductName = (0x65E0, 0x5FE7, 0x32, 0x38 | ForEach-Object { [char]$_ }) -join ""
if ([string]::IsNullOrWhiteSpace($InstallPath)) {
    $InstallPath = Join-Path $env:ProgramFiles $ProductName
}
$exe = Join-Path $InstallPath ($ProductName + ".exe")
$runtimeRoot = Join-Path $env:LOCALAPPDATA $ProductName
$taskName = $ProductName + " AutoStart"
$strategyTaskName = $ProductName + " Strategy AutoRunner"
$version = $null
if (Test-Path -LiteralPath $exe) {
    $versionInfo = (Get-Item -LiteralPath $exe).VersionInfo
    $version = [string]$versionInfo.ProductVersion
    if ([string]::IsNullOrWhiteSpace($version)) { $version = [string]$versionInfo.ProductVersionRaw }
}

$processes = @()
Get-Process -ErrorAction SilentlyContinue | ForEach-Object {
    try {
        if ([string]::Equals($_.Path, $exe, [StringComparison]::OrdinalIgnoreCase)) {
            $processes += $_
        }
    } catch {
        # Access to another process path can be denied on Server editions.
    }
}

$taskState = "Missing"
$taskLastRun = $null
$taskLastResult = $null
$strategyTaskState = "Missing"
$strategyTaskLastRun = $null
$strategyTaskLastResult = $null
if (Get-Command Get-ScheduledTask -ErrorAction SilentlyContinue) {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($task) {
        $taskState = [string]$task.State
        $taskInfo = Get-ScheduledTaskInfo -TaskName $taskName -ErrorAction SilentlyContinue
        if ($taskInfo) {
            $taskLastRun = $taskInfo.LastRunTime
            $taskLastResult = $taskInfo.LastTaskResult
        }
    }
    $strategyTask = Get-ScheduledTask -TaskName $strategyTaskName -ErrorAction SilentlyContinue
    if ($strategyTask) {
        $strategyTaskState = [string]$strategyTask.State
        $strategyTaskInfo = Get-ScheduledTaskInfo -TaskName $strategyTaskName -ErrorAction SilentlyContinue
        if ($strategyTaskInfo) {
            $strategyTaskLastRun = $strategyTaskInfo.LastRunTime
            $strategyTaskLastResult = $strategyTaskInfo.LastTaskResult
        }
    }
}

$logDir = Join-Path $runtimeRoot "logs"
$reportDir = Join-Path $runtimeRoot "reports\strategy_daily"
$latestReport = $null
if (Test-Path -LiteralPath $reportDir) {
    $latestReport = Get-ChildItem -LiteralPath $reportDir -Filter "*_report.json" -File |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1 -ExpandProperty FullName
}
$status = [pscustomobject]@{
    Product = $ProductName
    Version = $version
    InstallPath = $InstallPath
    ExecutableExists = (Test-Path -LiteralPath $exe)
    ProcessRunning = ($processes.Count -gt 0)
    ProcessIds = @($processes | ForEach-Object Id)
    TaskName = $taskName
    TaskState = $taskState
    TaskLastRun = $taskLastRun
    TaskLastResult = $taskLastResult
    StrategyTaskName = $strategyTaskName
    StrategyTaskState = $strategyTaskState
    StrategyTaskLastRun = $strategyTaskLastRun
    StrategyTaskLastResult = $strategyTaskLastResult
    RuntimeRoot = $runtimeRoot
    LogsDirectoryExists = (Test-Path -LiteralPath $logDir)
    ApplicationLog = (Join-Path $logDir "wuyou28.log")
    StartupLog = (Join-Path $logDir "vps_start.log")
    StrategyRunnerLog = (Join-Path $logDir "strategy_runner.log")
    LatestStrategyReport = $latestReport
    CheckedAt = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
}

if ($Json) {
    $status | ConvertTo-Json -Depth 4
} else {
    $status | Format-List
}

if ($FailIfNotRunning -and (-not $status.ExecutableExists -or -not $status.ProcessRunning)) {
    exit 2
}
exit 0
