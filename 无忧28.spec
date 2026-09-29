# -*- mode: python ; coding: utf-8 -*-


import json
from pathlib import Path
import re

ROOT = Path(SPECPATH)
VERSION_FILE = ROOT / 'resources' / 'version.json'
VERSION_PAYLOAD = json.loads(VERSION_FILE.read_text(encoding='utf-8-sig'))
VERSION = str(VERSION_PAYLOAD.get('version', '')).strip()
VERSION_MATCH = re.fullmatch(r'(\d+)\.(\d+)\.(\d+)', VERSION)
if VERSION_MATCH is None:
    raise ValueError(f'Invalid release version in {VERSION_FILE}: {VERSION!r}')
VERSION_PARTS = tuple(int(value) for value in VERSION_MATCH.groups()) + (0,)
VERSION_INFO = ROOT / 'build' / 'generated_version_info.txt'
VERSION_INFO.parent.mkdir(parents=True, exist_ok=True)
VERSION_INFO.write_text(
    f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={VERSION_PARTS},
    prodvers={VERSION_PARTS},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('080404b0', [
        StringStruct('CompanyName', '无忧28'),
        StringStruct('FileDescription', '无忧28桌面应用'),
        StringStruct('FileVersion', '{VERSION}'),
        StringStruct('InternalName', 'wuyou28'),
        StringStruct('OriginalFilename', '无忧28.exe'),
        StringStruct('ProductName', '无忧28'),
        StringStruct('ProductVersion', '{VERSION}')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
""",
    encoding='utf-8',
)

a = Analysis(
    ['main.py'],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[(str(ROOT / 'resources'), 'resources')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# ucrtbase.dll is a Windows runtime component.  A third-party image bundle
# exposes a copy, but shipping that duplicate causes Windows/Defender to deny
# PyInstaller's collect step.  Keep the system runtime out of the payload.
collect_binaries = [entry for entry in a.binaries if entry[0].lower() != 'ucrtbase.dll']

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='无忧28',
    icon=str(ROOT / 'resources' / 'wuyou28.ico'),
    version=str(VERSION_INFO),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    collect_binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='无忧28',
)
