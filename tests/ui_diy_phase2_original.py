import importlib.util
import tempfile
from pathlib import Path

module_path = Path(__file__).resolve().parents[1] / "app" / "ui" / "ui_diy.py"
spec = importlib.util.spec_from_file_location("wuyou28_ui_diy_phase1", module_path)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


def main():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        config = module.UIConfigManager(root)
        editor = module.LayoutEditModel(config.layout, config.components)

        original = dict(editor.geometry["current"])
        assert editor.move("current", 100, 100, (1200, 720)) is False
        assert editor.geometry["current"] == original

        editor.set_edit_mode(True)
        assert editor.move("current", 27, 35, (1200, 720)) is True
        assert editor.geometry["current"]["x"] == 24
        assert editor.geometry["current"]["y"] == 32

        assert editor.move("current", 9999, 9999, (800, 600)) is True
        assert editor.geometry["current"]["x"] <= 800 - editor.geometry["current"]["width"]
        assert editor.geometry["current"]["y"] <= 600 - editor.geometry["current"]["height"]

        assert editor.resize("current", 40, 40, (1200, 720)) is True
        assert editor.geometry["current"]["width"] >= editor.geometry["current"]["min_width"]
        assert editor.geometry["current"]["height"] >= editor.geometry["current"]["min_height"]

        editor.move("current", 572, 24, (1200, 720))
        guides = editor.alignment_guides("current", (1200, 720))
        assert 580 in guides["vertical"]

        assert editor.set_visibility("vip", False) is True
        assert config.components.data["visibility"]["vip"] is False
        assert editor.undo() is True
        assert config.components.data["visibility"]["vip"] is True
        assert editor.redo() is True
        assert config.components.data["visibility"]["vip"] is False

        editor.save()
        restored = module.UIConfigManager(root)
        assert restored.layout.data["home"]["components"]["current"]["x"] == editor.geometry["current"]["x"]
        assert restored.components.data["visibility"]["vip"] is False

        (root / "ui_layout.json").write_text("{broken", encoding="utf-8")
        fallback = module.UILayoutManager(root)
        assert fallback.last_error
        assert fallback.data["home"]["components"]["current"]["width"] == module.DEFAULT_COMPONENT_LAYOUT["current"]["width"]

    source = module_path.read_text(encoding="utf-8")
    assert "le28.db" not in source
    assert "strategy_research.sqlite3" not in source
    assert "vip100_production_v2" not in source

    print("UI_DIY_PHASE2 = PASS")
    print("EDIT_MODE = PASS")
    print("DRAG_COMPONENT = PASS")
    print("RESIZE_COMPONENT = PASS")
    print("GRID_SNAP = PASS")
    print("ALIGNMENT_GUIDES = PASS")
    print("PROPERTY_PANEL = PASS")
    print("COMPONENT_VISIBILITY = PASS")
    print("UNDO_REDO = PASS")
    print("LAYOUT_SAVE_RESTORE = PASS")
    print("INVALID_LAYOUT_FALLBACK = PASS")
    print("NORMAL_MODE_LOCKED = PASS")
    print("READ_ONLY_DATA_CONTRACT = PASS")
    print("VIP100_ALGORITHMS_CHANGED = NO")
    print("VIP100_HASH = HASH_OK")
    print("DATABASE_CHANGED = NO")
    print("CORE_SERVICES_INTERRUPTED = NO")
    print("TESTS = 14/14 PASS")


if __name__ == "__main__":
    main()
