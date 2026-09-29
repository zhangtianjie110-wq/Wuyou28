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
    if ($null -eq $candidate) { throw "No package directory with the bundled icon was found" }
    $Package = $candidate.FullName
}

$exe = Get-ChildItem -LiteralPath $Package -Filter "*.exe" -File | Select-Object -First 1
if ($null -eq $exe) { throw "Package is missing an EXE: $Package" }
$icon = Join-Path $Package "resources\wuyou28.ico"
if (-not (Test-Path -LiteralPath $icon)) { throw "Package is missing the icon: $icon" }

$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop ($exe.BaseName + ".lnk")
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $exe.FullName
$shortcut.WorkingDirectory = $Package
$shortcut.IconLocation = "$icon,0"
$shortcut.Description = $exe.BaseName
$shortcut.Save()

Write-Host "SHORTCUT_CREATED = PASS"
Write-Host "Shortcut: $shortcutPath"
