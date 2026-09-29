"""Formal-window adapters for the existing Phase 1/2 editor and managers."""
from __future__ import annotations

import copy
import re

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QFontComboBox, QFormLayout, QFrame, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea,
    QSpinBox, QTableWidget, QVBoxLayout, QWidget,
)

from .ui_diy import EditableComponent, LayoutEditorWidget, LayoutEditModel, UIConfigManager
from .theme import APP_STYLE


class HomeComponent(EditableComponent):
    """Keep the original drag/resize handlers, hosting the real home widget."""
    def __init__(self, editor, component_id, title, content):
        super().__init__(editor, component_id, title)
        self.body.hide()
        self.body.deleteLater()
        self.body = content
        content.setParent(self)
        content.show()
        self.setMinimumSize(0, 0)
        self.header.setAccessibleName(f"拖动组件 {title}")
        for name, handle in self.handles.items():
            handle.setAccessibleName(f"调整大小 {title} {name}")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.arrange_content()

    def arrange_content(self):
        editing = self.editor.edit_mode
        self.header.setVisible(editing)
        top = 30 if editing else 0
        self.body.setGeometry(4, top + 4, max(0, self.width()-8), max(0, self.height()-top-8))
        self.header.raise_()
        for handle in self.handles.values():
            handle.raise_()


class HomeLayoutCanvas(LayoutEditorWidget):
    changed = Signal()

    def __init__(self, model, components, parent=None):
        super().__init__(model, parent)
        titles = {"current": "当前开奖", "next": "下一期开奖", "vip": "VIP100 / 分析摘要",
                  "history": "最近开奖", "status": "数据状态"}
        for component_id, old in list(self.widgets.items()):
            old.hide()
            old.deleteLater()
            self.widgets[component_id] = HomeComponent(self, component_id, titles[component_id], components[component_id])
        self.refresh_from_model()

    def refresh_from_model(self):
        super().refresh_from_model()
        geometry = self.model.geometry.values()
        self.setMinimumSize(max(1200, max(g['x']+g['width']+24 for g in geometry)),
                            max(736, max(g['y']+g['height']+24 for g in geometry)))
        for cid, widget in self.widgets.items():
            widget.setVisible(self.model.components.data['visibility'].get(cid, True))
            if isinstance(widget, HomeComponent):
                widget.arrange_content()
        self.changed.emit()

    def set_edit_mode(self, enabled):
        self._active = None
        self.clear_guides()
        if not enabled:
            self.selected = None
        super().set_edit_mode(enabled)

    def select_component(self, component):
        if self.edit_mode:
            super().select_component(component)

    def show_guides(self, component_id):
        super().show_guides(component_id)
        for line in self._guides:
            line.setAttribute(Qt.WA_TransparentForMouseEvents)


