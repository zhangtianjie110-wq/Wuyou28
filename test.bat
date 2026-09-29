@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "VENV_DIR=%LOCALAPPDATA%\Le28Predictor\venv"

if exist "%VENV_DIR%\Scripts\python.exe" (
    "%VENV_DIR%\Scripts\python.exe" -m unittest discover -s tests -v
) else (
    where py >nul 2>nul
    if %errorlevel%==0 (
        py -3 -m unittest discover -s tests -v
    ) else (
        python -m unittest discover -s tests -v
    )
)
pause
