$ErrorActionPreference = 'Stop'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
$isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$payload = [ordered]@{
    is_admin = [bool]$isAdmin
    user = $identity.Name
    timestamp = (Get-Date).ToString('s')
}
$path = Join-Path $PSScriptRoot 'logs\elevated_check.json'
$payload | ConvertTo-Json | Set-Content -LiteralPath $path -Encoding UTF8
