import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from app import constants


class VersionManifestTests(unittest.TestCase):
    def test_packaged_internal_resources_manifest_is_used(self):
        with tempfile.TemporaryDirectory() as temporary:
            internal_resources = Path(temporary) / "resources"
            internal_resources.mkdir()
            (internal_resources / "version.json").write_text(
                json.dumps({"version": "9.8.7"}), encoding="utf-8"
            )
            with patch.object(sys, "frozen", True, create=True), patch.object(
                sys, "_MEIPASS", temporary, create=True
            ), patch.object(
                sys, "executable", str(Path(temporary) / "无忧28.exe")
            ):
                self.assertEqual(constants._load_app_version(), "9.8.7")

    def test_source_manifest_is_the_development_source(self):
        manifest = constants.PROJECT_ROOT / "resources" / "version.json"
        expected = json.loads(manifest.read_text(encoding="utf-8-sig"))["version"]
        self.assertEqual(constants._load_app_version(), expected)


if __name__ == "__main__":
    unittest.main()
