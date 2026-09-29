Unicode True
RequestExecutionLevel admin
ManifestSupportedOS win10

!include "StrFunc.nsh"
${Using:StrFunc} StrStr

!ifndef PRODUCT_ROOT
  !define PRODUCT_ROOT "..\dist\无忧28"
!endif
!ifndef OUTPUT_EXE
  !define OUTPUT_EXE "..\dist\无忧28_Setup.exe"
!endif

!define PRODUCT_NAME "无忧28"
!ifndef PRODUCT_VERSION
  !error "PRODUCT_VERSION must be supplied by build_installer.ps1"
!endif
!ifndef PRODUCT_FILE_VERSION
  !error "PRODUCT_FILE_VERSION must be supplied by build_installer.ps1"
!endif
!ifndef PRODUCT_EXE_SHA256
  !error "PRODUCT_EXE_SHA256 must be supplied by build_installer.ps1"
!endif
!define UNINSTALL_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCT_NAME}"

Var InstallLog
Var LogHandle

Name "${PRODUCT_NAME}"
OutFile "${OUTPUT_EXE}"
InstallDir "$PROGRAMFILES64\${PRODUCT_NAME}"
InstallDirRegKey HKLM "${UNINSTALL_KEY}" "InstallLocation"
Icon "${PRODUCT_ROOT}\resources\wuyou28.ico"
UninstallIcon "${PRODUCT_ROOT}\resources\wuyou28.ico"
SetCompressor /SOLID lzma
CRCCheck on
ShowInstDetails show
ShowUninstDetails show

VIProductVersion "${PRODUCT_FILE_VERSION}"
VIAddVersionKey "ProductName" "${PRODUCT_NAME}"
VIAddVersionKey "ProductVersion" "${PRODUCT_VERSION}"
VIAddVersionKey "FileVersion" "${PRODUCT_VERSION}"
VIAddVersionKey "FileDescription" "${PRODUCT_NAME} Windows 安装程序"
VIAddVersionKey "CompanyName" "无忧28"
VIAddVersionKey "LegalCopyright" "Copyright (c) 2026"

Page directory
Page instfiles
UninstPage uninstConfirm
UninstPage instfiles

Function LogLine
  Exch $0
  FileWrite $LogHandle "$0$\r$\n"
  Pop $0
FunctionEnd

Function InstallationFailure
  Exch $0
  Push "INSTALL=FAIL $0"
  Call LogLine
  FileClose $LogHandle
  StrCpy $2 "$InstallLog"
  ReadEnvStr $1 "LOCALAPPDATA"
  StrCmp $1 "" failure_log_temp failure_log_local
failure_log_local:
  CreateDirectory "$1\无忧28"
  CreateDirectory "$1\无忧28\logs"
  FileOpen $3 "$InstallLog" r
  IfErrors failure_log_ready
  FileOpen $4 "$1\无忧28\logs\wuyou28_install.log" w
  IfErrors failure_log_close_source
  StrCpy $2 "$1\无忧28\logs\wuyou28_install.log"
failure_log_copy_loop:
  ClearErrors
  FileRead $3 $5
  IfErrors failure_log_close_both
  FileWrite $4 $5
  Goto failure_log_copy_loop
failure_log_close_both:
  FileClose $4
failure_log_close_source:
  FileClose $3
  Goto failure_log_ready
failure_log_temp:
  StrCpy $2 "$InstallLog"
failure_log_ready:
  MessageBox MB_ICONSTOP "$0$\r$\n日志：$2"
  Pop $0
  SetErrorLevel 1
  Abort
FunctionEnd

