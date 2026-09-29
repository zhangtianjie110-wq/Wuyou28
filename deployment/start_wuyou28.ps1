param(
    [string]$InstallPath = "",
    [switch]$SelfTest,
    [switch]$Wait,
    [string]$Reason = "manual"
)

$ErrorActionPreference = "Stop"
$ProductName = (0x65E0, 0x5FE7, 0x32, 0x38 | ForEach-Object { [char]$_ }) -join ""
$ProductVersion = "0.6.0"
if ([string]::IsNullOrWhiteSpace($InstallPath)) {
    $InstallPath = Join-Path $env:ProgramFiles $ProductName
}
$exe = Join-Path $InstallPath ($ProductName + ".exe")
$runtimeRoot = Join-Path $env:LOCALAPPDATA $ProductName
$logDir = Join-Path $runtimeRoot "logs"
$logPath = Join-Path $logDir "vps_start.log"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
function Write-StartLog([string]$Message) {
    Add-Content -LiteralPath $logPath -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message"
}

try {
    if (-not (Test-Path -LiteralPath $exe)) {
        throw "EXE not found: $exe"
    }
    $versionInfo = (Get-Item -LiteralPath $exe).VersionInfo
    $fileVersion = [string]$versionInfo.ProductVersion
    if ([string]::IsNullOrWhiteSpace($fileVersion)) { $fileVersion = [string]$versionInfo.ProductVersionRaw }
    if (-not [string]::IsNullOrWhiteSpace($fileVersion)) { $ProductVersion = $fileVersion }
    $arguments = @()
    if ($SelfTest) { $arguments += "--self-test" }
    Write-StartLog "START version=$ProductVersion reason=$Reason exe=$exe"

    $startParameters = @{
        FilePath = $exe
        WorkingDirectory = $InstallPath
        PassThru = $true
        Wait = [bool]$Wait
    }
    if ($arguments.Count -gt 0) {
        $startParameters.ArgumentList = $arguments
    }
    $process = Start-Process @startParameters
    Write-StartLog "STARTED pid=$($process.Id) wait=$Wait exit=$($process.ExitCode)"
    Write-Host "START = PASS"
    Write-Host "PID = $($process.Id)"
    Write-Host "VERSION = $ProductVersion"
    Write-Host "LOG = $logPath"
    if ($Wait -and $process.ExitCode -ne 0) { exit $process.ExitCode }
    exit 0
}
catch {
    Write-StartLog "START_FAILED version=$ProductVersion reason=$Reason error=$($_.Exception.Message)"
    Write-Error $_
    exit 1
}
