# 无忧28 Windows 部署

## 构建

在项目根目录双击 `build_exe.bat`，或在已安装依赖的虚拟环境中执行：

```powershell
python tools/create_icon.py
python -m PyInstaller --noconfirm --clean 无忧28.spec
```

输出为 `dist/无忧28/无忧28.exe`（PyInstaller onedir）。打包脚本会创建
`data/`、`config/`、`logs/`、`backup/`、`strategies/` 和 `resources/` 目录，
并运行 `--self-test`。

## 安装包

在 onedir 构建完成后执行：

```powershell
pwsh -File packaging/build_installer.ps1
```

输出为 `dist/无忧28_Setup.exe`。安装包使用 Windows 自带 IExpress 封装，安装
时可选择路径，默认 `C:\Program Files\无忧28`，并创建桌面、开始菜单快捷方式及
系统卸载项。也可以双击 `build_setup.bat` 构建。

安装器核心可以在隔离目录回归：

```powershell
pwsh -File packaging/verify_installer.ps1
```

## 运行数据

冻结版不向安装目录写入数据库、配置或日志。运行时目录为：

```text
%LOCALAPPDATA%\无忧28\
├ data\
├ config\
├ logs\
├ backup\
├ strategies\
└ resources\
```

数据库为 `data\le28.db`（仅保留历史文件名，不再使用旧采集功能），应用日志为 `logs\wuyou28.log`。卸载或更新 EXE
不会删除这些用户数据。

## 验证

```powershell
pwsh -File packaging/verify_package.ps1
```

正式图标资源为 `resources/wuyou28.svg`，EXE 使用其同源生成的
`resources/wuyou28.ico`。

需要创建桌面快捷方式时执行：

```powershell
pwsh -File packaging/create_shortcut.ps1
```

快捷方式、窗口和 EXE 使用同一个 `wuyou28.ico`，脚本不会修改应用数据目录。