class InterfaceSettingsPage(QWidget):
    edit_requested = Signal()
    theme_changed = Signal()

    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        self.config = config or UIConfigManager()
        self.model = LayoutEditModel(self.config.layout, self.config.components)
        self.editor = None
        self.fields = {}
        self.geometry_fields = {}
        self.visibility_checks = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        title = QLabel("设置  /  界面设置")
        title.setObjectName("PageTitle")
        root.addWidget(title)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        body = QVBoxLayout(content)
        appearance = QGroupBox("外观")
        form = QFormLayout(appearance)
        for section, key, label in (
            ('colors', 'primary', '主题颜色'), ('colors', 'app_background', '背景颜色'),
            ('colors', 'card_background', '卡片背景颜色'), ('colors', 'text', '文字颜色'),
            ('draw', 'fill', '开奖号码背景颜色'), ('draw', 'text', '开奖号码颜色'),
        ):
            field = QLineEdit()
            field.setAccessibleName(label)
            field.setPlaceholderText('#RRGGBB')
            field.textChanged.connect(lambda value, s=section, k=key: self._color(s, k, value))
            self.fields[(section, key)] = field
            form.addRow(label, field)
        font = QFontComboBox()
        font.currentFontChanged.connect(lambda value: self._value('font', 'family', value.family()))
        self.fields[('font', 'family')] = font
        form.addRow('字体', font)
        for section, key, label, low, high in (
            ('font', 'base_size', '字号', 14, 24), ('font', 'title_size', '标题字号', 18, 32),
            ('sizes', 'nav_width', '导航宽度', 168, 320),
            ('sizes', 'table_row_height', '表格行高', 24, 64),
            ('sizes', 'draw_number_size', '开奖号码大小', 44, 120),
        ):
            field = QSpinBox()
            field.setRange(low, high)
            field.setAccessibleName(label)
            field.valueChanged.connect(lambda value, s=section, k=key: self._value(s, k, value))
            self.fields[(section, key)] = field
            form.addRow(label, field)
        body.addWidget(appearance)
        self._action_group(body, '布局', (
            ('编辑界面', self.enter_edit_mode), ('保存布局', self.save_layout),
            ('恢复默认布局', self.restore_layout)))
        self._action_group(body, '配置', (
            ('导入界面配置', self.import_config), ('导出界面配置', self.export_config),
            ('恢复默认界面', self.reset_config)))
        self.notice = QLabel('外观即时生效并保存；编辑界面后可调整首页组件。')
        self.notice.setWordWrap(True)
        body.addWidget(self.notice)
        body.addStretch()
        scroll.setWidget(content)
        root.addWidget(scroll)
        self.sync_fields()

    @staticmethod
    def _action_group(layout, title, actions):
        group = QGroupBox(title)
        row = QHBoxLayout(group)
        for label, callback in actions:
            button = QPushButton(label)
            if label == '编辑界面':
                button.setShortcut('Alt+E')
                button.setToolTip('进入首页编辑模式 (Alt+E)')
            elif label == '保存布局':
                button.setShortcut('Ctrl+S')
                button.setToolTip('保存布局 (Ctrl+S)')
            elif label == '恢复默认布局':
                button.setShortcut('Alt+R')
                button.setToolTip('恢复默认布局 (Alt+R)')
            button.clicked.connect(callback)
            row.addWidget(button)
        row.addStretch()
        layout.addWidget(group)

    def bind_home(self, home):
        if self.editor is not None:
            return self.editor
        self.home = home
        self.editor = home.attach_layout_editor(self.model)
        self.editor.on_selected = self._select_component
        home.layout_body.addWidget(self._property_panel())
        toolbar = home.edit_toolbar.layout()
        for text, callback in (('撤销 Ctrl+Z', self.undo), ('重做 Ctrl+Y', self.redo),
                               ('保存布局', self.save_layout), ('恢复默认布局', self.restore_layout),
                               ('退出编辑', self.exit_edit_mode)):
            button = QPushButton(text)
            if text == '保存布局':
                button.setShortcut('Ctrl+S')
                button.setToolTip('保存布局 (Ctrl+S)')
            elif text == '恢复默认布局':
                button.setShortcut('Alt+R')
                button.setToolTip('恢复默认布局 (Alt+R)')
            button.clicked.connect(callback)
            toolbar.addWidget(button)
        self.editor.changed.connect(self._sync_properties)
        for key, callback in (('Ctrl+Z', self.undo), ('Ctrl+Y', self.redo)):
            shortcut = QShortcut(QKeySequence(key), home)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(callback)
        for index, (cid, component) in enumerate(self.editor.widgets.items(), 1):
            shortcut = QShortcut(QKeySequence(f'Alt+{index}'), home)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(lambda c=component: self.editor.select_component(c))
            component.header.setToolTip(f'选择组件 Alt+{index}；拖动标题移动，边框手柄缩放')
        return self.editor

    def set_home(self, home):
        """Remember the home page without attaching the optional editor."""
        self.home = home

    def _property_panel(self):
        panel = QGroupBox('属性面板')
        self.property_panel = panel
        panel.setFixedWidth(238)
        root = QVBoxLayout(panel)
        self.property_hint = QLabel('选择组件标题以拖动；边框手柄调整大小。')
        self.property_hint.setWordWrap(True)
        root.addWidget(self.property_hint)
        form = QFormLayout()
        for key, label in (('x', '横坐标'), ('y', '纵坐标'), ('width', '宽度'), ('height', '高度')):
            field = QSpinBox()
            field.setRange(0, 4000 if key != 'height' else 2400)
            field.setSingleStep(8)
            field.setKeyboardTracking(False)
            field.installEventFilter(self)
            field.lineEdit().installEventFilter(self)
            field.setAccessibleName(f'组件{label}')
            field.valueChanged.connect(lambda value, k=key: self._geometry(k, value))
            self.geometry_fields[key] = field
            form.addRow(label, field)
        root.addLayout(form)
        root.addWidget(QLabel('组件显示 / 隐藏'))
        for cid, label in (('current', '当前开奖'), ('next', '下一期开奖'), ('vip', 'VIP100 / 分析摘要'),
                           ('history', '最近开奖'), ('status', '数据状态')):
            check = QCheckBox(label)
            check.toggled.connect(lambda value, c=cid: self._visibility(c, value))
            self.visibility_checks[cid] = check
            root.addWidget(check)
        root.addStretch()
        panel.hide()
        self._sync_properties()
        return panel

    def eventFilter(self, watched, event):
        if (event.type() in (QEvent.ShortcutOverride, QEvent.KeyPress)
                and event.modifiers() & Qt.ControlModifier
                and event.key() in (Qt.Key_Z, Qt.Key_Y) and self.model.edit_mode):
            event.accept()
            if event.type() == QEvent.KeyPress:
                (self.undo if event.key() == Qt.Key_Z else self.redo)()
            return True
        return super().eventFilter(watched, event)

    def enter_edit_mode(self):
        if self.editor is None:
            if not hasattr(self, 'home'):
                return
            self.bind_home(self.home)
        self.editor.set_edit_mode(True)
        self.home.edit_toolbar.show()
        self.property_panel.show()
        self.edit_requested.emit()
        self.home.setFocus()

    def exit_edit_mode(self):
        self.editor.set_edit_mode(False)
        self.home.edit_toolbar.hide()
        self.property_panel.hide()

    def _select_component(self, _cid):
        self._sync_properties()

    def _sync_properties(self):
        cid = self.model.selected_id
        if not hasattr(self, 'property_hint'):
            return
        component_names = {
            'current': '当前开奖',
            'next': '下一期开奖',
            'vip': 'VIP100 / 分析摘要',
            'history': '最近开奖',
            'status': '数据状态',
        }
        name = component_names.get(cid, cid)
        self.property_hint.setText(
            f'当前组件：{name} · 8 像素网格吸附'
            if cid
            else '选择组件标题以拖动；边框手柄调整大小。'
        )
        for key, field in self.geometry_fields.items():
            field.blockSignals(True)
            field.setEnabled(bool(cid) and self.model.edit_mode)
            if cid:
                field.setValue(self.model.geometry[cid][key])
            field.blockSignals(False)
        for key, field in self.visibility_checks.items():
            field.blockSignals(True)
            field.setChecked(self.config.components.data['visibility'].get(key, True))
            field.blockSignals(False)

    def _geometry(self, key, value):
        if self.model.selected_id and self.model.set_geometry(self.model.selected_id, **{key: round(value/8)*8}):
            self.editor.refresh_from_model()

    def _visibility(self, cid, value):
        if self.model.set_visibility(cid, value):
            self.editor.refresh_from_model()

    def undo(self):
        if self.model.edit_mode and self.model.undo():
            self.editor.refresh_from_model()

    def redo(self):
        if self.model.edit_mode and self.model.redo():
            self.editor.refresh_from_model()

    def save_layout(self):
        self.model.save()
        self.config.theme.save()
        self.notice.setText('布局已保存，下次启动自动加载。')
        self.window().statusBar().showMessage('布局已保存', 5000)

    def restore_layout(self):
        styles = copy.deepcopy(self.config.components.data['styles'])
        self.model.reset()
        self.config.components.data['styles'] = styles
        self.editor.refresh_from_model()
        self.save_layout()
        self.theme_changed.emit()

    def _value(self, section, key, value):
        self.config.theme.data[section][key] = value
        if key == 'draw_number_size':
            self.config.components.data['styles']['draw_numbers']['size'] = value
            self.config.components.save()
        self.config.theme.save()
        self.theme_changed.emit()

    def _color(self, section, key, value):
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
            return
        if section == 'draw':
            self.config.components.data['styles']['draw_numbers'][key] = value.upper()
            self.config.components.save()
            self.theme_changed.emit()
        else:
            self._value(section, key, value.upper())

    def sync_fields(self):
        for (section, key), field in self.fields.items():
            data = self.config.components.data['styles']['draw_numbers'] if section == 'draw' else self.config.theme.data[section]
            field.blockSignals(True)
            if isinstance(field, QFontComboBox):
                field.setCurrentFont(QFont(data[key]))
            elif isinstance(field, QSpinBox):
                field.setValue(data[key])
            else:
                field.setText(data[key])
            field.blockSignals(False)

    def export_config(self):
        path, _ = QFileDialog.getSaveFileName(self, '导出界面配置', 'wuyou28_ui.json', 'JSON (*.json)')
        if path:
            self.config.export_bundle(path)

    def load_bundle(self, path):
        # Roll back all managers together if a malformed nested section fails validation.
        before = [copy.deepcopy(m.data) for m in (self.config.theme, self.config.layout, self.config.components)]
        try:
            self.config.import_bundle(path)
        except Exception:
            for manager, data in zip((self.config.theme, self.config.layout, self.config.components), before):
                manager.data = data
            raise
        self.model._undo.clear()
        self.model._redo.clear()
        self.sync_fields()
        self.editor.refresh_from_model()
        self.theme_changed.emit()

    def import_config(self):
        path, _ = QFileDialog.getOpenFileName(self, '导入界面配置', '', 'JSON (*.json)')
        if path:
            try:
                self.load_bundle(path)
            except (OSError, ValueError, TypeError, AttributeError) as exc:
                QMessageBox.warning(self, '导入失败', f'配置无效，已保留当前界面。\n{exc}')

    def reset_config(self):
        self.config.reset()
        self.config.save()
        self.model._undo.clear()
        self.model._redo.clear()
        self.sync_fields()
        self.editor.refresh_from_model()
        self.theme_changed.emit()


