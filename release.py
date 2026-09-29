"""Build artifact publisher for the Wuyou28 Windows updater.

This module only handles release artifacts. It does not import or access the
application database, collection services, backtest engine, or strategy code.
"""
from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
from datetime import date
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import subprocess
import tempfile
from typing import Sequence
from urllib.parse import urlparse


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_EXE = Path("dist") / "无忧28" / "无忧28.exe"
DEFAULT_VERSION_FILE = Path("resources") / "version.json"
DEFAULT_CONFIG_FILE = Path("release_config.json")
DEFAULT_OUTPUT_FILE = Path("release_output") / "version.json"
REMOTE_RELEASE_PATH = PureWindowsPath(r"C:\Wuyou28Update")
MIN_EXE_SIZE = 1024
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


class ReleaseError(RuntimeError):
    """Raised when a release safety check or upload step fails."""


@dataclass(frozen=True)
class ReleaseConfig:
    server_url: str
    remote_path: PureWindowsPath
    download_url: str

    @classmethod
    def load(cls, path: Path) -> "ReleaseConfig":
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except FileNotFoundError as exc:
            raise ReleaseError(f"发布配置不存在: {path}") from exc
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ReleaseError(f"发布配置读取失败: {path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ReleaseError(f"发布配置必须是 JSON 对象: {path}")
        remote_path = _validate_remote_path(str(payload.get("remote_path", "")))
        return cls(
            server_url=str(payload.get("server_url", "")).strip(),
            remote_path=remote_path,
            download_url=str(payload.get("download_url", "")).strip(),
        )

    def resolved_download_url(self) -> str:
        value = self.download_url
        if not value and self.server_url.startswith(("http://", "https://")):
            value = self.server_url.rstrip("/") + "/wuyou28.exe"
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ReleaseError("download_url 必须是可公开访问的 HTTP/HTTPS EXE 地址")
        return value

    def ssh_host(self) -> str:
        override = os.environ.get("WUYOU28_RELEASE_HOST", "").strip()
        if override:
            return override
        value = self.server_url.strip()
        if not value:
            raise ReleaseError("未配置 server_url 或 WUYOU28_RELEASE_HOST")
        parsed = urlparse(value if "://" in value else f"ssh://{value}")
        if not parsed.hostname:
            raise ReleaseError(f"无法从 server_url 解析 VPS 地址: {value}")
        return parsed.hostname


@dataclass(frozen=True)
class ReleaseArtifact:
    executable: Path
    version: str
    size: int
    sha256: str
    manifest: dict[str, object]
    manifest_path: Path
    uploaded: bool


def _validate_remote_path(value: str) -> PureWindowsPath:
    path = PureWindowsPath(value)
    if str(path).casefold() != str(REMOTE_RELEASE_PATH).casefold():
        raise ReleaseError(
            f"远端目录必须是 {REMOTE_RELEASE_PATH}，拒绝发布到: {value or '<空>'}"
        )
    return path


def read_version(path: Path) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise ReleaseError(f"版本文件不存在: {path}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseError(f"版本文件读取失败: {path}: {exc}") from exc
    version = str(payload.get("version", "")).strip() if isinstance(payload, dict) else ""
    if not VERSION_PATTERN.fullmatch(version):
        raise ReleaseError(f"版本号无效: {version or '<空>'}")
    return version


def find_executable(path: Path) -> Path:
    executable = path.resolve()
    if not executable.is_file():
        raise ReleaseError(f"新版 EXE 不存在: {executable}")
    size = executable.stat().st_size
    if size < MIN_EXE_SIZE:
        raise ReleaseError(f"EXE 文件过小: {executable} ({size} bytes)")
    with executable.open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise ReleaseError(f"文件不是有效的 Windows EXE: {executable}")
    return executable


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    value = digest.hexdigest().upper()
    if len(value) != 64:
        raise ReleaseError(f"SHA256 计算失败: {path}")
    return value


def build_manifest(
    *, version: str, download_url: str, sha256: str, size: int, build_date: str | None = None
) -> dict[str, object]:
    if not VERSION_PATTERN.fullmatch(version):
        raise ReleaseError(f"版本号无效: {version}")
    if not re.fullmatch(r"[0-9A-Fa-f]{64}", sha256):
        raise ReleaseError("SHA256 格式无效")
    if size < MIN_EXE_SIZE:
        raise ReleaseError(f"EXE 文件大小无效: {size}")
    parsed = urlparse(download_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ReleaseError(f"下载地址无效: {download_url}")
    return {
        "version": version,
        "build_date": build_date or date.today().isoformat(),
        "download_url": download_url,
        "sha256": sha256.upper(),
        "size": size,
    }


def write_manifest(path: Path, manifest: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def _powershell_encoded(script: str) -> str:
    return base64.b64encode(script.encode("utf-16le")).decode("ascii")


class SshVpsUploader:
    """Upload and verify release artifacts using Windows OpenSSH."""

    def __init__(self, config: ReleaseConfig) -> None:
        self.config = config
        host = config.ssh_host()
        user = os.environ.get("WUYOU28_RELEASE_USER", "").strip()
        self.target = f"{user}@{host}" if user else host
        self.port = os.environ.get("WUYOU28_RELEASE_PORT", "22").strip() or "22"
        if not self.port.isdigit() or not (1 <= int(self.port) <= 65535):
            raise ReleaseError(f"SSH端口无效: {self.port}")
        key_value = os.environ.get("WUYOU28_RELEASE_SSH_KEY", "").strip()
        self.key = Path(key_value).expanduser().resolve() if key_value else None
        if self.key is not None and not self.key.is_file():
            raise ReleaseError(f"SSH密钥不存在: {self.key}")

    def _ssh_base(self) -> list[str]:
        command = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            "-p",
            self.port,
        ]
        if self.key is not None:
            command.extend(["-i", str(self.key)])
        return command

    def _scp_base(self) -> list[str]:
        command = [
            "scp",
            "-q",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            "-P",
            self.port,
        ]
        if self.key is not None:
            command.extend(["-i", str(self.key)])
        return command

    @staticmethod
    def _run(command: Sequence[str], description: str) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                list(command),
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
            )
        except subprocess.TimeoutExpired as exc:
            raise ReleaseError(f"{description}超时") from exc
        except OSError as exc:
            raise ReleaseError(f"{description}无法执行: {exc}") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "未知错误").strip()
            raise ReleaseError(f"{description}失败: {detail}")
        return result

    def _run_remote(self, script: str, description: str) -> None:
        command = [
            *self._ssh_base(),
            self.target,
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-EncodedCommand",
            _powershell_encoded(script),
        ]
        self._run(command, description)

    def check_connection(self) -> None:
        self._run_remote(
            "$ErrorActionPreference='Stop'; Write-Output $env:COMPUTERNAME",
            "VPS连接检查",
        )
        remote = str(self.config.remote_path).replace("'", "''")
        self._run_remote(
            "$ErrorActionPreference='Stop'; "
            f"$path='{remote}'; "
            "if (Test-Path -LiteralPath $path) { "
            "$item=Get-Item -LiteralPath $path; "
            "if (-not $item.PSIsContainer) { throw '远端发布路径不是目录' } "
            "} else { New-Item -ItemType Directory -Path $path | Out-Null }",
            "远端目录检查",
        )

    def _upload_file(self, source: Path, remote_name: str) -> None:
        remote_dir = self.config.remote_path.as_posix().rstrip("/")
        destination = f"{self.target}:{remote_dir}/{remote_name}"
        self._run([*self._scp_base(), str(source), destination], f"上传 {source.name}")

    def upload(self, executable: Path, manifest_path: Path, artifact: dict[str, object]) -> None:
        remote = str(self.config.remote_path).replace("'", "''")
        expected_hash = str(artifact["sha256"])
        expected_size = int(artifact["size"])
        finalize = f"""
$ErrorActionPreference='Stop'
$root='{remote}'
$newExe=Join-Path $root 'wuyou28.exe.uploading'
$newManifest=Join-Path $root 'version.json.uploading'
$exe=Join-Path $root 'wuyou28.exe'
$manifest=Join-Path $root 'version.json'
$previous=Join-Path $root 'wuyou28.exe.previous'
if (-not (Test-Path -LiteralPath $newExe -PathType Leaf)) {{ throw '上传的EXE不存在' }}
if (-not (Test-Path -LiteralPath $newManifest -PathType Leaf)) {{ throw '上传的version.json不存在' }}
if ((Get-Item -LiteralPath $newExe).Length -ne {expected_size}) {{ throw '远端EXE大小校验失败' }}
if ((Get-FileHash -LiteralPath $newExe -Algorithm SHA256).Hash -ne '{expected_hash}') {{ throw '远端EXE SHA256校验失败' }}
$null=Get-Content -LiteralPath $newManifest -Raw -Encoding UTF8 | ConvertFrom-Json
try {{
    if (Test-Path -LiteralPath $exe -PathType Leaf) {{ Copy-Item -LiteralPath $exe -Destination $previous -Force }}
    Move-Item -LiteralPath $newExe -Destination $exe -Force
    Move-Item -LiteralPath $newManifest -Destination $manifest -Force
    Remove-Item -LiteralPath $previous -Force -ErrorAction SilentlyContinue
}} catch {{
    if (Test-Path -LiteralPath $previous -PathType Leaf) {{ Move-Item -LiteralPath $previous -Destination $exe -Force }}
    throw
}}
"""
        try:
            self._upload_file(executable, "wuyou28.exe.uploading")
            self._upload_file(manifest_path, "version.json.uploading")
            self._run_remote(finalize, "远端校验与发布")
        except ReleaseError:
            cleanup = (
                f"$root='{remote}'; "
                "Remove-Item -LiteralPath (Join-Path $root 'wuyou28.exe.uploading') -Force -ErrorAction SilentlyContinue; "
                "Remove-Item -LiteralPath (Join-Path $root 'version.json.uploading') -Force -ErrorAction SilentlyContinue"
            )
            try:
                self._run_remote(cleanup, "远端临时文件清理")
            except ReleaseError:
                pass
            raise


def publish(
    *,
    project_root: Path = PROJECT_ROOT,
    config_path: Path | None = None,
    executable_path: Path | None = None,
    output_path: Path | None = None,
    dry_run: bool = False,
    uploader: object | None = None,
) -> ReleaseArtifact:
    root = project_root.resolve()
    version_file = root / DEFAULT_VERSION_FILE
    config_candidate = config_path or DEFAULT_CONFIG_FILE
    executable_candidate = executable_path or DEFAULT_EXE
    output_candidate = output_path or DEFAULT_OUTPUT_FILE
    config_file = (
        config_candidate if config_candidate.is_absolute() else root / config_candidate
    ).resolve()
    executable = find_executable(
        executable_candidate
        if executable_candidate.is_absolute()
        else root / executable_candidate
    )
    output = (
        output_candidate if output_candidate.is_absolute() else root / output_candidate
    ).resolve()
    version = read_version(version_file)
    config = ReleaseConfig.load(config_file)
    size = executable.stat().st_size
    digest = sha256_file(executable)
    manifest = build_manifest(
        version=version,
        download_url=config.resolved_download_url(),
        sha256=digest,
        size=size,
    )

    if dry_run:
        write_manifest(output, manifest)
        return ReleaseArtifact(executable, version, size, digest, manifest, output, False)

    active_uploader = uploader or SshVpsUploader(config)
    with tempfile.TemporaryDirectory(prefix="wuyou28-release-") as temporary:
        staged_manifest = write_manifest(Path(temporary) / "version.json", manifest)
        active_uploader.check_connection()
        active_uploader.upload(executable, staged_manifest, manifest)
    write_manifest(output, manifest)
    return ReleaseArtifact(executable, version, size, digest, manifest, output, True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="发布无忧28 EXE和自动更新清单")
    parser.add_argument("--config", type=Path, help="发布配置，默认 release_config.json")
    parser.add_argument("--exe", type=Path, help=r"EXE路径，默认 dist\无忧28\无忧28.exe")
    parser.add_argument("--output", type=Path, help="本地清单输出路径")
    parser.add_argument("--dry-run", action="store_true", help="只验证并生成本地清单，不连接VPS")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    mode = "dry-run" if args.dry_run else "publish"
    print("RELEASE_START", flush=True)
    print(f"RELEASE_CHECK mode={mode}", flush=True)
    try:
        current_version = read_version(PROJECT_ROOT / DEFAULT_VERSION_FILE)
        print(f"version={current_version}", flush=True)
        result = publish(
            config_path=args.config,
            executable_path=args.exe,
            output_path=args.output,
            dry_run=args.dry_run,
        )
    except ReleaseError as exc:
        print(f"RELEASE_FAILED: {exc}", flush=True)
        return 1
    print(
        f"RELEASE_SUCCESS mode={mode} uploaded={str(result.uploaded).lower()}",
        flush=True,
    )
    print(f"exe={result.executable}", flush=True)
    print(f"size={result.size}", flush=True)
    print(f"sha256={result.sha256}", flush=True)
    print(f"manifest={result.manifest_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
