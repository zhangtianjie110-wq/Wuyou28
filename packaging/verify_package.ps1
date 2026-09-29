param(
    [string]$Package = ""
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($Package)) {
    $distRoot = Join-Path $PSScriptRoot "..\dist"
    $candidate = Get-ChildItem -LiteralPath $distRoot -Directory |
        Where-Object {
            @(Get-ChildItem -LiteralPath $_.FullName -Filter "*.exe" -File).Count -gt 0 -and
            (Test-Path -LiteralPath (Join-Path $_.FullName "resources\wuyou28.ico"))
        } |
        Select-Object -First 1
    if ($null -eq $candidate) { throw "No package directory containing an EXE was found" }
    $Package = $candidate.FullName
}

$exe = Get-ChildItem -LiteralPath $Package -Filter "*.exe" -File | Select-Object -First 1
if ($null -eq $exe) { throw "Package is missing an EXE: $Package" }

foreach ($name in @("data", "config", "logs", "backup", "strategies", "resources")) {
    $path = Join-Path $Package $name
    if (-not (Test-Path -LiteralPath $path)) { throw "Missing deployment directory: $path" }
}

$icon = Join-Path $Package "resources\wuyou28.ico"
if (-not (Test-Path -LiteralPath $icon)) { throw "Missing icon: $icon" }

$process = Start-Process -FilePath $exe.FullName -ArgumentList "--self-test" -Wait -PassThru
if ($process.ExitCode -ne 0) { throw "EXE self-test failed with exit code $($process.ExitCode)" }
Write-Host "PACKAGE_VERIFY = PASS"
Write-Host "EXE: $($exe.FullName)"
