"""Real Qt controls on the formal MainWindow; all writes use a temporary directory."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton
from app.database import Database
from app.ui.main_window import MainWindow
from app.ui.ui_diy import UIConfigManager, DEFAULT_LAYOUT


class FormalDIYTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = UIConfigManager(self.root/'ui')
        self.start_yu28 = patch('app.yu28_controller.YU28Controller.start').start()
        self.window = MainWindow(Database(self.root/'isolated.db'), ui_only=True, ui_config=self.config)
        self.window.show()
        self.window.activateWindow()
        self.app.processEvents()
        self.page = self.window.interface_settings_page
        self.home = self.window.home_page
        self.editor = self.home.layout_canvas

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        patch.stopall()
        self.temp.cleanup()

    def click(self, parent, text):
        button = next(b for b in parent.findChildren(QPushButton) if b.text() == text)
        QTest.mouseClick(button, Qt.LeftButton)
        self.app.processEvents()

    def enter(self):
        self.click(self.window, '⚙   设置')
        self.click(self.window.settings_page, '打开界面设置 / 编辑界面')
        self.click(self.page, '编辑界面')
        self.assertIs(self.window.stack.currentWidget(), self.home)
        self.assertTrue(self.page.model.edit_mode)

    def drag(self, widget, delta):
        start = QPoint(widget.width()//2, widget.height()//2)
        QTest.mousePress(widget, Qt.LeftButton, pos=start)
        QTest.mouseMove(widget, start+delta, delay=30)
        QTest.mouseRelease(widget, Qt.LeftButton, pos=start+delta)
        self.app.processEvents()

    def test_settings_entry_and_navigation(self):
        self.click(self.window, '⚙   设置')
        self.assertIs(self.window.stack.currentWidget(), self.window.settings_page)
        self.click(self.window.settings_page, '打开界面设置 / 编辑界面')
        self.assertIs(self.window.stack.currentWidget(), self.page)
        labels={b.text() for b in self.page.findChildren(QPushButton)}
        self.assertTrue({'编辑界面','保存布局','恢复默认布局','导入UI配置','导出UI配置','恢复默认UI'} <= labels)

    def test_edit_routes_to_real_home(self):
        self.enter()
        self.assertTrue(self.home.edit_toolbar.isVisible())
        self.assertTrue(self.page.property_panel.isVisible())
        self.assertIs(self.home.draw_issue.parentWidget(), self.editor.widgets['current'].body)
        self.assertTrue(self.editor.widgets['history'].isAncestorOf(self.home.recent_table))
        self.assertFalse(any('可视化组件' in l.text() for l in self.home.findChildren(QLabel) if l.isVisible()))

    def test_drag_and_grid_snap(self):
        self.enter()
        self.drag(self.editor.widgets['current'].header, QPoint(35,43))
        g=self.page.model.geometry['current']
        self.assertEqual((g['x'], g['y']), (56,64))
        self.assertEqual(self.editor.widgets['current'].x(), g['x'])
        self.assertEqual(self.page.geometry_fields['x'].value(),g['x'])

    def test_resize_handle(self):
        self.enter()
        w=self.editor.widgets['current']
        self.editor.select_component(w)
        self.drag(w.handles['se'], QPoint(32,40))
        g=self.page.model.geometry['current']
        self.assertEqual((g['width'],g['height']), (576,304))
        self.assertEqual(w.size().width(),g['width'])
        self.assertEqual(w.body.width(),w.width()-8)

    def test_property_panel_edits_real_geometry(self):
        self.enter()
        self.editor.select_component(self.editor.widgets['current'])
        self.page.geometry_fields['x'].setValue(136)
        self.assertEqual(self.editor.widgets['current'].x(),136)

    def test_visibility_and_undo_sync(self):
        self.enter()
        self.page.visibility_checks['vip'].setChecked(False)
        self.assertFalse(self.editor.widgets['vip'].isVisible())
        self.page.undo()
        self.assertTrue(self.editor.widgets['vip'].isVisible())
        self.assertTrue(self.page.visibility_checks['vip'].isChecked())
        self.page.redo()
        self.assertFalse(self.editor.widgets['vip'].isVisible())

    def test_keyboard_undo_redo(self):
        self.enter()
        before=copy.deepcopy(self.page.model.geometry['current'])
        self.drag(self.editor.widgets['current'].header,QPoint(32,40))
        after=copy.deepcopy(self.page.model.geometry['current'])
        self.home.setFocus()
        QTest.keyClick(self.home,Qt.Key_Z,Qt.ControlModifier)
        self.app.processEvents()
        self.assertEqual(self.page.model.geometry['current'],before)
        QTest.keyClick(self.home,Qt.Key_Y,Qt.ControlModifier)
        self.app.processEvents()
        self.assertEqual(self.page.model.geometry['current'],after)

    def test_normal_mode_locked_and_content_visible(self):
        self.enter()
        self.page.exit_edit_mode()
        before=copy.deepcopy(self.page.model.geometry)
        self.assertFalse(self.editor.widgets['current'].header.isVisible())
        self.assertTrue(self.home.draw_issue.isVisible())
        self.editor.begin_drag(self.editor.widgets['current'],QPoint(0,0))
        self.editor.drag_move(QPoint(80,80))
        self.assertEqual(self.page.model.geometry,before)
        self.assertFalse(any(h.isVisible() for w in self.editor.widgets.values() for h in w.handles.values()))

    def test_alignment_guides_visible(self):
        self.enter()
        self.page.model.move('current',24,24,(1600,900))
        self.editor.show_guides('current')
        self.assertTrue(self.editor._guides)
        self.assertTrue(all(g.isVisible() for g in self.editor._guides))
        self.editor.end_interaction()
        self.assertFalse(self.editor._guides)

    def test_save_and_restore_defaults(self):
        self.enter()
        self.page.fields[('draw','text')].setText('#FFEEDD')
        self.drag(self.editor.widgets['current'].header,QPoint(32,40))
        QTest.keyClick(self.home,Qt.Key_S,Qt.ControlModifier)
        QTest.qWait(150)
        saved=UIConfigManager(self.root/'ui')
        self.assertEqual(saved.layout.data,self.config.layout.data)
        QTest.keyClick(self.home,Qt.Key_R,Qt.AltModifier)
        QTest.qWait(150)
        self.assertEqual(self.config.components.data['styles']['draw_numbers']['text'],'#FFEEDD')
        self.assertEqual(self.page.model.geometry,DEFAULT_LAYOUT['home']['components'])
        self.assertEqual(UIConfigManager(self.root/'ui').layout.data,self.config.layout.data)

    def test_load_saved_geometry_in_new_window(self):
        self.enter()
        self.page.model.move('current',104,80,(1600,900))
        self.page.save_layout()
        reopened=MainWindow(Database(self.root/'new.db'),ui_only=True,ui_config=UIConfigManager(self.root/'ui'))
        try:
            self.assertEqual(reopened.home_page.layout_canvas.widgets['current'].x(),104)
            self.assertFalse(reopened.interface_settings_page.model.edit_mode)
        finally:
            reopened.close()
            reopened.deleteLater()

    def test_theme_applies_and_persists(self):
        self.page.fields[('colors','primary')].setText('#123456')
        self.page.fields[('sizes','nav_width')].setValue(280)
        self.page.fields[('sizes','table_row_height')].setValue(48)
        self.page.fields[('sizes','draw_number_size')].setValue(88)
        self.page.fields[('draw','text')].setText('#FFEEDD')
        self.assertEqual(self.window.sidebar.width(),280)
        self.assertEqual(self.home.recent_table.verticalHeader().defaultSectionSize(),48)
        self.assertEqual(self.home.number_blocks[0].width(),88)
        self.assertIn('#123456',self.window.styleSheet())
        self.assertIn('#FFEEDD',self.window.styleSheet())
        self.assertEqual(UIConfigManager(self.root/'ui').theme.data['colors']['primary'],'#123456')

    def test_import_export_updates_ui(self):
        bundle=self.root/'bundle.json'
        self.config.export_bundle(bundle)
        raw=json.loads(bundle.read_text(encoding='utf-8'))
        raw['theme']['sizes']['nav_width']=296
        raw['layout']['home']['components']['current']['x']=96
        raw['components']['visibility']['next']=False
        bundle.write_text(json.dumps(raw),encoding='utf-8')
        self.page.load_bundle(bundle)
        self.assertEqual(self.window.sidebar.width(),296)
        self.assertEqual(self.editor.widgets['current'].x(),96)
        self.assertTrue(self.editor.widgets['next'].isHidden())
        self.assertFalse(self.page.visibility_checks['next'].isChecked())

    def test_invalid_import_preserves_all_config(self):
        before=[copy.deepcopy(m.data) for m in (self.config.theme,self.config.layout,self.config.components)]
        bundle=self.root/'invalid.json'
        self.config.export_bundle(bundle)
        raw=json.loads(bundle.read_text(encoding='utf-8'))
        raw['theme']['sizes']['nav_width']=296
        raw['layout']['home']['components']=[]
        bundle.write_text(json.dumps(raw),encoding='utf-8')
        with self.assertRaises((ValueError,TypeError,AttributeError)):
            self.page.load_bundle(bundle)
        self.assertEqual(before,[m.data for m in (self.config.theme,self.config.layout,self.config.components)])

    def test_brand_and_services(self):
        self.assertIn('无忧28',self.window.windowTitle())
        texts=[l.text() for l in self.window.findChildren(QLabel) if l.isVisible()]
        self.assertNotIn('乐28',texts)
        self.assertNotIn('预测采集与分析',texts)
        self.start_yu28.assert_not_called()

    def test_leaving_home_locks_edit_mode(self):
        self.enter()
        self.click(self.window,'⚙   设置')
        self.assertFalse(self.page.model.edit_mode)

    def test_accessible_navigation_shortcuts(self):
        QTest.keyClick(self.window,Qt.Key_S,Qt.AltModifier)
        self.app.processEvents()
        self.assertIs(self.window.stack.currentWidget(),self.window.settings_page)
        QTest.keyClick(self.window,Qt.Key_U,Qt.AltModifier)
        QTest.qWait(150)
        self.assertIs(self.window.stack.currentWidget(),self.page)
        QTest.keyClick(self.window,Qt.Key_E,Qt.AltModifier)
        QTest.qWait(150)
        self.assertIs(self.window.stack.currentWidget(),self.home)
        self.assertTrue(self.page.model.edit_mode)
        QTest.keyClick(self.home,Qt.Key_1,Qt.AltModifier)
        self.app.processEvents()
        self.assertEqual(self.page.model.selected_id,'current')

    def test_property_typing_and_focused_undo_redo(self):
        self.enter()
        self.editor.select_component(self.editor.widgets['current'])
        field=self.page.geometry_fields['x']
        field.setFocus()
        QTest.keyClick(field,Qt.Key_A,Qt.ControlModifier)
        QTest.keyClicks(field,'136')
        QTest.keyClick(field,Qt.Key_Return)
        self.assertEqual(self.page.model.geometry['current']['x'],136)
        QTest.keyClick(field,Qt.Key_Z,Qt.ControlModifier)
        self.assertEqual(self.page.model.geometry['current']['x'],24)
        QTest.keyClick(field,Qt.Key_Y,Qt.ControlModifier)
        self.assertEqual(self.page.model.geometry['current']['x'],136)

if __name__=='__main__':
    unittest.main(verbosity=2)
