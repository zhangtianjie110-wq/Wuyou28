# Build only the independent UI. Do not launch or control backend services.
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
$buildOriginalPath = $env:PATH
try {
    # Poppler's icuuc.dll on the inherited Codex PATH is incompatible with
    # Qt's Windows ICU imports. Limit discovery to Python, Qt and Windows.
    $buildPythonRoot = (& .venv\Scripts\python.exe -c 'import sys; print(sys.base_prefix)').Trim()
    $env:PATH = "$PSScriptRoot\.venv\Scripts;$PSScriptRoot\.venv\Lib\site-packages\PySide6;$buildPythonRoot;$buildPythonRoot\DLLs;$env:SystemRoot\System32;$env:SystemRoot"
    & .venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed --name 无忧28 --distpath dist_ui_diy --workpath build_ui_diy/build --specpath build_ui_diy frontend.py
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
    New-Item -ItemType Directory -Path 'dist_ui_diy\无忧28\ui\config' -Force | Out-Null
    Copy-Item -LiteralPath 'app\ui\config\ui_theme.json','app\ui\config\ui_layout.json','app\ui\config\ui_components.json' -Destination 'dist_ui_diy\无忧28\ui\config'
} finally {
    $env:PATH = $buildOriginalPath
    Pop-Location
}
