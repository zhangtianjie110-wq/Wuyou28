from __future__ import annotations

import hashlib
from io import BytesIO
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from app.update_manager import UpdateInfo, UpdateManager


class UpdateManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.gettempdir()) / f"wuyou28-update-{uuid4().hex}"
        self.root.mkdir(parents=True)
        self.current = self.root / "无忧28.exe"
        self.current.write_bytes(b"MZ" + b"old" * 512)
        self.version = self.root / "version.json"
        self.version.write_text(
            json.dumps({"version": "0.6.0", "build_date": "", "download_url": ""}),
            encoding="utf-8",
        )
        self.manager = UpdateManager(
            current_version="0.6.0",
            executable=self.current,
            runtime_root=self.root,
            local_version_path=self.version,
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_version_comparison_and_disabled_check(self) -> None:
        self.assertEqual(self.manager.local_version(), "0.6.0")
        self.assertGreater(UpdateManager.version_tuple("0.7.0"), UpdateManager.version_tuple("0.6.0"))
        self.assertIsNone(self.manager.check())
        self.assertTrue((self.root / "logs" / "update.log").is_file())

    def test_manifest_and_download_checksum(self) -> None:
        staged = self.root / "new.exe"
        staged.write_bytes(b"MZ" + b"new" * 512)
        digest = hashlib.sha256(staged.read_bytes()).hexdigest()
        manifest = json.dumps(
            {
                "version": "0.7.0",
                "build_date": "2026-09-28",
                "download_url": staged.as_uri(),
                "sha256": digest,
                "size": staged.stat().st_size,
            }
        ).encode()

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, *_args):
                return manifest

        manager = UpdateManager(
            current_version="0.6.0",
            executable=self.current,
            runtime_root=self.root,
            local_version_path=self.version,
            manifest_url="https://updates.invalid/version.json",
            opener=lambda *_args, **_kwargs: Response(),
        )
        info = manager.check()
        self.assertIsNotNone(info)
        self.assertEqual(info.latest_version, "0.7.0")

    def test_065_update_detection_and_integrity_rejection(self) -> None:
        self.version.write_text(
            json.dumps({"version": "0.6.5", "build_date": "2026-09-29"}),
            encoding="utf-8",
        )
        payload = b"MZ" + b"release-0.6.6" * 128
        digest = hashlib.sha256(payload).hexdigest()
        manifest = json.dumps(
            {
                "version": "0.6.6",
                "build_date": "2026-09-29",
                "download_url": "https://updates.invalid/无忧28.exe",
                "sha256": digest,
                "size": len(payload),
            },
            ensure_ascii=False,
        ).encode("utf-8")

        def opener(request, **_kwargs):
            if request.get_header("Accept") == "application/json":
                return BytesIO(manifest)
            return BytesIO(payload)

        manager = UpdateManager(
            current_version="0.6.5",
            executable=self.current,
            runtime_root=self.root,
            local_version_path=self.version,
            manifest_url="https://updates.invalid/version.json",
            opener=opener,
        )
        info = manager.check()
        self.assertIsNotNone(info)
        self.assertEqual(info.current_version, "0.6.5")
        self.assertEqual(info.latest_version, "0.6.6")
        self.assertEqual(manager.download(info).read_bytes(), payload)

        with self.assertRaisesRegex(ValueError, "size does not match"):
            manager.download(
                UpdateInfo("0.6.5", "0.6.6", info.download_url, size=len(payload) + 1)
            )
        with self.assertRaisesRegex(ValueError, "SHA256 does not match"):
            manager.download(
                UpdateInfo("0.6.5", "0.6.6", info.download_url, sha256="0" * 64)
            )

    def test_update_prompt_wiring_shows_current_and_latest_versions(self) -> None:
        main_source = (Path(__file__).parents[1] / "main.py").read_text(encoding="utf-8")
        self.assertIn("task.signals.finished.connect(finish)", main_source)
        self.assertIn('QMessageBox.question(', main_source)
        self.assertIn('f"发现新版本：{info.latest_version}\\n"', main_source)
        self.assertIn('f"当前版本：{info.current_version}\\n"', main_source)
        self.assertIn("manager.schedule_update(info)", main_source)

    def test_end_to_end_manifest_with_empty_optional_size(self) -> None:
        server = self.root / "server"
        server.mkdir()
        payload = server / "无忧28.exe"
        source_exe = Path("dist/无忧28/无忧28.exe")
        payload.write_bytes(source_exe.read_bytes() if source_exe.is_file() else b"MZ" + b"new" * 512)
        (server / "version.json").write_text(
            json.dumps(
                {
                    "version": "0.6.1",
                    "build_date": "2026-09-28",
                    "download_url": payload.as_uri(),
                    "sha256": "",
                    "size": "",
                }
            ),
            encoding="utf-8",
        )
        manager = UpdateManager(
            current_version="0.6.0",
            executable=self.current,
            runtime_root=self.root,
            local_version_path=self.version,
            manifest_url=(server / "version.json").as_uri(),
        )
        info = manager.check()
        self.assertIsNotNone(info)
        staged = manager.download(info)
        old = self.current.read_bytes()
        backup = manager.replace_staged(staged, old_version="0.6.0")
        self.assertEqual(self.current.read_bytes(), payload.read_bytes())
        self.assertEqual(backup.read_bytes(), old)

        failed = server / "broken.exe"
        failed.write_bytes(b"not-an-exe")
        with self.assertRaises(ValueError):
            manager.download(
                UpdateInfo("0.6.0", "0.6.2", failed.as_uri())
            )
        self.assertEqual(self.current.read_bytes(), payload.read_bytes())

    def test_chinese_paths_and_http_urls_use_utf8_safely(self) -> None:
        chinese_root = self.root / "中文更新目录"
        chinese_root.mkdir()
        current = chinese_root / "无忧28.exe"
        current.write_bytes(b"MZ" + b"old" * 512)
        local_version = chinese_root / "本地版本.json"
        local_version.write_text(
            json.dumps({"version": "0.6.0"}, ensure_ascii=False),
            encoding="utf-8",
        )
        new_exe = b"MZ" + b"new" * 512
        digest = hashlib.sha256(new_exe).hexdigest()
        download_url = "https://更新.example/发布/无忧28.exe"
        manifest = json.dumps(
            {
                "version": "0.6.1",
                "build_date": "2026-09-28",
                "download_url": download_url,
                "sha256": digest,
                "size": len(new_exe),
            },
            ensure_ascii=False,
        ).encode("utf-8")
        requests = []

        def opener(request, **_kwargs):
            requests.append(request)
            for _name, value in request.header_items():
                value.encode("latin-1")
            self.assertEqual(request.get_header("Accept-charset"), "utf-8")
            if request.get_header("Accept") == "application/json":
                return BytesIO(manifest)
            return BytesIO(new_exe)

        manager = UpdateManager(
            current_version="0.6.0",
            executable=current,
            runtime_root=chinese_root,
            local_version_path=local_version,
            manifest_url="https://更新.example/发布/version.json",
            opener=opener,
        )
        info = manager.check()
        self.assertIsNotNone(info)
        staged = manager.download(info)
        backup = manager.replace_staged(staged, old_version="0.6.0")

        self.assertEqual(current.read_bytes(), new_exe)
        self.assertTrue(backup.is_file())
        self.assertEqual(len(requests), 2)
        self.assertTrue(all(request.get_header("User-agent").startswith("Wuyou28/") for request in requests))
        self.assertTrue(all(request.full_url.isascii() for request in requests))
        self.assertIn("%E6%97%A0%E5%BF%A728.exe", requests[1].full_url)
        log_text = (chinese_root / "logs" / "update.log").read_text(encoding="utf-8")
        self.assertIn("UPDATE_OK", log_text)

    def test_replace_and_failure_recovery(self) -> None:
        staged = self.root / "staged.exe"
        staged.write_bytes(b"MZ" + b"new" * 512)
        old = self.current.read_bytes()
        backup = self.manager.replace_staged(staged)
        self.assertEqual(self.current.read_bytes(), staged.read_bytes())
        self.assertEqual(backup.read_bytes(), old)

        self.current.write_bytes(old)
        with patch("app.update_manager.os.replace", side_effect=OSError("simulated replace failure")):
            with self.assertRaises(OSError):
                self.manager.replace_staged(staged, old_version="0.6.0")
        self.assertEqual(self.current.read_bytes(), old)

    def test_schedule_uses_utf8_plan_for_chinese_windows_paths(self) -> None:
        runtime = Path(r"C:\Users\Administrator\AppData\Local\无忧28")
        update_temp = self.root / "AppData" / "Local" / "无忧28" / "update_temp"
        update_temp.mkdir(parents=True)
        staged = update_temp / "无忧28_0.6.2.exe"
        staged.write_bytes(b"MZ" + b"new" * 512)
        current = Path(r"C:\project\dist\无忧28\无忧28.exe")
        manager = UpdateManager(
            current_version="0.6.0",
            executable=current,
            runtime_root=runtime,
            local_version_path=Path(r"C:\project\dist\无忧28\_internal\resources\version.json"),
        )
        manager.update_temp = update_temp
        manager.backup_dir = runtime / "backup"
        manager.log_path = runtime / "logs" / "update.log"
        info = UpdateInfo("0.6.0", "0.6.2", "https://updates.invalid/wuyou28.exe")

        with (
            patch.object(manager, "download", return_value=staged),
            patch.object(manager, "_log"),
            patch("app.update_manager.subprocess.Popen") as popen,
        ):
            self.assertEqual(manager.schedule_update(info), staged)

        script = update_temp / "apply_update.ps1"
        plan = update_temp / "update_plan.json"
        self.assertTrue(script.read_bytes().startswith(b"\xef\xbb\xbf"))
        self.assertTrue(plan.read_bytes().startswith(b"\xef\xbb\xbf"))
        payload = json.loads(plan.read_text(encoding="utf-8-sig"))
        self.assertEqual(payload["current_exe"], str(current.resolve()))
        self.assertEqual(payload["staged_exe"], str(staged.resolve()))
        self.assertEqual(
            payload["current_version_path"],
            r"C:\project\dist\无忧28\_internal\resources\version.json",
        )
        staged_version = Path(payload["staged_version_path"])
        self.assertEqual(
            json.loads(staged_version.read_text(encoding="utf-8"))["version"],
            "0.6.2",
        )
        self.assertEqual(payload["backup_dir"], str((runtime / "backup").resolve()))
        self.assertEqual(
            payload["log_path"],
            r"C:\Users\Administrator\AppData\Local\无忧28\logs\update.log",
        )
        self.assertEqual(
            payload["backup_dir"],
            r"C:\Users\Administrator\AppData\Local\无忧28\backup",
        )
        self.assertIn(r"dist\无忧28\无忧28.exe", payload["current_exe"])

        command = popen.call_args.args[0]
        self.assertIn("-PlanPath", command)
        self.assertEqual(command[command.index("-PlanPath") + 1], str(plan))
        self.assertNotIn("-CurrentExe", command)
        self.assertNotIn("-StagedExe", command)
        script_text = script.read_text(encoding="utf-8-sig")
        self.assertIn("ReadAllText($PlanPath, [System.Text.Encoding]::UTF8)", script_text)
        self.assertIn("Quote-ProcessArgument $PSCommandPath", script_text)
        self.assertIn("version_backup=$versionBackup", script_text)
        self.assertIn("Copy-Item -LiteralPath $versionBackup", script_text)
        self.assertIn("-PassThru -ErrorAction Stop", script_text)
        self.assertIn("Start-Sleep -Seconds 5", script_text)
        self.assertIn("if ($newProcess.HasExited)", script_text)
        self.assertIn("rollback_exe=$exeRestored", script_text)
        self.assertIn("ROLLBACK_RESTART_OK", script_text)

    def test_schedule_script_does_not_report_success_before_startup_check(self) -> None:
        staged = self.root / "update_temp" / "无忧28_0.6.6.exe"
        staged.parent.mkdir(parents=True)
        staged.write_bytes(b"MZ" + b"new" * 512)
        info = UpdateInfo("0.6.5", "0.6.6", "https://updates.invalid/wuyou28.exe")
        manager = UpdateManager(
            current_version="0.6.5",
            executable=self.current,
            runtime_root=self.root,
            local_version_path=self.version,
        )
        with (
            patch.object(manager, "download", return_value=staged),
            patch("app.update_manager.subprocess.Popen"),
        ):
            manager.schedule_update(info)

        script_text = (manager.update_temp / "apply_update.ps1").read_text(encoding="utf-8-sig")
        start_position = script_text.index("$newProcess = Start-Process")
        health_check_position = script_text.index("if ($newProcess.HasExited)")
        success_position = script_text.index('Log "UPDATE_OK')
        self.assertLess(start_position, health_check_position)
        self.assertLess(health_check_position, success_position)
        self.assertIn('throw "新版启动后在观察期内退出', script_text)
        self.assertIn('Log "UPDATE_FAILED old_version=', script_text)

    def test_schedule_failure_is_logged_with_utf8_paths(self) -> None:
        runtime = self.root / "无忧28"
        staged = runtime / "update_temp" / "无忧28_0.6.2.exe"
        staged.parent.mkdir(parents=True)
        staged.write_bytes(b"MZ" + b"new" * 512)
        manager = UpdateManager(
            current_version="0.6.0",
            executable=runtime / "dist" / "无忧28" / "无忧28.exe",
            runtime_root=runtime,
        )
        info = UpdateInfo("0.6.0", "0.6.2", "https://updates.invalid/wuyou28.exe")
        with (
            patch.object(manager, "download", return_value=staged),
            patch("app.update_manager.subprocess.Popen", side_effect=OSError("启动失败")),
            self.assertRaises(OSError),
        ):
            manager.schedule_update(info)
        log_text = manager.log_path.read_text(encoding="utf-8")
        self.assertIn("SCHEDULE_FAILED", log_text)
        self.assertIn("启动失败", log_text)


if __name__ == "__main__":
    unittest.main()
