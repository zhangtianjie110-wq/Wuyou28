"""无忧28 UI DIY Phase 1.

This module owns UI configuration only. It does not import or write lottery,
strategy, VIP100, or database modules. PySide6 is optional for config tests;
the desktop shell is enabled when PySide6 is available.
"""
from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable

UI_CONFIG_VERSION = 1
HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

APP_ROOT = Path(__file__).resolve().parent
CONFIG_DIR = APP_ROOT / "config"

DEFAULT_THEME: dict[str, Any] = {
    "config_version": UI_CONFIG_VERSION,
    "colors": {
        "app_background": "#EDF2F7",
        "content_background": "#F7F9FC",
        "card_background": "#FFFFFF",
        "primary": "#2B6ED1",
        "secondary": "#5D83BF",
        "border": "#D7E0EA",
        "success": "#2AA874",
        "warning": "#C68A32",
        "error": "#C64A57",
        "text": "#142238",
        "muted_text": "#78879A",
    },
    "font": {
        "family": "Microsoft YaHei",
        "base_size": 13,
        "title_size": 17,
        "body_size": 13,
        "table_size": 12,
        "number_size": 32,
        "weight": 400,
    },
    "sizes": {
        "nav_width": 216,
        "topbar_height": 46,
        "card_height": 260,
        "table_row_height": 32,
        "button_height": 30,
        "icon_size": 16,
        "draw_number_size": 74,
        "countdown_size": 45,
    },
    "style": {
        "radius": 6,
        "border_width": 1,
        "shadow_enabled": False,
        "shadow_strength": 12,
        "padding": 16,
        "margin": 12,
        "gap": 13,
    },
}

DEFAULT_COMPONENT_LAYOUT: dict[str, Any] = {
    "current": {"x": 24, "y": 24, "width": 540, "height": 260, "min_width": 360, "min_height": 180},
    "next": {"x": 580, "y": 24, "width": 260, "height": 260, "min_width": 220, "min_height": 180},
    "vip": {"x": 856, "y": 24, "width": 300, "height": 260, "min_width": 240, "min_height": 180},
    "history": {"x": 24, "y": 300, "width": 1132, "height": 360, "min_width": 560, "min_height": 220},
    "status": {"x": 24, "y": 672, "width": 1132, "height": 32, "min_width": 480, "min_height": 24},
}

DEFAULT_LAYOUT: dict[str, Any] = {
    "config_version": UI_CONFIG_VERSION,
    "navigation": {
        "width": 216,
        "item_height": 40,
        "item_gap": 4,
        "items": [
            {"id": "home", "label": "首页", "icon": "⌂", "visible": True},
            {"id": "data", "label": "数据中心", "icon": "▤", "visible": True},
            {"id": "vip", "label": "VIP100", "icon": "◇", "visible": True},
            {"id": "strategy", "label": "策略研究", "icon": "⌁", "visible": True},
            {"id": "gap", "label": "遗漏分析", "icon": "◌", "visible": True},
            {"id": "trend", "label": "走势图", "icon": "⌁", "visible": True},
            {"id": "train", "label": "火车路子", "icon": "▥", "visible": True},
            {"id": "settings", "label": "设置", "icon": "⚙", "visible": True},
        ],
    },
    "home": {
        "order": ["current", "next", "vip", "history", "status"],
        "columns": 3,
        "components": DEFAULT_COMPONENT_LAYOUT,
    },
}

DEFAULT_COMPONENTS: dict[str, Any] = {
    "config_version": UI_CONFIG_VERSION,
    "visibility": {
        "current": True,
        "next": True,
        "vip": True,
        "history": True,
        "status": True,
        "scratch_entry": True,
    },
    "styles": {
        "draw_numbers": {
            "shape": "circle",
            "fill": "#2B6ED1",
            "text": "#FFFFFF",
            "size": 74,
            "gap": 11,
        },
        "scratch_dialog": {
            "width": 480,
            "height": 320,
            "background": "#FFFFFF",
            "overlay_alpha": 120,
            "scratch_fill": "#DCE9FB",
            "radius": 8,
            "title_size": 18,
            "button_style": "primary",
        },
    },
}


def _deep_merge(defaults: Any, value: Any) -> Any:
    if isinstance(defaults, dict) and isinstance(value, dict):
        result = copy.deepcopy(defaults)
        for key, item in value.items():
            result[key] = _deep_merge(result[key], item) if key in result else copy.deepcopy(item)
        return result
    return copy.deepcopy(value) if value is not None else copy.deepcopy(defaults)


def _clamp_int(value: Any, low: int, high: int, fallback: int) -> int:
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return fallback


def _hex(value: Any, fallback: str) -> str:
    return str(value).upper() if HEX_RE.fullmatch(str(value)) else fallback


