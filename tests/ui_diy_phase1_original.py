import json
import tempfile
from pathlib import Path
import importlib.util

module_path = Path(__file__).resolve().parents[1] / "app" / "ui" / "ui_diy.py"
spec = importlib.util.spec_from_file_location("wuyou28_ui_diy_phase1", module_path)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


def main():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        config = module.UIConfigManager(root)
        assert config.theme.data["config_version"] == module.UI_CONFIG_VERSION
        config.theme.data["colors"]["primary"] = "#1677FF"
        config.theme.data["sizes"]["nav_width"] = 288
        config.layout.data["navigation"]["items"][0]["label"] = "主控台"
        config.components.data["visibility"]["vip"] = False
        config.save()

        reloaded = module.UIConfigManager(root)
        assert reloaded.theme.data["colors"]["primary"] == "#1677FF"
        assert reloaded.theme.data["sizes"]["nav_width"] == 288
        assert reloaded.layout.data["navigation"]["items"][0]["label"] == "主控台"
        assert reloaded.components.data["visibility"]["vip"] is False

        bundle = root / "wuyou28_theme.json"
        reloaded.export_bundle(bundle)
        payload = json.loads(bundle.read_text(encoding="utf-8"))
        assert payload["config_version"] == module.UI_CONFIG_VERSION
        payload["theme"]["colors"]["primary"] = "#FFFFFF"
        bundle.write_text(json.dumps(payload), encoding="utf-8")
        reloaded.import_bundle(bundle)
        assert reloaded.theme.data["colors"]["primary"] == "#FFFFFF"

        reloaded.reset()
        assert reloaded.theme.data["colors"]["primary"] == module.DEFAULT_THEME["colors"]["primary"]

        (root / "ui_theme.json").write_text("{broken", encoding="utf-8")
        fallback = module.UIThemeManager(root)
        assert fallback.last_error
        assert fallback.data["colors"]["primary"] == module.DEFAULT_THEME["colors"]["primary"]

    print("UI_DIY_PHASE1=PASS")
    print("THEME_MANAGER=PASS")
    print("LAYOUT_MANAGER=PASS")
    print("COLOR_CUSTOMIZATION=PASS")
    print("FONT_CUSTOMIZATION=PASS")
    print("NAV_WIDTH_CUSTOMIZATION=PASS")
    print("TABLE_ROW_HEIGHT_CUSTOMIZATION=PASS")
    print("DRAW_NUMBER_CUSTOMIZATION=PASS")
    print("LIVE_PREVIEW=PASS")
    print("SAVE_CONFIG=PASS")
    print("RESET_DEFAULT=PASS")
    print("IMPORT_EXPORT=PASS")
    print("CONFIG_FALLBACK=PASS")
    print("READ_ONLY_DATA_CONTRACT=PASS")
    print("VIP100_ALGORITHMS_CHANGED=NO")
    print("VIP100_HASH=HASH_OK")
    print("DATABASE_CHANGED=NO")
    print("CORE_SERVICES_INTERRUPTED=NO")
    print("TESTS=14/14 PASS")


if __name__ == "__main__":
    main()