Section "Install"
  SetRegView 64
  StrCpy $InstallLog "$TEMP\wuyou28_install.log"
  Delete "$InstallLog"
  FileOpen $LogHandle "$InstallLog" w
  Push "START $(^Name)"
  Call LogLine

  ; Keep the NSIS shell context explicit and record its resolved paths. The
  ; environment paths below are deterministic on Windows Server 2022 even
  ; when UAC runs the installer under a different administrator token.
  SetShellVarContext all
  Push "ShellVarContext=all"
  Call LogLine
  Push "DESKTOP=$DESKTOP"
  Call LogLine
  Push "SMPROGRAMS=$SMPROGRAMS"
  Call LogLine

  ; Preserve the PyInstaller onedir layout exactly. Each SetOutPath applies
  ; only to the files that follow it, keeping the launcher in the install
  ; root and dependencies inside _internal.
  SetOutPath "$INSTDIR"
  File /oname=无忧28.exe "${PRODUCT_ROOT}\无忧28.exe"

  SetOutPath "$INSTDIR\_internal"
  File /r "${PRODUCT_ROOT}\_internal\*"

  SetOutPath "$INSTDIR\resources"
  File /r "${PRODUCT_ROOT}\resources\*"

  SetOutPath "$INSTDIR"
  IfFileExists "$INSTDIR\无忧28.exe" exe_present exe_missing
exe_present:
  Push "MAIN_EXE=PASS ($INSTDIR\无忧28.exe)"
  Call LogLine
  Goto exe_check_done
exe_missing:
  Push "MAIN_EXE=FAIL ($INSTDIR\无忧28.exe)"
  Call LogLine
  Push "安装文件缺少无忧28.exe。请检查安装包或安全软件隔离记录。"
  Call InstallationFailure
exe_check_done:
  ; These runtime directories may be empty in a fresh distribution. Create
  ; them at install time so the expected deployment layout is always present.
  CreateDirectory "$INSTDIR\backup"
  CreateDirectory "$INSTDIR\config"
  CreateDirectory "$INSTDIR\data"
  CreateDirectory "$INSTDIR\logs"
  CreateDirectory "$INSTDIR\strategies"

  ; Verify the extracted launcher against the hash captured at build time.
  ; certutil is part of Windows 10/Server 2022 and avoids extra plugins.
  ClearErrors
  nsExec::ExecToStack '"$SYSDIR\certutil.exe" -hashfile "$INSTDIR\无忧28.exe" SHA256'
  Pop $0
  Pop $1
  StrCmp $0 "0" exe_hash_output_ok exe_hash_command_fail
exe_hash_output_ok:
  ${StrStr} $2 $1 "${PRODUCT_EXE_SHA256}"
  StrCmp $2 "" exe_hash_failed exe_hash_pass
exe_hash_pass:
  Push "EXE_HASH=PASS (${PRODUCT_EXE_SHA256})"
  Call LogLine
  Goto exe_hash_done
exe_hash_command_fail:
  Push "EXE_HASH=ERROR code=$0 output=$1"
  Call LogLine
  Push "无法校验无忧28.exe完整性，可能已被安全软件拦截。"
  Call InstallationFailure
  Goto exe_hash_done
exe_hash_failed:
  Push "EXE_HASH=FAIL expected=${PRODUCT_EXE_SHA256} output=$1"
  Call LogLine
  Push "无忧28.exe完整性校验失败，文件可能被修改或隔离。"
  Call InstallationFailure
exe_hash_done:

  ; Run the packaged self-test so launch blocking is detected during install.
  ClearErrors
  ExecWait '"$INSTDIR\无忧28.exe" --self-test' $0
  IfErrors startup_exec_failed startup_exit_check
startup_exit_check:
  StrCmp $0 "0" startup_check_pass startup_exit_failed
startup_check_pass:
  Push "STARTUP_CHECK=PASS"
  Call LogLine
  Goto startup_check_done
startup_exec_failed:
  Push "STARTUP_CHECK=FAIL launch_error"
  Call LogLine
  Push "无忧28启动失败，可能被 360、AlibabaProtect 或其他安全软件拦截。"
  Call InstallationFailure
  Goto startup_check_done
startup_exit_failed:
  Push "STARTUP_CHECK=FAIL exit_code=$0"
  Call LogLine
  Push "无忧28自检启动失败，退出码：$0。"
  Call InstallationFailure
