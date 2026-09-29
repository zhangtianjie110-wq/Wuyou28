"""Optional application update checks and transactional EXE replacement.

The updater owns only version metadata and executable deployment. It never
opens the application database or any strategy/data directory.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from .constants import APP_HOME, APP_NAME, APP_VERSION


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UpdateInfo:
    current_version: str
    latest_version: str
    download_url: str
    build_date: str = ""
    sha256: str = ""
    size: int | None = None


class UpdateManager:
    """Check and stage updates without changing mutable application data."""

    def __init__(
        self,
        *,
        current_version: str = APP_VERSION,
        executable: str | Path | None = None,
        runtime_root: str | Path = APP_HOME,
        local_version_path: str | Path | None = None,
        manifest_url: str | None = None,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        self.current_version = str(current_version or "0.0.0")
        self.executable = Path(executable or sys.executable).resolve()
        self.runtime_root = Path(runtime_root)
        self.update_temp = self.runtime_root / "update_temp"
        self.backup_dir = self.runtime_root / "backup"
        self.local_version_path = Path(local_version_path) if local_version_path else None
        self.manifest_url = str(manifest_url or os.environ.get("WUYOU28_UPDATE_URL", "")).strip()
        self.opener = opener
        self.log_path = self.runtime_root / "logs" / "update.log"

    def _log(self, message: str, *, level: int = logging.INFO) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        logger.log(level, "update: %s", message)
        try:
            with self.log_path.open("a", encoding="utf-8") as stream:
                from datetime import datetime

                stream.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}\n")
        except OSError:
            logger.exception("unable to write update log: %s", self.log_path)

    @staticmethod
    def _normalize_url(value: str) -> str:
        """Return an ASCII URL while preserving already escaped URL parts."""
        parsed = urlsplit(str(value).strip())
        if not parsed.scheme:
            return str(value).strip()

        netloc = parsed.netloc
        if parsed.hostname:
            hostname = parsed.hostname.encode("idna").decode("ascii")
            if ":" in hostname and not hostname.startswith("["):
                hostname = f"[{hostname}]"
            userinfo = ""
            if "@" in parsed.netloc:
                userinfo = parsed.netloc.rsplit("@", 1)[0] + "@"
            port = f":{parsed.port}" if parsed.port is not None else ""
            netloc = f"{userinfo}{hostname}{port}"

        path = quote(parsed.path, safe="/%:@!$&'()*+,;=-._~")
        query = quote(parsed.query, safe="=&%:@/?+!$'()*,-._~")
        fragment = quote(parsed.fragment, safe="=&%:@/?+!$'()*,-._~")
        return urlunsplit((parsed.scheme, netloc, path, query, fragment))

    def _request(self, url: str, *, accept: str) -> Request:
        # HTTP headers are Latin-1 limited in urllib/http.client. Keep product
        # branding out of headers and carry all Chinese text in the UTF-8 URL
        # or response body instead.
        version = self.current_version.encode("ascii", "ignore").decode("ascii") or "0"
        return Request(
            self._normalize_url(url),
            headers={
                "User-Agent": f"Wuyou28/{version}",
                "Accept": accept,
                "Accept-Charset": "utf-8",
            },
        )

    @staticmethod
    def version_tuple(value: str) -> tuple[int, ...]:
        parts = []
        for part in str(value or "0").strip().lstrip("vV").split("."):
            digits = "".join(character for character in part if character.isdigit())
            parts.append(int(digits or 0))
        while len(parts) < 3:
            parts.append(0)
        return tuple(parts)

    @classmethod
    def load_version_file(cls, path: str | Path) -> dict[str, str]:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not str(payload.get("version", "")).strip():
            raise ValueError(f"invalid version file: {path}")
        return {
            "version": str(payload["version"]),
            "build_date": str(payload.get("build_date", "")),
            "download_url": str(payload.get("download_url", "")),
        }

    def local_version(self) -> str:
        if self.local_version_path and self.local_version_path.is_file():
            try:
                return self.load_version_file(self.local_version_path)["version"]
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                self._log(f"LOCAL_VERSION_FAILED error={type(exc).__name__}: {exc}", level=logging.WARNING)
        return self.current_version

    def check(self) -> UpdateInfo | None:
        """Return available update metadata, or None when checking is disabled."""
        current = self.local_version()
        if not self.manifest_url:
            self._log(f"CHECK_SKIPPED current={current} reason=no_manifest_url")
            return None
        try:
            request = self._request(self.manifest_url, accept="application/json")
            with self.opener(request, timeout=8) as response:
                raw = response.read()
            payload = json.loads(raw.decode("utf-8-sig"))
            if not isinstance(payload, dict):
                raise ValueError("version manifest must be a JSON object")
            latest = str(payload.get("version", "")).strip()
            download_url = str(payload.get("download_url", "")).strip()
            raw_size = payload.get("size")
            if not latest:
                raise ValueError("version manifest has no version")
            if self.version_tuple(latest) <= self.version_tuple(current):
                self._log(f"CHECK_OK current={current} latest={latest} result=up_to_date")
                return None
            if not download_url:
                raise ValueError("new version has no download_url")
            info = UpdateInfo(
                current_version=current,
                latest_version=latest,
                download_url=download_url,
                build_date=str(payload.get("build_date", "")),
                sha256=str(payload.get("sha256", "")).lower(),
                size=int(raw_size) if raw_size not in (None, "") else None,
            )
            self._log(f"CHECK_UPDATE current={current} latest={latest} url={download_url}")
            return info
        except Exception as exc:
            self._log(f"CHECK_FAILED current={current} error={type(exc).__name__}: {exc}", level=logging.WARNING)
            return None

    @staticmethod
    def _validate_download(path: Path, info: UpdateInfo) -> None:
        if not path.is_file() or path.stat().st_size < 1024:
            raise ValueError("downloaded EXE is missing or too small")
        with path.open("rb") as stream:
            if stream.read(2) != b"MZ":
                raise ValueError("downloaded file is not a Windows executable")
        if info.size is not None and path.stat().st_size != info.size:
            raise ValueError("downloaded EXE size does not match manifest")
        if info.sha256:
            digest = hashlib.sha256(path.read_bytes()).hexdigest().lower()
            if digest != info.sha256:
                raise ValueError("downloaded EXE SHA256 does not match manifest")

    def download(self, info: UpdateInfo) -> Path:
        self.update_temp.mkdir(parents=True, exist_ok=True)
        staged = self.update_temp / f"{APP_NAME}_{info.latest_version}.exe"
        request = self._request(info.download_url, accept="application/octet-stream")
        with self.opener(request, timeout=60) as response, staged.open("wb") as stream:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                stream.write(chunk)
        self._validate_download(staged, info)
        self._log(f"DOWNLOAD_OK version={info.latest_version} path={staged}")
        return staged

    def replace_staged(self, staged: str | Path, *, old_version: str | None = None) -> Path:
        """Apply a staged executable transactionally; used by tests and recovery tooling."""
        staged_path = Path(staged)
        self._validate_download(staged_path, UpdateInfo(self.current_version, self.current_version, ""))
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        backup = self.backup_dir / f"{self.executable.stem}_{old_version or self.current_version}.exe"
        temporary = self.executable.with_name(self.executable.name + ".update")
        try:
            if self.executable.is_file():
                backup.write_bytes(self.executable.read_bytes())
            temporary.write_bytes(staged_path.read_bytes())
            os.replace(temporary, self.executable)
            self._validate_download(self.executable, UpdateInfo(self.current_version, self.current_version, ""))
            self._log(f"UPDATE_OK current={self.current_version} exe={self.executable} backup={backup}")
            return backup
        except Exception as exc:
            if backup.is_file():
                backup.replace(self.executable)
            temporary.unlink(missing_ok=True)
            self._log(f"UPDATE_FAILED current={self.current_version} error={type(exc).__name__}: {exc}", level=logging.WARNING)
            raise

    def schedule_update(self, info: UpdateInfo) -> Path:
        """Download and launch an elevated PowerShell replacement helper."""
        staged = self.download(info)
        script = self.update_temp / "apply_update.ps1"
        plan = self.update_temp / "update_plan.json"
        staged_version = self.update_temp / "version.json"
        staged_version.write_text(
            json.dumps(
                {
                    "version": info.latest_version,
                    "build_date": info.build_date,
                    "download_url": info.download_url,
                    "sha256": info.sha256,
                    "size": info.size if info.size is not None else "",
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        # Windows PowerShell 5.1 needs a BOM to reliably parse UTF-8 scripts
        # containing Chinese paths or messages.
        script.write_text(_powershell_script(), encoding="utf-8-sig")
        plan.write_text(
            json.dumps(
                {
                    "process_id": os.getpid(),
                    "current_exe": str(self.executable),
                    "staged_exe": str(staged.resolve()),
                    "current_version_path": (
                        str(self.local_version_path.resolve()) if self.local_version_path else ""
                    ),
                    "staged_version_path": str(staged_version.resolve()),
                    "backup_dir": str(self.backup_dir.resolve()),
                    "log_path": str(self.log_path.resolve()),
                    "version": info.current_version,
                    "latest_version": info.latest_version,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8-sig",
        )
        powershell = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        arguments = [
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-PlanPath",
            str(plan),
        ]
        self._log(
            f"SCHEDULE current={info.current_version} latest={info.latest_version} "
            f"staged={staged} plan={plan}"
        )
        try:
            subprocess.Popen(
                [str(powershell), *arguments],
                cwd=str(self.update_temp),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception as exc:
            self._log(
                f"SCHEDULE_FAILED current={info.current_version} "
                f"latest={info.latest_version} error={type(exc).__name__}: {exc}",
                level=logging.ERROR,
            )
            raise
        return staged


def _powershell_script() -> str:
    return r'''param(
    [Parameter(Mandatory=$true)]
    [string]$PlanPath
)
$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding($false)
$planJson = [System.IO.File]::ReadAllText($PlanPath, [System.Text.Encoding]::UTF8)
$plan = $planJson | ConvertFrom-Json
$TargetProcessId = [int]$plan.process_id
$CurrentExe = [string]$plan.current_exe
$StagedExe = [string]$plan.staged_exe
$CurrentVersionPath = [string]$plan.current_version_path
$StagedVersionPath = [string]$plan.staged_version_path
$BackupDir = [string]$plan.backup_dir
$Version = [string]$plan.version
$LatestVersion = [string]$plan.latest_version
$log = [string]$plan.log_path
$logDirectory = Split-Path -Parent $log
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
function Log([string]$Message) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message$([Environment]::NewLine)"
    [System.IO.File]::AppendAllText($log, $line, $utf8)
}
function Quote-ProcessArgument([string]$Value) {
    if ($Value.Contains('"')) { throw "更新路径不能包含双引号: $Value" }
    return '"' + $Value + '"'
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
$isAdministrator = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
Log "HELPER_START elevated=$isAdministrator plan=$PlanPath exe=$CurrentExe"
if (-not $isAdministrator) {
    try {
        $powershell = Join-Path $env:WINDIR "System32\WindowsPowerShell\v1.0\powershell.exe"
        $forwarded = "-NoProfile -ExecutionPolicy Bypass -File $(Quote-ProcessArgument $PSCommandPath) -PlanPath $(Quote-ProcessArgument $PlanPath)"
        Log "ELEVATION_REQUEST script=$PSCommandPath plan=$PlanPath"
        Start-Process -FilePath $powershell -Verb RunAs -WindowStyle Hidden -ArgumentList $forwarded -ErrorAction Stop | Out-Null
    } catch {
        Log "ELEVATION_FAILED error=$($_.Exception.Message)"
    }
    exit 0
}
$backup = Join-Path $BackupDir ([System.IO.Path]::GetFileNameWithoutExtension($CurrentExe) + "_" + $Version + ".exe")
$versionBackup = Join-Path $BackupDir ("version_" + $Version + ".json")
$temporary = "$CurrentExe.update"
$versionTemporary = if ($CurrentVersionPath) { "$CurrentVersionPath.update" } else { "" }
$hadCurrentVersion = $CurrentVersionPath -and (Test-Path -LiteralPath $CurrentVersionPath -PathType Leaf)
$newProcess = $null
$exeReplaced = $false
$versionReplaced = $false
try {
    for ($i = 0; $i -lt 90; $i++) {
        if (-not (Get-Process -Id $TargetProcessId -ErrorAction SilentlyContinue)) { break }
        Start-Sleep -Seconds 1
    }
    if (Get-Process -Id $TargetProcessId -ErrorAction SilentlyContinue) { throw "旧进程未退出" }
    if (-not (Test-Path -LiteralPath $StagedVersionPath -PathType Leaf)) { throw "待安装版本文件不存在" }
    $stagedVersion = Get-Content -LiteralPath $StagedVersionPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$stagedVersion.version -ne $LatestVersion) { throw "待安装版本号不匹配" }
    New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
    Copy-Item -LiteralPath $CurrentExe -Destination $backup -Force
    if ($CurrentVersionPath -and (Test-Path -LiteralPath $CurrentVersionPath -PathType Leaf)) {
        Copy-Item -LiteralPath $CurrentVersionPath -Destination $versionBackup -Force
    }
    Copy-Item -LiteralPath $StagedExe -Destination $temporary -Force
    if ($CurrentVersionPath) {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $CurrentVersionPath) | Out-Null
        Copy-Item -LiteralPath $StagedVersionPath -Destination $versionTemporary -Force
    }
    Move-Item -LiteralPath $temporary -Destination $CurrentExe -Force
    $exeReplaced = $true
    if ($CurrentVersionPath) {
        Move-Item -LiteralPath $versionTemporary -Destination $CurrentVersionPath -Force
        $versionReplaced = $true
    }
    $newProcess = Start-Process -FilePath $CurrentExe -WorkingDirectory (Split-Path -Parent $CurrentExe) -PassThru -ErrorAction Stop
    Start-Sleep -Seconds 5
    if ($newProcess.HasExited) {
        throw "新版启动后在观察期内退出 exit_code=$($newProcess.ExitCode)"
    }
    Log "UPDATE_OK old_version=$Version new_version=$LatestVersion exe=$CurrentExe backup=$backup version_file=$CurrentVersionPath version_backup=$versionBackup process_id=$($newProcess.Id)"
} catch {
    $failure = $_.Exception.Message
    if ($newProcess -and -not $newProcess.HasExited) {
        Stop-Process -Id $newProcess.Id -Force -ErrorAction SilentlyContinue
        $newProcess.WaitForExit()
    }
    $exeRestored = $false
    $versionRestored = $false
    if ($exeReplaced -and (Test-Path -LiteralPath $backup -PathType Leaf)) {
        Copy-Item -LiteralPath $backup -Destination $CurrentExe -Force
        $exeRestored = $true
    }
    if ($versionReplaced -and $CurrentVersionPath) {
        if ($hadCurrentVersion -and (Test-Path -LiteralPath $versionBackup -PathType Leaf)) {
            Copy-Item -LiteralPath $versionBackup -Destination $CurrentVersionPath -Force
            $versionRestored = $true
        } elseif (-not $hadCurrentVersion -and (Test-Path -LiteralPath $CurrentVersionPath -PathType Leaf)) {
            Remove-Item -LiteralPath $CurrentVersionPath -Force
            $versionRestored = $true
        }
    }
    if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue }
    if ($versionTemporary -and (Test-Path -LiteralPath $versionTemporary)) { Remove-Item -LiteralPath $versionTemporary -Force -ErrorAction SilentlyContinue }
    Log "UPDATE_FAILED old_version=$Version new_version=$LatestVersion error=$failure rollback_exe=$exeRestored rollback_version=$versionRestored"
    try {
        $rollbackProcess = Start-Process -FilePath $CurrentExe -WorkingDirectory (Split-Path -Parent $CurrentExe) -PassThru -ErrorAction Stop
        Log "ROLLBACK_RESTART_OK version=$Version process_id=$($rollbackProcess.Id)"
    } catch {
        Log "ROLLBACK_RESTART_FAILED version=$Version error=$($_.Exception.Message)"
    }
}
'''


__all__ = ["UpdateInfo", "UpdateManager"]