def apply_formal_theme(window, config):
    theme = config.theme.data
    colors, font = theme['colors'], theme['font']
    family = re.sub(r'[";{}\n\r]', '', font['family'])
    draw = config.components.data['styles']['draw_numbers']
    size = theme['sizes']['draw_number_size']
    style = APP_STYLE + f'''
    QWidget {{ background: {colors['app_background']}; color: {colors['text']}; font-family: "{family}"; font-size: {font['base_size']}px; }}
    QFrame#Sidebar, QGroupBox, QFrame#DrawBar, QFrame#SummaryPanel, QFrame#WorkPanel, QFrame#EngineStatusLine {{ background: {colors['card_background']}; border-color: {colors['border']}; }}
    QLabel {{ background: transparent; }}
    QLabel#PageTitle {{ font-size: {font['title_size']}px; }}
    QPushButton {{ background: {colors['primary']}; color: white; }}
    QPushButton#NavButton:checked {{ color: {colors['primary']}; }}
    QTableWidget {{ background: {colors['card_background']}; font-size: {font['table_size']}px; }}
    QLabel#DrawBall {{ background: {draw['fill']}; color: {draw['text']}; border-radius: {size//2}px; font-size: {max(16,size//2)}px; }}
    QFrame#editComponent {{ background: {colors['card_background']}; border: 1px solid {colors['border']}; }}
    QFrame#editComponent[selected="true"] {{ border: 2px solid {colors['primary']}; }}
    QLabel#componentHeader {{ background: {colors['primary']}; color: white; padding-left: 12px; }}
    QFrame#resizeHandle {{ background: {colors['primary']}; border: 1px solid white; }}
    QFrame#alignmentGuide {{ background: #E95BA4; }}
    '''
    window.setStyleSheet(style)
    window.sidebar.setFixedWidth(theme['sizes']['nav_width'])
    for table in window.findChildren(QTableWidget):
        table.verticalHeader().setMinimumSectionSize(16)
        table.verticalHeader().setDefaultSectionSize(theme['sizes']['table_row_height'])
    for ball in window.home_page.number_blocks:
        ball.setFixedSize(size, size)
