@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
pwsh -NoProfile -ExecutionPolicy Bypass -File "packaging\build_installer.ps1"
if errorlevel 1 goto :error
echo 安装包已生成：dist\无忧28_Setup.exe
exit /b 0

:error
echo 安装包生成失败。
exit /b 1
