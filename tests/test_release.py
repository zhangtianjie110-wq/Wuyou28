from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import release


class FakeUploader:
    def __init__(self, *, fail_connection: bool = False, fail_upload: bool = False):
        self.fail_connection = fail_connection
        self.fail_upload = fail_upload
        self.checked = False
        self.uploaded = False

    def check_connection(self) -> None:
        self.checked = True
        if self.fail_connection:
            raise release.ReleaseError("模拟连接失败")

    def upload(self, executable: Path, manifest_path: Path, artifact: dict) -> None:
        self.uploaded = True
        if self.fail_upload:
            raise release.ReleaseError("模拟上传失败")
        if not executable.is_file() or not manifest_path.is_file():
            raise release.ReleaseError("模拟上传文件不存在")
        if artifact["size"] != executable.stat().st_size:
            raise release.ReleaseError("模拟上传大小不一致")


class ReleaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "resources").mkdir()
        (self.root / "resources" / "version.json").write_text(
            json.dumps({"version": "0.6.2"}), encoding="utf-8"
        )
        (self.root / "release_config.json").write_text(
            json.dumps(
                {
                    "server_url": "https://updates.example.com",
                    "remote_path": r"C:\Wuyou28Update",
                    "download_url": "https://updates.example.com/wuyou28.exe",
                }
            ),
            encoding="utf-8",
        )
        self.exe = self.root / "dist" / "无忧28" / "无忧28.exe"
        self.exe.parent.mkdir(parents=True)
        self.exe.write_bytes(b"MZ" + b"release-payload" * 128)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_missing_executable_stops_release(self) -> None:
        self.exe.unlink()
        with self.assertRaisesRegex(release.ReleaseError, "新版 EXE 不存在"):
            release.publish(project_root=self.root, dry_run=True)

    def test_sha256_matches_file(self) -> None:
        expected = hashlib.sha256(self.exe.read_bytes()).hexdigest().upper()
        self.assertEqual(release.sha256_file(self.exe), expected)

    def test_manifest_generation(self) -> None:
        manifest = release.build_manifest(
            version="0.6.2",
            build_date="2026-09-28",
            download_url="https://updates.example.com/wuyou28.exe",
            sha256="A" * 64,
            size=2048,
        )
        target = release.write_manifest(self.root / "out" / "version.json", manifest)
        saved = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(saved["version"], "0.6.2")
        self.assertEqual(saved["build_date"], "2026-09-28")
        self.assertEqual(saved["sha256"], "A" * 64)
        self.assertEqual(saved["size"], 2048)

    def test_upload_failure_has_no_success_output(self) -> None:
        output = self.root / "release_output" / "version.json"
        uploader = FakeUploader(fail_upload=True)
        with self.assertRaisesRegex(release.ReleaseError, "模拟上传失败"):
            release.publish(
                project_root=self.root,
                output_path=output,
                uploader=uploader,
            )
        self.assertTrue(uploader.checked)
        self.assertTrue(uploader.uploaded)
        self.assertFalse(output.exists())

    def test_simulated_release(self) -> None:
        output = self.root / "release_output" / "version.json"
        uploader = FakeUploader()
        result = release.publish(
            project_root=self.root,
            output_path=output,
            uploader=uploader,
        )
        self.assertTrue(result.uploaded)
        self.assertTrue(uploader.checked)
        self.assertTrue(uploader.uploaded)
        saved = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(saved["version"], "0.6.2")
        self.assertEqual(saved["size"], self.exe.stat().st_size)
        self.assertEqual(saved["sha256"], release.sha256_file(self.exe))

    def test_dry_run_never_connects(self) -> None:
        output = self.root / "release_output" / "version.json"
        result = release.publish(
            project_root=self.root,
            output_path=output,
            dry_run=True,
            uploader=FakeUploader(fail_connection=True),
        )
        self.assertFalse(result.uploaded)
        self.assertTrue(output.is_file())

    def test_rejects_wrong_remote_path(self) -> None:
        (self.root / "release_config.json").write_text(
            json.dumps(
                {
                    "server_url": "https://updates.example.com",
                    "remote_path": r"C:\Windows",
                    "download_url": "https://updates.example.com/wuyou28.exe",
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(release.ReleaseError, "远端目录必须"):
            release.publish(project_root=self.root, dry_run=True)

    def test_cli_help_has_output(self) -> None:
        environment = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        result = subprocess.run(
            [sys.executable, str(Path(release.__file__).resolve()), "--help"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("usage:", result.stdout)
        self.assertIn("--dry-run", result.stdout)
        self.assertIn("--exe", result.stdout)

    def test_cli_dry_run_has_status_output(self) -> None:
        output = self.root / "cli-output" / "version.json"
        environment = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        result = subprocess.run(
            [
                sys.executable,
                str(Path(release.__file__).resolve()),
                "--dry-run",
                "--exe",
                str(self.exe),
                "--config",
                str(self.root / "release_config.json"),
                "--output",
                str(output),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("RELEASE_START", result.stdout)
        self.assertIn("RELEASE_CHECK mode=dry-run", result.stdout)
        self.assertIn("version=0.6.3", result.stdout)
        self.assertIn("RELEASE_SUCCESS mode=dry-run uploaded=false", result.stdout)
        self.assertTrue(output.is_file())


if __name__ == "__main__":
    unittest.main()