def _sanitize_theme(theme: dict[str, Any]) -> dict[str, Any]:
    merged = _deep_merge(DEFAULT_THEME, theme)
    for key, fallback in DEFAULT_THEME["colors"].items():
        merged["colors"][key] = _hex(merged["colors"].get(key), fallback)
    merged["font"]["base_size"] = _clamp_int(merged["font"].get("base_size"), 10, 24, 13)
    merged["font"]["title_size"] = _clamp_int(merged["font"].get("title_size"), 12, 32, 17)
    merged["font"]["body_size"] = _clamp_int(merged["font"].get("body_size"), 10, 24, 13)
    merged["font"]["table_size"] = _clamp_int(merged["font"].get("table_size"), 10, 20, 12)
    merged["font"]["number_size"] = _clamp_int(merged["font"].get("number_size"), 16, 96, 32)
    merged["sizes"]["nav_width"] = _clamp_int(merged["sizes"].get("nav_width"), 168, 320, 216)
    merged["sizes"]["topbar_height"] = _clamp_int(merged["sizes"].get("topbar_height"), 34, 80, 46)
    merged["sizes"]["card_height"] = _clamp_int(merged["sizes"].get("card_height"), 160, 480, 260)
    merged["sizes"]["table_row_height"] = _clamp_int(merged["sizes"].get("table_row_height"), 24, 64, 32)
    merged["sizes"]["button_height"] = _clamp_int(merged["sizes"].get("button_height"), 24, 52, 30)
    merged["sizes"]["draw_number_size"] = _clamp_int(merged["sizes"].get("draw_number_size"), 44, 120, 74)
    merged["sizes"]["countdown_size"] = _clamp_int(merged["sizes"].get("countdown_size"), 24, 80, 45)
    merged["style"]["radius"] = _clamp_int(merged["style"].get("radius"), 0, 18, 6)
    merged["style"]["padding"] = _clamp_int(merged["style"].get("padding"), 4, 36, 16)
    merged["style"]["gap"] = _clamp_int(merged["style"].get("gap"), 4, 32, 13)
    merged["config_version"] = UI_CONFIG_VERSION
    return merged


def _sanitize_layout(layout: dict[str, Any]) -> dict[str, Any]:
    merged = _deep_merge(DEFAULT_LAYOUT, layout)
    nav = merged["navigation"]
    nav["width"] = _clamp_int(nav.get("width"), 168, 320, 216)
    nav["item_height"] = _clamp_int(nav.get("item_height"), 28, 64, 40)
    nav["item_gap"] = _clamp_int(nav.get("item_gap"), 0, 20, 4)
    valid_ids = {item["id"] for item in DEFAULT_LAYOUT["navigation"]["items"]}
    items = []
    for item in nav.get("items", []):
        if not isinstance(item, dict) or item.get("id") not in valid_ids:
            continue
        base = next(x for x in DEFAULT_LAYOUT["navigation"]["items"] if x["id"] == item["id"])
        clean = _deep_merge(base, item)
        clean["label"] = str(clean.get("label", base["label"]))[:24] or base["label"]
        clean["icon"] = str(clean.get("icon", base["icon"]))[:2] or base["icon"]
        clean["visible"] = bool(clean.get("visible", True))
        items.append(clean)
    seen = {item["id"] for item in items}
    items.extend(copy.deepcopy(item) for item in DEFAULT_LAYOUT["navigation"]["items"] if item["id"] not in seen)
    nav["items"] = items
    home = merged["home"]
    clean_components = {}
    for component_id, default in DEFAULT_COMPONENT_LAYOUT.items():
        value = home.get("components", {}).get(component_id, {})
        geometry = _deep_merge(default, value if isinstance(value, dict) else {})
        geometry["min_width"] = _clamp_int(geometry.get("min_width"), 120, 2000, default["min_width"])
        geometry["min_height"] = _clamp_int(geometry.get("min_height"), 24, 1200, default["min_height"])
        geometry["width"] = _clamp_int(geometry.get("width"), geometry["min_width"], 4000, default["width"])
        geometry["height"] = _clamp_int(geometry.get("height"), geometry["min_height"], 2400, default["height"])
        geometry["x"] = _clamp_int(geometry.get("x"), 0, 4000, default["x"])
        geometry["y"] = _clamp_int(geometry.get("y"), 0, 2400, default["y"])
        clean_components[component_id] = geometry
    home["components"] = clean_components
    merged["config_version"] = UI_CONFIG_VERSION
    return merged


def _sanitize_components(components: dict[str, Any]) -> dict[str, Any]:
    merged = _deep_merge(DEFAULT_COMPONENTS, components)
    merged["config_version"] = UI_CONFIG_VERSION
    for key in DEFAULT_COMPONENTS["visibility"]:
        merged["visibility"][key] = bool(merged["visibility"].get(key, True))
    draw = merged["styles"]["draw_numbers"]
    draw["shape"] = draw.get("shape", "circle") if draw.get("shape") in {"circle", "rounded", "square"} else "circle"
    draw["fill"] = _hex(draw.get("fill"), "#2B6ED1")
    draw["text"] = _hex(draw.get("text"), "#FFFFFF")
    draw["size"] = _clamp_int(draw.get("size"), 44, 120, 74)
    draw["gap"] = _clamp_int(draw.get("gap"), 4, 32, 11)
    return merged


class _JsonManager:
    defaults: dict[str, Any] = {}
    filename = ""

    def __init__(self, config_dir: Path | str = CONFIG_DIR):
        self.config_dir = Path(config_dir)
        self.path = self.config_dir / self.filename
        self.data: dict[str, Any] = {}
        self.last_error = ""
        self._listeners: list[Callable[[dict[str, Any]], None]] = []
        self.load()

    def add_listener(self, callback: Callable[[dict[str, Any]], None]) -> None:
        self._listeners.append(callback)

    def _emit(self) -> None:
        for callback in tuple(self._listeners):
            callback(copy.deepcopy(self.data))

    def load(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
            if not isinstance(raw, dict) or raw.get("config_version", UI_CONFIG_VERSION) != UI_CONFIG_VERSION:
                raise ValueError("unsupported UI config version")
            self.data = self.sanitize(raw)
            self.last_error = ""
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self.data = self.sanitize(copy.deepcopy(self.defaults))
            self.last_error = str(exc)
        return copy.deepcopy(self.data)

    def save(self) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.path)

    def reset(self) -> None:
        self.data = self.sanitize(copy.deepcopy(self.defaults))
        self._emit()

    def update(self, data: dict[str, Any], persist: bool = False) -> None:
        self.data = self.sanitize(_deep_merge(self.defaults, data))
        self._emit()
        if persist:
            self.save()

    def sanitize(self, data: dict[str, Any]) -> dict[str, Any]:
        return copy.deepcopy(data)


