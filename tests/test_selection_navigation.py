"""Canvas selections reveal matching Python without becoming source edits."""
from __future__ import annotations

import ast
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QCoreApplication, QEvent, QPointF, QSettings, Qt
from PyQt6.QtGui import QMouseEvent, QTextCursor
from PyQt6.QtTest import QSignalSpy, QTest
from PyQt6.QtWidgets import QApplication, QMessageBox

from tkstudio.app import MainWindow
from tkstudio.codegen import generate_document
from tkstudio.model import create_widget, default_document


class SelectionNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="tkstudio-selection-")
        self.base = Path(self.temporary.name)
        document = default_document()
        action = create_widget(document, "ttk.Button", x=560, y=450)
        action.name = "senza_azione"
        action.properties["text"] = "Nuova azione"
        self.original_source = generate_document(document)
        (self.base / "app.py").write_text(self.original_source, encoding="utf-8")
        metadata = document.to_dict()
        metadata["python_file"] = "app.py"
        self.project = self.base / "progetto.tkui"
        self.project.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
        self.settings = QSettings(str(self.base / "settings.ini"), QSettings.Format.IniFormat)
        self.patches = [
            patch("tkstudio.app.QSettings", return_value=self.settings),
            patch.object(MainWindow, "_recovery_path", return_value=self.base / "recovery.json"),
            patch("tkstudio.app.QMessageBox.question", return_value=QMessageBox.StandardButton.Discard),
            patch("tkstudio.app.QMessageBox.warning", return_value=QMessageBox.StandardButton.Ok),
        ]
        for item in self.patches:
            item.start()
        self.window = MainWindow(self.project, restore_session=False)
        self.window.recovery_timer.stop()
        self.window.resize(1560, 970)
        self.window.show()
        self.window.set_view("design")
        QTest.qWait(140)
        self.window.designer.fit()
        self.app.processEvents()

    def tearDown(self):
        self.window.sync_timer.stop()
        self.window.recovery_timer.stop()
        with patch.object(self.window, "_allow_switch", return_value=True):
            self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.settings.sync()
        for item in reversed(self.patches):
            item.stop()
        self.temporary.cleanup()

    def node(self, name):
        return next(node for node in self.window.doc.widgets if node.name == name)

    def lines(self, name):
        constructor = placement = None
        for node in ast.walk(ast.parse(self.window.main_editor.source())):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if (isinstance(target, ast.Attribute) and target.attr == name
                            and isinstance(target.value, ast.Name) and target.value.id == "self"):
                        constructor = node.lineno
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "place":
                target = node.func.value
                if (isinstance(target, ast.Attribute) and target.attr == name
                        and isinstance(target.value, ast.Name) and target.value.id == "self"):
                    placement = node.lineno
        self.assertIsNotNone(constructor)
        self.assertIsNotNone(placement)
        return constructor, placement

    def point(self, name, position=None):
        node = self.node(name)
        item = self.window.designer.view.items_by_id[node.id]
        local = QPointF(*position) if position else QPointF(node.width / 2, node.height / 2)
        return self.window.designer.view.mapFromScene(item.mapToScene(local))

    def click(self, name, position=None):
        self.window.designer.view.setFocus()
        QTest.mouseClick(self.window.designer.view.viewport(), Qt.MouseButton.LeftButton, pos=self.point(name, position))
        QTest.qWait(QApplication.doubleClickInterval() + 110)

    def assert_points_to(self, name):
        constructor, placement = self.lines(name)
        editor = self.window.main_editor.editor
        self.assertEqual(editor.textCursor().blockNumber() + 1, constructor)
        highlighted = set()
        for selection in editor.extraSelections():
            first = editor.document().findBlock(selection.cursor.selectionStart()).blockNumber() + 1
            last = editor.document().findBlock(selection.cursor.selectionEnd()).blockNumber() + 1
            highlighted.update(range(first, last + 1))
        self.assertIn(constructor, highlighted)
        self.assertIn(placement, highlighted)

    def test_single_click_label_reveals_its_constructor_and_placement(self):
        self.click("titolo")
        self.assertEqual(self.window.view_mode, "split")
        self.assertEqual(self.window._selected_id, self.node("titolo").id)
        self.assert_points_to("titolo")
        self.assertFalse(self.window.main_editor.editor.hasFocus())

    def test_nested_entry_and_container_point_to_their_own_python(self):
        self.click("nome")
        self.assert_points_to("nome")
        self.window.set_view("design")
        QTest.qWait(80)
        group = self.node("profilo")
        self.click("profilo", (group.width - 20, group.height - 20))
        self.assert_points_to("profilo")

    def test_selection_does_not_edit_source_model_or_history(self):
        source = self.window.main_editor.source()
        document = copy.deepcopy(self.window.doc.to_dict())
        history = copy.deepcopy(self.window._history)
        activated = QSignalSpy(self.window.designer.widget_activated)
        self.click("titolo")
        self.click("nome")
        self.assertEqual(self.window.main_editor.source(), source)
        self.assertEqual(self.window.doc.to_dict(), document)
        self.assertEqual(self.window._history, history)
        self.assertEqual(len(activated), 0)
        self.assertFalse(self.window._main_dirty())

    def test_single_click_button_does_not_create_a_callback(self):
        before = self.window.main_editor.source()
        self.assertEqual(self.node("senza_azione").properties["command"], "")
        self.click("senza_azione")
        self.assert_points_to("senza_azione")
        self.assertEqual(self.window.main_editor.source(), before)
        self.assertEqual(self.node("senza_azione").properties["command"], "")
        self.assertNotIn("def on_senza_azione(", self.window.main_editor.source())

    def test_clicking_already_selected_widget_repoints_after_editor_navigation(self):
        self.click("titolo")
        self.window.main_editor.go_to_line(8)
        self.assertEqual(self.window.main_editor.editor.textCursor().blockNumber() + 1, 8)
        self.click("titolo")
        self.assert_points_to("titolo")
        self.assertFalse(self.window.main_editor.editor.hasFocus())

    def test_canvas_selection_activates_main_source_tab_without_taking_focus(self):
        other_file = self.base / "utilita.py"
        other_file.write_text("print('Un altro file del progetto')\n", encoding="utf-8")
        self.window.open_file(str(other_file))
        self.assertIsNot(self.window.editors.currentWidget(), self.window.main_editor)
        self.window.set_view("design")
        QTest.qWait(80)
        self.click("titolo")
        self.assertIs(self.window.editors.currentWidget(), self.window.main_editor)
        self.assert_points_to("titolo")
        self.assertFalse(self.window.main_editor.editor.hasFocus())

    def test_background_code_sync_preserves_cursor_and_selection(self):
        self.click("titolo")
        editor = self.window.main_editor.editor
        callback = next(node for node in ast.walk(ast.parse(self.window.main_editor.source()))
                        if isinstance(node, ast.FunctionDef) and node.name == "on_saluta")
        block = editor.document().findBlockByNumber(callback.body[0].lineno - 1)
        cursor = QTextCursor(block)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        cursor.insertText("  # una nota personale")
        editor.setTextCursor(cursor)
        self.window.sync_timer.stop()
        before = (editor.textCursor().position(), editor.textCursor().anchor(), editor.verticalScrollBar().value())
        self.assertTrue(self.window.sync_from_code())
        QTest.qWait(130)
        after = (editor.textCursor().position(), editor.textCursor().anchor(), editor.verticalScrollBar().value())
        self.assertEqual(after, before)
        self.assertEqual(self.window._selected_id, self.node("titolo").id)

    def test_double_click_button_still_opens_callback_body(self):
        before = self.window.main_editor.source()
        viewport = self.window.designer.view.viewport()
        point = self.point("saluta")
        # QGraphicsScene treats a double-click without a preceding click as a
        # press on an unselected item. Model the real two-click sequence.
        QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=point)
        QTest.qWait(20)
        QTest.mouseDClick(viewport, Qt.MouseButton.LeftButton, pos=point)
        QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=point)
        QTest.qWait(130)
        callback = next(node for node in ast.walk(ast.parse(before))
                        if isinstance(node, ast.FunctionDef) and node.name == "on_saluta")
        self.assertEqual(self.window.main_editor.editor.textCursor().blockNumber() + 1, callback.body[0].lineno)
        self.assertEqual(self.window.main_editor.source(), before)
        self.assertEqual(self.window.view_mode, "split")

    def test_revealing_code_waits_until_drag_is_released(self):
        view = self.window.designer.view
        node = self.node("titolo")
        start = self.point("titolo")
        original = (node.x, node.y)
        width = self.window.designer.width()
        QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
        QTest.qWait(70)
        self.assertEqual(self.window.view_mode, "design")
        self.assertEqual(self.window.designer.width(), width)
        shift = view.mapFromScene(QPointF(48, 16)) - view.mapFromScene(QPointF(0, 0))
        target = start + shift
        move = QMouseEvent(QEvent.Type.MouseMove, QPointF(target), QPointF(view.viewport().mapToGlobal(target)),
                           Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(view.viewport(), move)
        QTest.qWait(30)
        self.assertEqual(self.window.view_mode, "design")
        QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=target)
        QTest.qWait(QApplication.doubleClickInterval() + 110)
        moved = self.node("titolo")
        self.assertLessEqual(abs(moved.x - original[0] - 48), 8)
        self.assertLessEqual(abs(moved.y - original[1] - 16), 8)
        self.assertEqual((moved.x % 8, moved.y % 8), (0, 0))
        self.assertEqual(self.window.view_mode, "split")
        self.assert_points_to("titolo")


if __name__ == "__main__":
    unittest.main()
