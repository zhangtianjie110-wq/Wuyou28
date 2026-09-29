@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "VENV_DIR=%LOCALAPPDATA%\无忧28\venv"

where py >nul 2>nul
if %errorlevel%==0 (
    set "PY_CMD=py -3"
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo 未检测到 Python。请先安装 Python 3.11 或 3.12，并勾选“Add Python to PATH”。
        pause
        exit /b 1
    )
    set "PY_CMD=python"
)

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo 正在创建独立运行环境...
    %PY_CMD% -m venv "%VENV_DIR%"
    if errorlevel 1 goto :error
)

call "%VENV_DIR%\Scripts\activate.bat"
python -c "import PySide6, openpyxl" >nul 2>nul
if errorlevel 1 (
    echo 正在安装首次运行所需组件，请稍候...
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
    if errorlevel 1 goto :error
)

python main.py
exit /b %errorlevel%

:error
echo 安装或启动失败，请查看上方错误信息。
pause
exit /b 1
