param(
    [string]$DistDirectory = "",
    [string]$OutputDirectory = ""
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$productName = "无忧28"
$versionFile = Join-Path $root "resources\version.json"
$versionPayload = Get-Content -LiteralPath $versionFile -Raw -Encoding UTF8 | ConvertFrom-Json
$version = [string]$versionPayload.version
if ($version -notmatch '^\d+\.\d+\.\d+$') {
    throw "版本号无效: $versionFile ($version)"
}
$fileVersion = "$version.0"

if ([string]::IsNullOrWhiteSpace($DistDirectory)) {
    $DistDirectory = Join-Path $root "dist\无忧28"
}
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $root "dist"
}

$dist = (Resolve-Path -LiteralPath $DistDirectory).Path
$output = New-Item -ItemType Directory -Force -Path $OutputDirectory
$exe = Join-Path $dist "$productName.exe"
$icon = Join-Path $dist "resources\wuyou28.ico"
if (-not (Test-Path -LiteralPath $exe)) {
    throw "正式 EXE 不存在: $exe"
}
if (-not (Test-Path -LiteralPath $icon)) {
    throw "正式图标不存在: $icon"
}
$exeHash = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToUpperInvariant()

$makensis = $null
$command = Get-Command makensis.exe -ErrorAction SilentlyContinue
if ($command) {
    $makensis = $command.Source
}
if (-not $makensis) {
    $candidates = @(
        "${env:ProgramFiles(x86)}\NSIS\makensis.exe",
        "$env:ProgramFiles\NSIS\makensis.exe"
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
    $makensis = $candidates | Select-Object -First 1
}
if (-not $makensis) {
    throw "未找到 NSIS makensis.exe。请安装 NSIS 3.x。"
}

$script = Join-Path $PSScriptRoot "wuyou28.nsi"
$final = Join-Path $output ($productName + "_Setup.exe")
if (Test-Path -LiteralPath $final) {
    Remove-Item -LiteralPath $final -Force
}

& $makensis "/DPRODUCT_ROOT=$dist" "/DOUTPUT_EXE=$final" "/DPRODUCT_VERSION=$version" "/DPRODUCT_FILE_VERSION=$fileVersion" "/DPRODUCT_EXE_SHA256=$exeHash" $script
if ($LASTEXITCODE -ne 0) {
    throw "NSIS 构建失败，退出码: $LASTEXITCODE"
}
if (-not (Test-Path -LiteralPath $final)) {
    throw "NSIS 未生成安装包: $final"
}

Write-Host "INSTALLER_BUILD = PASS"
Write-Host "INSTALLER_ENGINE = NSIS"
Write-Host "VERSION = $version"
Write-Host "SETUP = $final"
