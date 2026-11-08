"""Interaction checks for the graphics designer, without launching Tk code."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from PyQt6.QtCore import QEvent, QMimeData, QPointF, Qt
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QFontDatabase, QMouseEvent
from PyQt6.QtTest import QSignalSpy, QTest
from PyQt6.QtWidgets import QApplication

from tkstudio.designer import DesignerPanel, WIDGET_MIME
from tkstudio.model import WIDGET_SPECS, new_document, validate_document


class DesignerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        # The Windows offscreen Qt platform does not enumerate system fonts.
        font = r"C:\Windows\Fonts\segoeui.ttf"
        if os.path.exists(font) and not QFontDatabase.families():
            QFontDatabase.addApplicationFont(font)

    def setUp(self):
        self.panel = DesignerPanel()
        self.panel.resize(980, 740)
        self.panel.set_document(new_document())
        self.panel.show()
        self.app.processEvents()
        self.panel.actual_size()
        self.app.processEvents()

    def tearDown(self):
        self.panel.close()
        self.panel.deleteLater()
        self.app.processEvents()

    def test_add_snap_and_canvas_bounds(self):
        changes = QSignalSpy(self.panel.document_changed)
        entry = self.panel.add_widget("ttk.Entry", (29, 35))
        self.assertEqual((entry.x, entry.y), (32, 32))
        self.assertEqual(len(changes), 1)
        edge = self.panel.add_widget("ttk.Button", (9000, 9000))
        self.assertLessEqual(edge.x + edge.width, self.panel.document.width)
        self.assertLessEqual(edge.y + edge.height, self.panel.document.height)
        validate_document(self.panel.document)

    def test_duplicate_container_preserves_children(self):
        frame = self.panel.add_widget("ttk.Frame", (40, 40))
        button = self.panel.add_widget("ttk.Button", (24, 24), frame.id)
        self.panel.select_widget(frame.id)
        self.panel.duplicate_selected()
        self.assertEqual(len(self.panel.document.widgets), 4)
        names = [node.name for node in self.panel.document.widgets]
        self.assertEqual(len(names), len(set(names)))
        clone = self.panel.document.find(self.panel.selected_ids()[0])
        self.assertNotEqual(clone.id, frame.id)
        child = next(node for node in self.panel.document.widgets if node.parent == clone.id)
        self.assertEqual(child.properties, button.properties)
        self.assertEqual((child.x, child.y), (button.x, button.y))
        validate_document(self.panel.document)

    def test_delete_cascades_and_refresh_is_not_an_edit(self):
        frame = self.panel.add_widget("ttk.Frame", (40, 40))
        self.panel.add_widget("ttk.Button", (24, 24), frame.id)
        changes = QSignalSpy(self.panel.document_changed)
        self.panel.refresh(frame.id)
        self.assertEqual(len(changes), 0)
        self.panel.delete_selected()
        self.assertEqual(self.panel.document.widgets, [])
        self.assertEqual(len(changes), 1)

    def test_ancestor_and_grandchild_selection_is_not_duplicated_twice(self):
        outer = self.panel.add_widget("ttk.Frame", (40, 40))
        inner = self.panel.add_widget("ttk.Frame", (0, 0), outer.id)
        child = self.panel.add_widget("ttk.Button", (24, 24), inner.id)
        self.panel.view.scene().clearSelection()
        self.panel.view.items_by_id[outer.id].setSelected(True)
        self.panel.view.items_by_id[child.id].setSelected(True)
        self.panel.duplicate_selected()
        self.assertEqual(len(self.panel.document.widgets), 6)
        validate_document(self.panel.document)

    def test_keyboard_moves_in_pixels_and_emits_once(self):
        button = self.panel.add_widget("ttk.Button", (40, 40))
        changes = QSignalSpy(self.panel.document_changed)
        self.panel.view.setFocus()
        QTest.keyClick(self.panel.view, Qt.Key.Key_Right)
        self.assertEqual(button.x, 41)
        QTest.keyClick(self.panel.view, Qt.Key.Key_Down, Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(button.y, 50)
        self.assertEqual(len(changes), 2)

    def test_drag_resizes_from_corner(self):
        button = self.panel.add_widget("ttk.Button", (40, 40))
        self.app.processEvents()
        view = self.panel.view
        item = view.items_by_id[button.id]
        origin = view.mapFromScene(item.mapToScene(QPointF(button.width, button.height)))
        changes = QSignalSpy(self.panel.document_changed)
        QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=origin)
        target = origin + view.mapFromScene(QPointF(32, 16)) - view.mapFromScene(QPointF(0, 0))
        event = QMouseEvent(QEvent.Type.MouseMove, QPointF(target),
                            QPointF(view.viewport().mapToGlobal(target)),
                            Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
                            Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(view.viewport(), event)
        QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=target)
        self.app.processEvents()
        self.assertEqual((button.width, button.height), (162, 52))
        self.assertEqual(len(changes), 1)

    def test_drop_into_container_uses_relative_coordinates(self):
        frame = self.panel.add_widget("ttk.Frame", (80, 80))
        view = self.panel.view
        point = view.mapFromScene(QPointF(120, 120))
        mime = QMimeData()
        mime.setData(WIDGET_MIME, b"ttk.Label")
        enter = QDragEnterEvent(point, Qt.DropAction.CopyAction, mime,
                                Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        view.dragEnterEvent(enter)
        self.assertTrue(enter.isAccepted())
        event = QDropEvent(QPointF(point), Qt.DropAction.CopyAction, mime,
                           Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        view.dropEvent(event)
        self.assertTrue(event.isAccepted())
        label = self.panel.document.widgets[-1]
        self.assertEqual(label.parent, frame.id)
        self.assertEqual((label.x, label.y), (40, 40))

    def test_locked_designer_does_not_change_document(self):
        button = self.panel.add_widget("ttk.Button", (40, 40))
        before = self.panel.document.to_dict()
        self.panel.set_editable(False)
        self.panel.delete_selected()
        self.panel.duplicate_selected()
        self.panel.add_widget("ttk.Label")
        QTest.keyClick(self.panel.view, Qt.Key.Key_Right)
        self.assertEqual(self.panel.document.to_dict(), before)
        self.assertEqual(self.panel.selected_ids(), [button.id])

    def test_every_supported_widget_renders(self):
        for index, kind in enumerate(WIDGET_SPECS):
            node = self.panel.add_widget(kind, ((index % 3) * 240, (index % 5) * 80))
            self.assertIsNotNone(node)
        self.app.processEvents()
        image = self.panel.grab()
        self.assertFalse(image.isNull())
        validate_document(self.panel.document)


if __name__ == "__main__":
    unittest.main()
