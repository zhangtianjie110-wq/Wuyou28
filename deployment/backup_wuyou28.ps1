param(
    [string]$RuntimeRoot = "",
    [int]$KeepDays = 30
)

$ErrorActionPreference = "Stop"
$ProductName = (0x65E0, 0x5FE7, 0x32, 0x38 | ForEach-Object { [char]$_ }) -join ""
if ([string]::IsNullOrWhiteSpace($RuntimeRoot)) { $RuntimeRoot = Join-Path $env:LOCALAPPDATA $ProductName }
$backupRoot = Join-Path $RuntimeRoot "backup"
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$destination = Join-Path $backupRoot $stamp
New-Item -ItemType Directory -Force -Path $destination | Out-Null

foreach ($sourceName in @("data", "config", "strategies")) {
    $source = Join-Path $RuntimeRoot $sourceName
    if (Test-Path -LiteralPath $source) {
        Copy-Item -LiteralPath $source -Destination $destination -Recurse -Force
    }
}

if ($KeepDays -gt 0) {
    $cutoff = (Get-Date).AddDays(-$KeepDays)
    Get-ChildItem -LiteralPath $backupRoot -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -lt $cutoff } |
        Remove-Item -Recurse -Force
}
Write-Host "BACKUP = PASS"
Write-Host "DESTINATION = $destination"