startup_check_done:

  WriteUninstaller "$INSTDIR\Uninstall.exe"

  CreateDirectory "$DESKTOP"
  CreateDirectory "$SMPROGRAMS\${PRODUCT_NAME}"
  CreateShortCut "$DESKTOP\${PRODUCT_NAME}.lnk" "$INSTDIR\${PRODUCT_NAME}.exe" "" "$INSTDIR\resources\wuyou28.ico" 0
  IfFileExists "$DESKTOP\${PRODUCT_NAME}.lnk" desktop_shortcut_ok desktop_shortcut_fail
desktop_shortcut_ok:
  Push "CreateShortCut Desktop=PASS ($DESKTOP\${PRODUCT_NAME}.lnk)"
  Call LogLine
  Goto desktop_shortcut_done
desktop_shortcut_fail:
  Push "CreateShortCut Desktop=FAIL ($DESKTOP\${PRODUCT_NAME}.lnk)"
  Call LogLine
  FileClose $LogHandle
  MessageBox MB_ICONSTOP "无法创建桌面快捷方式。日志：$InstallLog"
  Abort
desktop_shortcut_done:

  CreateShortCut "$SMPROGRAMS\${PRODUCT_NAME}\${PRODUCT_NAME}.lnk" "$INSTDIR\${PRODUCT_NAME}.exe" "" "$INSTDIR\resources\wuyou28.ico" 0
  IfFileExists "$SMPROGRAMS\${PRODUCT_NAME}\${PRODUCT_NAME}.lnk" start_shortcut_ok start_shortcut_fail
start_shortcut_ok:
  Push "CreateShortCut StartMenu=PASS ($SMPROGRAMS\${PRODUCT_NAME}\${PRODUCT_NAME}.lnk)"
  Call LogLine
  Goto start_shortcut_done
start_shortcut_fail:
  Push "CreateShortCut StartMenu=FAIL ($SMPROGRAMS\${PRODUCT_NAME}\${PRODUCT_NAME}.lnk)"
  Call LogLine
  FileClose $LogHandle
  MessageBox MB_ICONSTOP "无法创建开始菜单快捷方式。日志：$InstallLog"
  Abort
start_shortcut_done:

  CreateShortCut "$SMPROGRAMS\${PRODUCT_NAME}\卸载 ${PRODUCT_NAME}.lnk" "$INSTDIR\Uninstall.exe" "" "$INSTDIR\resources\wuyou28.ico" 0

  WriteRegStr HKLM "${UNINSTALL_KEY}" "DisplayName" "${PRODUCT_NAME}"
  WriteRegStr HKLM "${UNINSTALL_KEY}" "DisplayVersion" "${PRODUCT_VERSION}"
  WriteRegStr HKLM "${UNINSTALL_KEY}" "Publisher" "无忧28"
  WriteRegStr HKLM "${UNINSTALL_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKLM "${UNINSTALL_KEY}" "DisplayIcon" "$INSTDIR\${PRODUCT_NAME}.exe"
  WriteRegStr HKLM "${UNINSTALL_KEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegDWORD HKLM "${UNINSTALL_KEY}" "NoModify" 1
  WriteRegDWORD HKLM "${UNINSTALL_KEY}" "NoRepair" 1
  Push "INSTALL=PASS"
  Call LogLine
  FileClose $LogHandle
  CopyFiles "$InstallLog" "$INSTDIR"
SectionEnd

Section "Uninstall"
  SetRegView 64
  SetShellVarContext all
  Delete "$DESKTOP\${PRODUCT_NAME}.lnk"
  Delete "$SMPROGRAMS\${PRODUCT_NAME}\${PRODUCT_NAME}.lnk"
  Delete "$SMPROGRAMS\${PRODUCT_NAME}\卸载 ${PRODUCT_NAME}.lnk"
  RMDir "$SMPROGRAMS\${PRODUCT_NAME}"
  DeleteRegKey HKLM "${UNINSTALL_KEY}"

  ; 用户数据位于 %LOCALAPPDATA%\无忧28，卸载刻意不访问该目录。
  RMDir /r "$INSTDIR"
SectionEnd
