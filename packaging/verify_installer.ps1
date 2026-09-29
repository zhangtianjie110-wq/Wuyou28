$ErrorActionPreference = "Stop"
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]$identity
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run verify_installer.ps1 from an elevated PowerShell; the installer writes HKLM uninstall metadata."
}
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$stage = Join-Path $root "build\installer_payload"
$installer = Join-Path $stage "install_wuyou28.ps1"
if (-not (Test-Path -LiteralPath $installer)) { throw "Build the installer first" }

$product = (0x65E0, 0x5FE7, 0x32, 0x38 | ForEach-Object { [char]$_ }) -join ""
$install = Join-Path $env:TEMP ("wuyou28-verify-" + [guid]::NewGuid().ToString("N"))
$exe = Join-Path $install ($product + ".exe")
$reg = "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$product"
$userLink = Join-Path ([Environment]::GetFolderPath("Desktop")) ($product + ".lnk")
$startLink = Join-Path ([Environment]::GetFolderPath("CommonPrograms")) ($product + "\" + $product + ".lnk")

& $installer -InstallPath $install -Silent
if ($LASTEXITCODE -ne 0) { throw "Install failed with exit code $LASTEXITCODE" }
if (-not (Test-Path -LiteralPath $exe)) { throw "Installed EXE is missing" }
$process = Start-Process -FilePath $exe -ArgumentList "--self-test" -Wait -PassThru
if ($process.ExitCode -ne 0) { throw "Installed EXE self-test failed" }
if (-not (Test-Path -LiteralPath $reg)) { throw "Uninstall registry entry is missing" }
if (-not (Test-Path -LiteralPath $userLink)) { throw "Desktop shortcut is missing" }
if (-not (Test-Path -LiteralPath $startLink)) { throw "Start Menu shortcut is missing" }

& (Join-Path $install "uninstall_wuyou28.ps1") -InstallPath $install -Silent
if ($LASTEXITCODE -ne 0) { throw "Uninstall failed with exit code $LASTEXITCODE" }
Start-Sleep -Seconds 3
if (Test-Path -LiteralPath $install) { throw "Install directory was not removed" }
if (Test-Path -LiteralPath $reg) { throw "Uninstall registry entry remains" }
if (Test-Path -LiteralPath $userLink) { throw "Desktop shortcut remains" }
if (Test-Path -LiteralPath $startLink) { throw "Start Menu shortcut remains" }
Write-Host "INSTALLER_VERIFY = PASS"