class UIThemeManager(_JsonManager):
    defaults = DEFAULT_THEME
    filename = "ui_theme.json"

    def sanitize(self, data: dict[str, Any]) -> dict[str, Any]:
        return _sanitize_theme(data)


class UILayoutManager(_JsonManager):
    defaults = DEFAULT_LAYOUT
    filename = "ui_layout.json"

    def sanitize(self, data: dict[str, Any]) -> dict[str, Any]:
        return _sanitize_layout(data)


class UIComponentManager(_JsonManager):
    defaults = DEFAULT_COMPONENTS
    filename = "ui_components.json"

    def sanitize(self, data: dict[str, Any]) -> dict[str, Any]:
        return _sanitize_components(data)


class UIConfigManager:
    def __init__(self, config_dir: Path | str = CONFIG_DIR):
        self.config_dir = Path(config_dir)
        self.theme = UIThemeManager(self.config_dir)
        self.layout = UILayoutManager(self.config_dir)
        self.components = UIComponentManager(self.config_dir)

    def save(self) -> None:
        self.theme.save()
        self.layout.save()
        self.components.save()

    def reset(self) -> None:
        self.theme.reset()
        self.layout.reset()
        self.components.reset()

    def export_bundle(self, destination: Path | str) -> None:
        payload = {
            "config_version": UI_CONFIG_VERSION,
            "theme": copy.deepcopy(self.theme.data),
            "layout": copy.deepcopy(self.layout.data),
            "components": copy.deepcopy(self.components.data),
        }
        Path(destination).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def import_bundle(self, source: Path | str) -> None:
        raw = json.loads(Path(source).read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("config_version") != UI_CONFIG_VERSION:
            raise ValueError("unsupported UI config version")
        for key in ("theme", "layout", "components"):
            if not isinstance(raw.get(key), dict):
                raise ValueError(f"missing {key} config")
        self.theme.update(raw["theme"])
        self.layout.update(raw["layout"])
        self.components.update(raw["components"])
        self.save()

GRID_SIZE = 8
UNDO_LIMIT = 30


class LayoutEditModel:
    """Pure-Python layout editor state used by Qt and headless tests."""

    def __init__(self, layout: UILayoutManager, components: UIComponentManager, grid_size: int = GRID_SIZE):
        self.layout = layout
        self.components = components
        self.grid_size = max(1, int(grid_size))
        self.edit_mode = False
        self.selected_id: str | None = None
        self._undo: list[dict[str, Any]] = []
        self._redo: list[dict[str, Any]] = []

    @property
    def geometry(self) -> dict[str, dict[str, int]]:
        return self.layout.data["home"]["components"]

    def _snapshot(self) -> dict[str, Any]:
        return {"components": copy.deepcopy(self.geometry), "visibility": copy.deepcopy(self.components.data["visibility"])}

    def _restore_snapshot(self, snapshot: dict[str, Any]) -> None:
        self.layout.data["home"]["components"] = copy.deepcopy(snapshot["components"])
        self.components.data["visibility"] = copy.deepcopy(snapshot["visibility"])

    def _checkpoint(self) -> None:
        self._undo.append(self._snapshot())
        if len(self._undo) > UNDO_LIMIT:
            self._undo.pop(0)
        self._redo.clear()

    def begin_change(self) -> None:
        if self.edit_mode:
            self._checkpoint()

    def set_edit_mode(self, enabled: bool) -> None:
        self.edit_mode = bool(enabled)
        if not self.edit_mode:
            self.selected_id = None

    def select(self, component_id: str | None) -> bool:
        if component_id is None or component_id in self.geometry:
            self.selected_id = component_id
            return True
        return False

    def _snap(self, value: int) -> int:
        return int(round(value / self.grid_size) * self.grid_size)

    def _clamp_position(self, component_id: str, x: int, y: int, bounds: tuple[int, int]) -> tuple[int, int]:
        item = self.geometry[component_id]
        return max(0, min(self._snap(x), max(0, bounds[0] - item["width"]))), max(0, min(self._snap(y), max(0, bounds[1] - item["height"])))

    def move(self, component_id: str, x: int, y: int, bounds: tuple[int, int], record: bool = True) -> bool:
        if not self.edit_mode or component_id not in self.geometry:
            return False
        if record:
            self._checkpoint()
        self.geometry[component_id]["x"], self.geometry[component_id]["y"] = self._clamp_position(component_id, int(x), int(y), bounds)
        self.selected_id = component_id
        return True

    def resize(self, component_id: str, width: int, height: int, bounds: tuple[int, int], record: bool = True, x: int | None = None, y: int | None = None) -> bool:
        if not self.edit_mode or component_id not in self.geometry:
            return False
        if record:
            self._checkpoint()
        item = self.geometry[component_id]
        item["width"] = max(item["min_width"], min(self._snap(int(width)), max(item["min_width"], bounds[0] - item["x"])))
        item["height"] = max(item["min_height"], min(self._snap(int(height)), max(item["min_height"], bounds[1] - item["y"])))
        if x is not None:
            item["x"] = max(0, min(self._snap(int(x)), max(0, bounds[0] - item["width"])))
        if y is not None:
            item["y"] = max(0, min(self._snap(int(y)), max(0, bounds[1] - item["height"])))
        self.selected_id = component_id
        return True

    def set_geometry(self, component_id: str, **values: int) -> bool:
        if not self.edit_mode or component_id not in self.geometry:
            return False
        self._checkpoint()
        item = self.geometry[component_id]
        for key in ("x", "y", "width", "height"):
            if key in values:
                item[key] = int(values[key])
        self.layout.data = _sanitize_layout(self.layout.data)
        self.selected_id = component_id
        return True

    def set_visibility(self, component_id: str, visible: bool) -> bool:
        if not self.edit_mode or component_id not in self.components.data["visibility"]:
            return False
        self._checkpoint()
        self.components.data["visibility"][component_id] = bool(visible)
        return True

    def alignment_guides(self, component_id: str, bounds: tuple[int, int], threshold: int = GRID_SIZE) -> dict[str, list[int]]:
        if component_id not in self.geometry:
            return {"vertical": [], "horizontal": []}
        current = self.geometry[component_id]
        x_edges = [0, bounds[0], current["x"], current["x"] + current["width"], current["x"] + current["width"] // 2]
        y_edges = [0, bounds[1], current["y"], current["y"] + current["height"], current["y"] + current["height"] // 2]
        vertical: list[int] = []
        horizontal: list[int] = []
        for other_id, other in self.geometry.items():
            if other_id == component_id:
                continue
            for value in (other["x"], other["x"] + other["width"], other["x"] + other["width"] // 2):
                if any(abs(value - candidate) <= threshold for candidate in x_edges):
                    vertical.append(value)
            for value in (other["y"], other["y"] + other["height"], other["y"] + other["height"] // 2):
                if any(abs(value - candidate) <= threshold for candidate in y_edges):
                    horizontal.append(value)
        return {"vertical": sorted(set(vertical)), "horizontal": sorted(set(horizontal))}

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self._snapshot())
        self._restore_snapshot(self._undo.pop())
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self._snapshot())
        self._restore_snapshot(self._redo.pop())
        return True

    def save(self) -> None:
        self.layout.data = _sanitize_layout(self.layout.data)
        self.components.data = _sanitize_components(self.components.data)
        self.layout.save()
        self.components.save()

    def reset(self) -> None:
        self._checkpoint()
        self.layout.reset()
        self.components.reset()


try:
    from PySide6.QtCore import QEvent, QPoint, Qt, Signal
    from PySide6.QtGui import QColor, QFont
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QColorDialog,
        QComboBox,
        QFileDialog,
        QFontComboBox,
        QFormLayout,
        QFrame,
        QGridLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QScrollArea,
        QSizePolicy,
        QSpinBox,
        QStackedWidget,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
    )

    QT_AVAILABLE = True
except ImportError:
    QT_AVAILABLE = False


if QT_AVAILABLE:
    class EditableComponent(QFrame):
        def __init__(self, editor: "LayoutEditorWidget", component_id: str, title: str):
            super().__init__(editor)
            self.editor = editor
            self.component_id = component_id
            self.setObjectName("editComponent")
            self.header = QLabel(title, self)
            self.header.setObjectName("componentHeader")
            self.header.installEventFilter(self)
            self.body = QLabel("可视化组件 · 双击或拖动标题区域", self)
            self.body.setObjectName("componentBody")
            self.body.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.handles: dict[str, QFrame] = {}
            for name in ("nw", "n", "ne", "e", "se", "s", "sw", "w"):
                handle = QFrame(self)
                handle.setObjectName("resizeHandle")
                handle.installEventFilter(self)
                self.handles[name] = handle
            self.setMinimumSize(120, 80)

        def eventFilter(self, watched: QWidget, event: QEvent) -> bool:
            if watched is self.header:
                if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                    self.editor.begin_drag(self, event.globalPosition().toPoint())
                    return True
                if event.type() == QEvent.Type.MouseMove and event.buttons() & Qt.MouseButton.LeftButton:
                    self.editor.drag_move(event.globalPosition().toPoint())
                    return True
                if event.type() == QEvent.Type.MouseButtonRelease:
                    self.editor.end_interaction()
                    return True
            for name, handle in self.handles.items():
                if watched is handle:
                    if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                        self.editor.begin_resize(self, name, event.globalPosition().toPoint())
                        return True
                    if event.type() == QEvent.Type.MouseMove and event.buttons() & Qt.MouseButton.LeftButton:
                        self.editor.resize_move(event.globalPosition().toPoint())
                        return True
                    if event.type() == QEvent.Type.MouseButtonRelease:
                        self.editor.end_interaction()
                        return True
            return super().eventFilter(watched, event)

        def mousePressEvent(self, event: Any) -> None:
            if event.button() == Qt.MouseButton.LeftButton:
                self.editor.select_component(self)
            super().mousePressEvent(event)

        def resizeEvent(self, event: Any) -> None:
            self.header.setGeometry(0, 0, self.width(), 30)
            self.body.setGeometry(0, 30, self.width(), max(0, self.height() - 30))
            self.update_handles()
            super().resizeEvent(event)

        def update_handles(self) -> None:
            size = 8
            w, h = self.width(), self.height()
            positions = {
                "nw": (0, 0), "n": ((w - size) // 2, 0), "ne": (w - size, 0),
                "e": (w - size, (h - size) // 2), "se": (w - size, h - size),
                "s": ((w - size) // 2, h - size), "sw": (0, h - size), "w": (0, (h - size) // 2),
            }
            for name, (x, y) in positions.items():
                self.handles[name].setGeometry(x, y, size, size)
                self.handles[name].setVisible(self.editor.edit_mode and self.editor.selected is self)


    class LayoutEditorWidget(QFrame):
        def __init__(self, model: LayoutEditModel, parent: QWidget | None = None):
            super().__init__(parent)
            self.model = model
            self.edit_mode = False
            self.selected: EditableComponent | None = None
            self._active: dict[str, Any] | None = None
            self._guides: list[QFrame] = []
            self.on_selected: Callable[[str | None], None] | None = None
            self.setObjectName("layoutCanvas")
            self.setMinimumSize(900, 700)
            self.widgets: dict[str, EditableComponent] = {}
            titles = {"current": "当前开奖", "next": "下一期开奖", "vip": "VIP100", "history": "最近10期开奖", "status": "顶部状态"}
            for component_id, title in titles.items():
                self.widgets[component_id] = EditableComponent(self, component_id, title)
            self.refresh_from_model()

        def set_edit_mode(self, enabled: bool) -> None:
            self.edit_mode = bool(enabled)
            self.model.set_edit_mode(enabled)
            self.refresh_from_model()

        def _bounds(self) -> tuple[int, int]:
            return max(1, self.width()), max(1, self.height())

        def select_component(self, component: EditableComponent | None) -> None:
            self.selected = component
            self.model.select(component.component_id if component else None)
            self.refresh_from_model()
            if self.on_selected:
                self.on_selected(component.component_id if component else None)

        def begin_drag(self, component: EditableComponent, point: QPoint) -> None:
            if not self.edit_mode:
                return
            self.select_component(component)
            geometry = self.model.geometry[component.component_id]
            self.model.begin_change()
            self._active = {"kind": "move", "component": component.component_id, "point": point, "x": geometry["x"], "y": geometry["y"]}

        def drag_move(self, point: QPoint) -> None:
            if not self._active or self._active["kind"] != "move":
                return
            dx = point.x() - self._active["point"].x()
            dy = point.y() - self._active["point"].y()
            self.model.move(self._active["component"], self._active["x"] + dx, self._active["y"] + dy, self._bounds(), record=False)
            self.refresh_from_model()
            self.show_guides(self._active["component"])

        def begin_resize(self, component: EditableComponent, handle: str, point: QPoint) -> None:
            if not self.edit_mode:
                return
            self.select_component(component)
            geometry = self.model.geometry[component.component_id]
            self.model.begin_change()
            self._active = {"kind": "resize", "handle": handle, "component": component.component_id, "point": point, "x": geometry["x"], "y": geometry["y"], "width": geometry["width"], "height": geometry["height"]}

        def resize_move(self, point: QPoint) -> None:
            if not self._active or self._active["kind"] != "resize":
                return
            dx = point.x() - self._active["point"].x()
            dy = point.y() - self._active["point"].y()
            handle = self._active["handle"]
            width = self._active["width"] + (dx if "e" in handle else -dx if "w" in handle else 0)
            height = self._active["height"] + (dy if "s" in handle else -dy if "n" in handle else 0)
            x = self._active["x"] + (dx if "w" in handle else 0)
            y = self._active["y"] + (dy if "n" in handle else 0)
            self.model.resize(self._active["component"], width, height, self._bounds(), record=False, x=x, y=y)
            self.refresh_from_model()

        def end_interaction(self) -> None:
            self._active = None
            self.clear_guides()

        def show_guides(self, component_id: str) -> None:
            self.clear_guides()
            guides = self.model.alignment_guides(component_id, self._bounds())
            for x in guides["vertical"]:
                line = QFrame(self)
                line.setObjectName("alignmentGuide")
                line.setGeometry(x, 0, 1, self.height())
                line.show()
                self._guides.append(line)
            for y in guides["horizontal"]:
                line = QFrame(self)
                line.setObjectName("alignmentGuide")
                line.setGeometry(0, y, self.width(), 1)
                line.show()
                self._guides.append(line)

        def clear_guides(self) -> None:
            for line in self._guides:
                line.deleteLater()
            self._guides.clear()

        def refresh_from_model(self) -> None:
            for component_id, widget in self.widgets.items():
                geometry = self.model.geometry[component_id]
                visible = self.model.components.data["visibility"].get(component_id, True)
                widget.setGeometry(geometry["x"], geometry["y"], geometry["width"], geometry["height"])
                widget.setVisible(visible and self.edit_mode)
                widget.setProperty("selected", widget is self.selected)
                widget.style().unpolish(widget)
                widget.style().polish(widget)
                widget.update_handles()

    class MainWindow(QMainWindow):
        """A Phase 1 shell with live theme/layout controls."""

        def __init__(self, config: UIConfigManager | None = None):
            super().__init__()
            self.config = config or UIConfigManager()
            self.layout_model = LayoutEditModel(self.config.layout, self.config.components)
            self.setWindowTitle("无忧28 · UI DIY Phase 1")
            self.resize(1280, 820)
            self._theme_fields: dict[str, QLineEdit] = {}
            self._number_label: QLabel | None = None
            self._countdown_label: QLabel | None = None
            self._table: QTableWidget | None = None
            self.editor_page: QWidget | None = None
            self.editor: LayoutEditorWidget | None = None
            self.geometry_fields: dict[str, QSpinBox] = {}
            self.visibility_checks: dict[str, QCheckBox] = {}
            self._build_shell()
            self._apply_ui()

        def _build_shell(self) -> None:
            root = QWidget()
            root_layout = QHBoxLayout(root)
            root_layout.setContentsMargins(0, 0, 0, 0)
            root_layout.setSpacing(0)
            self.sidebar = QFrame()
            self.sidebar_layout = QVBoxLayout(self.sidebar)
            self.sidebar_layout.setContentsMargins(12, 16, 12, 12)
            self.sidebar_layout.setSpacing(4)
            self.nav_buttons: dict[str, QPushButton] = {}
            for item in self.config.layout.data["navigation"]["items"]:
                button = QPushButton(f"{item['icon']}  {item['label']}")
                button.setProperty("navId", item["id"])
                button.clicked.connect(lambda checked=False, nav_id=item["id"]: self._show_page(nav_id))
                self.nav_buttons[item["id"]] = button
                self.sidebar_layout.addWidget(button)
            self.sidebar_layout.addStretch(1)
            root_layout.addWidget(self.sidebar)
            self.stack = QStackedWidget()
            self.home_page = self._build_home_page()
            self.settings_page = self._build_settings_page()
            self.stack.addWidget(self.home_page)
            self.stack.addWidget(self.settings_page)
            root_layout.addWidget(self.stack, 1)
            self.setCentralWidget(root)

        def _build_home_page(self) -> QWidget:
            page = QWidget()
            outer = QVBoxLayout(page)
            outer.setContentsMargins(20, 16, 20, 12)
            outer.setSpacing(12)
            heading = QLabel("首页  /  实时数据总览")
            heading.setObjectName("pageTitle")
            outer.addWidget(heading)
            cards = QHBoxLayout()
            cards.setSpacing(12)
            current = self._card("当前开奖", "20240718-093\n07   +   18   +   26")
            self._number_label = current.findChild(QLabel, "cardValue")
            next_card = self._card("下一期", "20240718-094\n02:18")
            self._countdown_label = next_card.findChild(QLabel, "cardValue")
            vip = self._card("VIP100", "100 / 100\nHASH_OK\n大单 23   大双 18")
            cards.addWidget(current, 2)
            cards.addWidget(next_card, 1)
            cards.addWidget(vip, 1)
            outer.addLayout(cards)
            history = QFrame()
            history.setObjectName("card")
            history_layout = QVBoxLayout(history)
            history_layout.addWidget(QLabel("近期 10 期"))
            self._table = QTableWidget(10, 5)
            self._table.setHorizontalHeaderLabels(["期号", "开奖时间", "开奖号码", "和值", "四组合"])
            rows = [
                ("20240718-093", "21:30", "07  18  26", "51", "大单"),
                ("20240718-092", "21:25", "03  14  22", "39", "大双"),
                ("20240718-091", "21:20", "04  09  11", "24", "小单"),
                ("20240718-090", "21:15", "10  12  25", "47", "大单"),
                ("20240718-089", "21:10", "02  16  20", "38", "大双"),
                ("20240718-088", "21:05", "01  08  13", "22", "小双"),
                ("20240718-087", "21:00", "06  17  24", "47", "大单"),
                ("20240718-086", "20:55", "05  15  19", "39", "大单"),
                ("20240718-085", "20:50", "08  12  21", "41", "大单"),
                ("20240718-084", "20:45", "04  07  18", "29", "小单"),
            ]
            for row, values in enumerate(rows):
                for column, value in enumerate(values):
                    self._table.setItem(row, column, QTableWidgetItem(value))
            history_layout.addWidget(self._table)
            outer.addWidget(history, 1)
            status = QLabel("● YU28 正常    ● VIP100 正常    ● StrategyResearchEngine 正常    ● 数据健康 正常")
            status.setObjectName("statusStrip")
            outer.addWidget(status)
            return page

        def _card(self, title: str, value: str) -> QFrame:
            frame = QFrame()
            frame.setObjectName("card")
            layout = QVBoxLayout(frame)
            label = QLabel(title)
            label.setObjectName("cardTitle")
            value_label = QLabel(value)
            value_label.setObjectName("cardValue")
            value_label.setWordWrap(True)
            layout.addWidget(label)
            layout.addWidget(value_label)
            layout.addStretch(1)
            return frame

        def _build_settings_page(self) -> QWidget:
            page = QWidget()
            outer = QVBoxLayout(page)
            title = QLabel("设置  /  界面设置")
            title.setObjectName("pageTitle")
            outer.addWidget(title)
            edit_button = QPushButton("编辑界面")
            edit_button.setToolTip("进入 Layout Edit Mode，拖动或调整首页组件")
            edit_button.clicked.connect(self._enter_edit_mode)
            outer.addWidget(edit_button)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            body = QWidget()
            form = QFormLayout(body)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
            for key, label in [("app_background", "软件背景色"), ("content_background", "内容背景色"), ("card_background", "卡片背景色"), ("primary", "主色"), ("border", "边框色"), ("text", "文字主色"), ("muted_text", "次级文字色")]:
                field = QLineEdit(self.config.theme.data["colors"][key])
                field.textChanged.connect(lambda value, color_key=key: self._update_color(color_key, value))
                self._theme_fields[key] = field
                form.addRow(label, field)
            font_box = QFontComboBox()
            font_box.setCurrentFont(QFont(self.config.theme.data["font"]["family"]))
            font_box.currentFontChanged.connect(lambda font: self._update_font("family", font.family()))
            form.addRow("字体", font_box)
            for key, label, low, high in [("base_size", "全局字号", 10, 24), ("title_size", "标题字号", 12, 32), ("table_size", "表格字号", 10, 20), ("number_size", "数字字号", 16, 96), ("nav_width", "导航宽度", 168, 320), ("table_row_height", "表格行高", 24, 64), ("draw_number_size", "开奖数字大小", 44, 120)]:
                group = QSpinBox()
                group.setRange(low, high)
                source = "font" if key in {"base_size", "title_size", "table_size", "number_size"} else "sizes"
                group.setValue(self.config.theme.data[source][key])
                group.valueChanged.connect(lambda value, section=source, setting=key: self._update_number(section, setting, value))
                form.addRow(label, group)
            buttons = QHBoxLayout()
            save = QPushButton("保存当前布局")
            save.clicked.connect(self._save)
            export = QPushButton("导出 JSON")
            export.clicked.connect(self._export)
            import_button = QPushButton("导入 JSON")
            import_button.clicked.connect(self._import)
            reset = QPushButton("恢复默认界面")
            reset.clicked.connect(self._reset)
            for button in (save, export, import_button, reset):
                buttons.addWidget(button)
            form.addRow(buttons)
            scroll.setWidget(body)
            outer.addWidget(scroll, 1)
            return page

        def _enter_edit_mode(self) -> None:
            if self.editor_page is None:
                self.editor_page = self._build_edit_page()
                self.stack.addWidget(self.editor_page)
            self.layout_model.set_edit_mode(True)
            if self.editor:
                self.editor.set_edit_mode(True)
            self.stack.setCurrentWidget(self.editor_page)

        def _build_edit_page(self) -> QWidget:
            page = QWidget()
            outer = QVBoxLayout(page)
            outer.setContentsMargins(12, 10, 12, 10)
            outer.setSpacing(8)
            toolbar = QHBoxLayout()
            label = QLabel("首页 · Layout Edit Mode")
            label.setObjectName("pageTitle")
            toolbar.addWidget(label)
            for text, callback in [("保存布局", self._editor_save), ("撤销", self._editor_undo), ("重做", self._editor_redo), ("恢复默认布局", self._editor_reset), ("退出编辑", self._exit_edit_mode)]:
                button = QPushButton(text)
                button.clicked.connect(callback)
                toolbar.addWidget(button)
            toolbar.addStretch(1)
            outer.addLayout(toolbar)
            work = QHBoxLayout()
            self.editor = LayoutEditorWidget(self.layout_model)
            self.editor.on_selected = self._select_component
            work.addWidget(self.editor, 1)
            work.addWidget(self._build_property_panel())
            outer.addLayout(work, 1)
            return page

        def _build_property_panel(self) -> QWidget:
            panel = QFrame()
            panel.setObjectName("propertyPanel")
            panel.setMinimumWidth(260)
            layout = QVBoxLayout(panel)
            title = QLabel("属性")
            title.setObjectName("panelTitle")
            layout.addWidget(title)
            self.property_hint = QLabel("选择一个组件开始编辑")
            self.property_hint.setWordWrap(True)
            layout.addWidget(self.property_hint)
            form = QFormLayout()
            for key, label in [("x", "X"), ("y", "Y"), ("width", "宽度"), ("height", "高度")]:
                field = QSpinBox()
                field.setRange(0, 4000)
                field.valueChanged.connect(lambda value, name=key: self._editor_geometry_changed(name, value))
                self.geometry_fields[key] = field
                form.addRow(label, field)
            layout.addLayout(form)
            layout.addWidget(QLabel("组件显示"))
            for component_id, label in [("current", "当前开奖"), ("next", "下一期开奖"), ("vip", "VIP100"), ("history", "最近开奖"), ("status", "顶部状态")]:
                check = QCheckBox(label)
                check.setChecked(self.config.components.data["visibility"].get(component_id, True))
                check.toggled.connect(lambda checked, cid=component_id: self._editor_visibility_changed(cid, checked))
                self.visibility_checks[component_id] = check
                layout.addWidget(check)
            layout.addStretch(1)
            return panel

        def _select_component(self, component_id: str | None) -> None:
            if not component_id or component_id not in self.layout_model.geometry:
                self.property_hint.setText("选择一个组件开始编辑")
                return
            self.property_hint.setText(f"正在编辑：{component_id}\n8px 网格吸附 · 最小尺寸已保护")
            geometry = self.layout_model.geometry[component_id]
            for key, field in self.geometry_fields.items():
                field.blockSignals(True)
                field.setValue(geometry[key])
                field.blockSignals(False)

        def _editor_geometry_changed(self, key: str, value: int) -> None:
            component_id = self.layout_model.selected_id
            if component_id and self.layout_model.set_geometry(component_id, **{key: value}):
                if self.editor:
                    self.editor.refresh_from_model()

        def _editor_visibility_changed(self, component_id: str, visible: bool) -> None:
            if self.layout_model.set_visibility(component_id, visible) and self.editor:
                self.editor.refresh_from_model()

        def _editor_save(self) -> None:
            self.layout_model.save()

        def _editor_undo(self) -> None:
            if self.layout_model.undo() and self.editor:
                self.editor.refresh_from_model()
                self._select_component(self.layout_model.selected_id)

        def _editor_redo(self) -> None:
            if self.layout_model.redo() and self.editor:
                self.editor.refresh_from_model()
                self._select_component(self.layout_model.selected_id)

        def _editor_reset(self) -> None:
            self.layout_model.reset()
            if self.editor:
                self.editor.refresh_from_model()
                self._select_component(None)

        def _exit_edit_mode(self) -> None:
            self.layout_model.set_edit_mode(False)
            if self.editor:
                self.editor.set_edit_mode(False)
            self.stack.setCurrentWidget(self.home_page)

        def _show_page(self, nav_id: str) -> None:
            if nav_id == "settings":
                self.stack.setCurrentWidget(self.settings_page)
            else:
                self.stack.setCurrentWidget(self.home_page)

        def _update_color(self, key: str, value: str) -> None:
            if HEX_RE.fullmatch(value):
                self.config.theme.data["colors"][key] = value.upper()
                self._apply_ui()

        def _update_font(self, key: str, value: Any) -> None:
            self.config.theme.data["font"][key] = value
            self._apply_ui()

        def _update_number(self, section: str, key: str, value: int) -> None:
            self.config.theme.data[section][key] = int(value)
            self._apply_ui()

        def _apply_ui(self) -> None:
            theme = self.config.theme.data
            colors = theme["colors"]
            font = theme["font"]
            sizes = theme["sizes"]
            self.sidebar.setFixedWidth(sizes["nav_width"])
            if self._table:
                self._table.verticalHeader().setDefaultSectionSize(sizes["table_row_height"])
                self._table.setStyleSheet(f"font-size:{font['table_size']}px")
            if self._number_label:
                self._number_label.setStyleSheet(f"font-size:{sizes['draw_number_size']}px;color:{colors['primary']};font-weight:600")
            if self._countdown_label:
                self._countdown_label.setStyleSheet(f"font-size:{sizes['countdown_size']}px;color:{colors['primary']};font-weight:600")
            self.setStyleSheet(self._stylesheet())

        def _stylesheet(self) -> str:
            theme = self.config.theme.data
            c, f, s, st = theme["colors"], theme["font"], theme["sizes"], theme["style"]
            shadow = "0 3px 12px rgba(20,34,56,0.12)" if st["shadow_enabled"] else "none"
            return f"""
                QMainWindow, QWidget {{ background:{c['content_background']}; color:{c['text']}; font-family:'{f['family']}'; font-size:{f['body_size']}px; }}
                QFrame#card {{ background:{c['card_background']}; border:{st['border_width']}px solid {c['border']}; border-radius:{st['radius']}px; padding:{st['padding']}px; }}
                QFrame#card {{ box-shadow:{shadow}; }}
                QFrame#layoutCanvas {{ background:{c['content_background']}; border:1px solid {c['border']}; }}
                QFrame#editComponent {{ background:{c['card_background']}; border:1px solid {c['border']}; border-radius:{st['radius']}px; }}
                QFrame#editComponent[selected="true"] {{ border:2px solid {c['primary']}; }}
                QLabel#componentHeader {{ background:{c['content_background']}; color:{c['primary']}; padding:4px 8px; font-weight:600; }}
                QLabel#componentBody {{ color:{c['muted_text']}; padding:8px; }}
                QFrame#resizeHandle {{ background:{c['primary']}; border-radius:2px; }}
                QFrame#alignmentGuide {{ background:{c['primary']}; }}
                QFrame#propertyPanel {{ background:{c['card_background']}; border:1px solid {c['border']}; border-radius:{st['radius']}px; padding:{st['padding']}px; }}
                QLabel#panelTitle {{ font-size:{f['title_size']}px; font-weight:600; }}
                QFrame {{ border:0; }}
                QPushButton {{ min-height:{s['button_height']}px; border:1px solid {c['border']}; border-radius:{st['radius']}px; padding:0 12px; background:{c['card_background']}; color:{c['text']}; }}
                QPushButton:hover {{ border-color:{c['primary']}; color:{c['primary']}; }}
                QPushButton[navId] {{ text-align:left; border:0; background:transparent; min-height:{self.config.layout.data['navigation']['item_height']}px; }}
                QPushButton[navId]:hover {{ background:{c['content_background']}; color:{c['primary']}; }}
                QLineEdit, QSpinBox, QComboBox {{ min-height:{s['button_height']}px; border:1px solid {c['border']}; border-radius:{st['radius']}px; background:{c['card_background']}; padding:0 8px; }}
                QTableWidget {{ background:{c['card_background']}; border:1px solid {c['border']}; gridline-color:{c['border']}; }}
                QLabel#pageTitle {{ font-size:{f['title_size']}px; font-weight:600; color:{c['text']}; padding-bottom:4px; }}
                QLabel#cardTitle {{ color:{c['muted_text']}; font-size:{f['body_size']}px; }}
                QLabel#statusStrip {{ color:{c['success']}; border-top:1px solid {c['border']}; padding:8px 0; }}
            """

        def _save(self) -> None:
            self.config.save()
            QMessageBox.information(self, "无忧28", "UI 配置已保存。")

        def _export(self) -> None:
            path, _ = QFileDialog.getSaveFileName(self, "导出 UI 方案", "wuyou28_theme.json", "JSON (*.json)")
            if path:
                self.config.export_bundle(path)

        def _import(self) -> None:
            path, _ = QFileDialog.getOpenFileName(self, "导入 UI 方案", "", "JSON (*.json)")
            if not path:
                return
            try:
                self.config.import_bundle(path)
                self._apply_ui()
                QMessageBox.information(self, "无忧28", "UI 配置已导入。")
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                QMessageBox.warning(self, "导入失败", f"配置无效，已保留当前界面。\n{exc}")

        def _reset(self) -> None:
            answer = QMessageBox.question(self, "恢复默认界面", "只重置 UI 配置，不修改数据或算法。继续吗？")
            if answer == QMessageBox.StandardButton.Yes:
                self.config.reset()
                self.config.save()
                self._apply_ui()


else:
    MainWindow = None


def main() -> int:
    if not QT_AVAILABLE:
        print("PySide6 is required to launch the desktop UI.", file=sys.stderr)
        return 2
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
