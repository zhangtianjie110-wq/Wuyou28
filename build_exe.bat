@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "VENV_DIR=%LOCALAPPDATA%\无忧28\venv"

if not exist "%VENV_DIR%\Scripts\python.exe" if exist ".venv\Scripts\python.exe" set "VENV_DIR=%CD%\.venv"

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo 请先双击 run.bat，完成运行环境安装。
    pause
    exit /b 1
)

set "PYTHON=%VENV_DIR%\Scripts\python.exe"
if exist "%VENV_DIR%\Scripts\activate.bat" call "%VENV_DIR%\Scripts\activate.bat"
"%PYTHON%" -c "import PySide6, PyInstaller, openpyxl" >nul 2>&1
if errorlevel 1 (
    "%PYTHON%" -m pip install -r requirements.txt
    if errorlevel 1 goto :error
) else (
    echo 依赖已可用，跳过 pip 安装步骤。
)

echo 正在执行编译检查...
"%PYTHON%" -m compileall -q app main.py tools
if errorlevel 1 goto :error

echo 正在生成无忧28图标...
"%PYTHON%" tools\create_icon.py
if errorlevel 1 goto :error

echo 正在打包 Windows EXE...
"%PYTHON%" -m PyInstaller --noconfirm --clean "无忧28.spec"
if errorlevel 1 goto :error

rem PyInstaller 在部分 Codex Python 环境中会误收集 ICU 78，覆盖 Windows 系统 ICU，
rem 导致 PySide6.QtCore 报 WinError 127。Qt 6 在 Windows 上应使用系统 icuuc.dll。
if exist "dist\无忧28\_internal\icuuc.dll" ren "dist\无忧28\_internal\icuuc.dll" "icuuc.dll.disabled"
if exist "dist\无忧28\_internal\icudt78.dll" ren "dist\无忧28\_internal\icudt78.dll" "icudt78.dll.disabled"

rem Keep a visible deployment layout beside the onedir executable. Mutable
rem runtime state is redirected to %%LOCALAPPDATA%%\无忧28 by app.constants.
for %%D in (data config logs backup strategies resources) do if not exist "dist\无忧28\%%D" mkdir "dist\无忧28\%%D"
copy /Y "resources\wuyou28.svg" "dist\无忧28\resources\wuyou28.svg" >nul
copy /Y "resources\wuyou28.ico" "dist\无忧28\resources\wuyou28.ico" >nul
if exist "dist\无忧28\无忧28.exe" (
    echo 正在运行打包自检...
    "dist\无忧28\无忧28.exe" --self-test
    if errorlevel 1 goto :error
)

echo.
echo 打包完成：dist\无忧28\无忧28.exe
echo 用户数据目录：%%LOCALAPPDATA%%\无忧28
pause
exit /b 0

:error
echo 打包失败，请查看上方错误信息。
pause
exit /b 1
