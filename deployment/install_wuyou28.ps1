param(
    [string]$InstallerPath = "",
    [string]$InstallPath = "",
    [string]$PackageDirectory = "",
    [switch]$Silent
)

$ErrorActionPreference = "Stop"
$ProductName = (0x65E0, 0x5FE7, 0x32, 0x38 | ForEach-Object { [char]$_ }) -join ""
if ([string]::IsNullOrWhiteSpace($InstallPath)) { $InstallPath = Join-Path $env:ProgramFiles $ProductName }
$runtimeRoot = Join-Path $env:LOCALAPPDATA $ProductName

$windows = [Environment]::OSVersion.Version
if ($windows.Major -lt 10) { throw "Windows 10 or Windows Server 2016+ is required" }
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]$identity
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this deployment script from an elevated PowerShell" }

foreach ($name in @("data", "config", "logs", "backup", "strategies", "resources")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $runtimeRoot $name) | Out-Null
}

if (-not [string]::IsNullOrWhiteSpace($PackageDirectory)) {
    $package = (Resolve-Path $PackageDirectory).Path
    if (@(Get-ChildItem -LiteralPath $package -Filter "*.exe" -File).Count -eq 0) { throw "Package directory has no EXE" }
    New-Item -ItemType Directory -Force -Path $InstallPath | Out-Null
    Copy-Item -Path (Join-Path $package "*") -Destination $InstallPath -Recurse -Force
    Write-Host "PROGRAM_FILES_INSTALL = PASS"
} else {
    if ([string]::IsNullOrWhiteSpace($InstallerPath)) { $InstallerPath = Join-Path $PSScriptRoot "无忧28_Setup.exe" }
    if (-not (Test-Path -LiteralPath $InstallerPath)) { throw "Installer not found: $InstallerPath" }
    $installerArgs = @()
    if ($Silent) { $installerArgs += "/S" }
    # NSIS requires /D=... to be the final installer argument.
    if (-not [string]::IsNullOrWhiteSpace($InstallPath)) { $installerArgs += "/D=$InstallPath" }
    $startParameters = @{
        FilePath = $InstallerPath
        Wait = $true
        PassThru = $true
    }
    if ($installerArgs.Count -gt 0) {
        $startParameters.ArgumentList = $installerArgs
    }
    $process = Start-Process @startParameters
    if ($process.ExitCode -ne 0) { throw "Installer failed with exit code $($process.ExitCode)" }
    Write-Host "SETUP_INSTALL = PASS"
}

Write-Host "RUNTIME_ROOT = $runtimeRoot"
