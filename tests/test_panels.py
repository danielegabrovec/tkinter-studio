"""Verify inspector, component search, and hierarchy interactions."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFontDatabase
from PyQt6.QtTest import QSignalSpy
from PyQt6.QtWidgets import QApplication

from tkstudio.model import create_widget, new_document
from tkstudio.panels import HierarchyPanel, PalettePanel, PropertyPanel


class PanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        font = r"C:\Windows\Fonts\segoeui.ttf"
        if os.path.exists(font) and not QFontDatabase.families():
            QFontDatabase.addApplicationFont(font)

    def setUp(self):
        self.widgets = []

    def panel(self, cls):
        panel = cls()
        self.widgets.append(panel)
        return panel

    def tearDown(self):
        for panel in self.widgets:
            panel.close()
            panel.deleteLater()
        self.app.processEvents()

    def test_root_properties_do_not_emit_a_user_change_on_refresh(self):
        document = new_document()
        panel = self.panel(PropertyPanel)
        changes = QSignalSpy(panel.changed)
        panel.show_document(document)
        self.assertEqual(set(panel._fields), {"title", "width", "height", "background"})
        panel.show_document(document)
        self.assertEqual(len(changes), 0)
        panel._fields["width"].setValue(960)
        self.assertEqual(list(changes[0]), ["width", 960])
        # The inspector emits an edit intent; MainWindow owns validation/mutation.
        self.assertEqual(document.width, 800)

    def test_parent_selector_excludes_descendants_and_noncontainers(self):
        document = new_document()
        outer = create_widget(document, "ttk.Frame")
        inner = create_widget(document, "ttk.Frame", outer.id)
        child = create_widget(document, "ttk.Button", inner.id)
        other = create_widget(document, "ttk.LabelFrame")
        create_widget(document, "ttk.Label")
        panel = self.panel(PropertyPanel)
        panel.show_document(document, outer.id)
        selector = panel._fields["parent"]
        options = [selector.itemData(index) for index in range(selector.count())]
        self.assertEqual(options, [None, other.id])
        panel.show_document(document, child.id)
        selector = panel._fields["parent"]
        self.assertEqual(selector.currentData(), inner.id)
        changes = QSignalSpy(panel.changed)
        selector.setCurrentIndex(selector.findData(other.id))
        self.assertEqual(list(changes[0]), ["parent", other.id])

    def test_list_property_accepts_literals_and_rejects_wrong_types(self):
        document = new_document()
        node = create_widget(document, "tk.Listbox")
        panel = self.panel(PropertyPanel)
        panel.show_document(document, node.id)
        changes = QSignalSpy(panel.changed)
        field = panel._fields["properties.items"]
        original = node.properties["items"]
        field.setText("42")
        field.editingFinished.emit()
        self.assertEqual(len(changes), 0)
        self.assertEqual(field.text(), repr(original))
        field.setText("['Uno', 'Due']")
        field.editingFinished.emit()
        self.assertEqual(list(changes[0]), ["properties.items", ["Uno", "Due"]])
        self.assertEqual(node.properties["items"], original)

    def test_state_choices_match_widget_capabilities(self):
        document = new_document()
        entry = create_widget(document, "ttk.Entry")
        entry.properties["state"] = "readonly"
        label = create_widget(document, "ttk.Label")
        label.properties["state"] = "normal"
        panel = self.panel(PropertyPanel)
        panel.show_document(document, entry.id)
        state = panel._fields["properties.state"]
        self.assertEqual(state.currentText(), "readonly")
        self.assertGreaterEqual(state.findText("readonly"), 0)
        panel.show_document(document, label.id)
        self.assertEqual(panel._fields["properties.state"].findText("readonly"), -1)

    def test_palette_search_and_doubleclick_emit_concrete_kind(self):
        panel = self.panel(PalettePanel)
        panel.search.setText("PULSANTE")
        entries = [panel.list.item(i) for i in range(panel.list.count())
                   if panel.list.item(i).data(Qt.ItemDataRole.UserRole)]
        self.assertEqual([entry.data(Qt.ItemDataRole.UserRole) for entry in entries], ["ttk.Button"])
        changes = QSignalSpy(panel.add_requested)
        panel.list.itemDoubleClicked.emit(panel.list.item(0))
        self.assertEqual(len(changes), 0)
        panel.list.itemDoubleClicked.emit(entries[0])
        self.assertEqual(list(changes[0]), ["ttk.Button"])
        panel.set_theme("light")
        self.assertEqual(panel.search.text(), "PULSANTE")
        self.assertEqual(panel.list.count(), 2)

    def test_palette_empty_results_are_not_draggable(self):
        panel = self.panel(PalettePanel)
        panel.search.setText("nessun-tipo-corrispondente")
        self.assertEqual(panel.list.count(), 1)
        item = panel.list.item(0)
        self.assertFalse(item.flags() & Qt.ItemFlag.ItemIsEnabled)
        self.assertIsNone(item.data(Qt.ItemDataRole.UserRole))

    def test_hierarchy_orders_parents_without_spurious_selection(self):
        document = new_document()
        frame = create_widget(document, "ttk.Frame")
        child = create_widget(document, "ttk.Button", frame.id)
        document.widgets.reverse()  # Serialization need not list parents first.
        panel = self.panel(HierarchyPanel)
        changes = QSignalSpy(panel.selected)
        panel.populate(document, child.id)
        root = panel.topLevelItem(0)
        self.assertEqual(root.child(0).data(0, Qt.ItemDataRole.UserRole), frame.id)
        self.assertEqual(root.child(0).child(0).data(0, Qt.ItemDataRole.UserRole), child.id)
        self.assertEqual(panel.currentItem().data(0, Qt.ItemDataRole.UserRole), child.id)
        self.assertEqual(len(changes), 0)
        panel.setCurrentItem(root)
        self.assertEqual(list(changes[0]), [None])


if __name__ == "__main__":
    unittest.main()
