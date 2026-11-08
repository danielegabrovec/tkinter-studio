"""The new editing tools must cooperate with the existing project/designer flow."""
from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QCoreApplication, QEvent, QSettings
from PyQt6.QtGui import QTextCursor
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMessageBox

from tkstudio.app import MainWindow
from tkstudio.codegen import generate_document
from tkstudio.integrations import detect_context
from tkstudio.model import create_widget, default_document
from tkstudio.sync import source_to_document


class AssistanceIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="tkstudio-code-tools-")
        self.base = Path(self.temp.name)
        doc = default_document()
        button = create_widget(doc, "ttk.Button", x=520, y=450)
        button.name = "aggiungi"; button.properties["text"] = "Aggiungi"
        data = doc.to_dict(); data["python_file"] = "app.py"
        self.original = generate_document(doc)
        (self.base / "app.py").write_text(self.original, encoding="utf-8")
        self.project = self.base / "progetto.tkui"
        self.project.write_text(json.dumps(data), encoding="utf-8")
        self.settings = QSettings(str(self.base / "settings.ini"), QSettings.Format.IniFormat)
        self.patchers = [patch("tkstudio.app.QSettings", return_value=self.settings),
                         patch.object(MainWindow, "_recovery_path", return_value=self.base / "recovery.json"),
                         patch("tkstudio.app.QMessageBox.question", return_value=QMessageBox.StandardButton.Discard)]
        for item in self.patchers: item.start()
        self.window = MainWindow(self.project, restore_session=False)
        self.window.recovery_timer.stop()
        self.panel = self.window.main_editor

    def tearDown(self):
        self.window.sync_timer.stop(); self.window.selection_reveal_timer.stop(); self.panel.syntax_timer.stop()
        with patch.object(self.window, "_allow_switch", return_value=True): self.window.close()
        self.window.deleteLater(); QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents(); self.settings.sync()
        for item in reversed(self.patchers): item.stop()
        self.temp.cleanup()

    def context(self, name):
        source = self.panel.source()
        return detect_context(source, source.index("self." + name + " =") + len("self."))

    def test_insert_callback_updates_designer_and_one_undo_restores_source(self):
        self.assertTrue(self.panel.apply_integration("callback", self.context("aggiungi")))
        self.assertTrue(self.window.sync_from_code())
        node = next(node for node in self.window.doc.widgets if node.name == "aggiungi")
        self.assertTrue(node.properties["command"])
        self.assertTrue(self.window._main_dirty())
        self.assertIn("def " + node.properties["command"], self.panel.source())
        self.panel.editor.undo()
        self.assertEqual(self.panel.source(), self.original)
        self.assertTrue(self.window.sync_from_code())

    def test_existing_callback_is_opened_without_code_or_dirty_changes(self):
        before = self.panel.source()
        self.assertTrue(self.panel.apply_integration("callback", self.context("saluta")))
        self.assertEqual(self.panel.source(), before)
        line = self.panel.editor.textCursor().blockNumber()
        self.assertIn("nome =", self.panel.source().splitlines()[line])
        self.assertFalse(self.window._main_dirty())

    def test_label_event_survives_visual_edit_save_and_reopen(self):
        self.assertTrue(self.panel.apply_integration("bind_click", self.context("etichetta_nome")))
        self.assertTrue(self.window.sync_from_code())
        integrated = self.panel.source()
        node = next(node for node in self.window.doc.widgets if node.name == "etichetta_nome")
        self.window.designer.select_widget(node.id)
        self.window.property_changed("properties.text", "Clicca questa etichetta")
        self.assertTrue(self.window._sync_ok)
        self.assertIn(".bind(", self.panel.source())
        self.assertEqual(self.panel.source().count(".bind("), integrated.count(".bind("))
        self.assertTrue(self.window.save_project())
        saved = self.panel.source()
        self.window.load_project(self.project)
        self.assertEqual(self.panel.source(), saved)
        self.assertTrue(self.window._sync_ok)
        compile(saved, "app.py", "exec")

    def test_rename_integrated_label_updates_bind_references(self):
        self.assertTrue(self.panel.apply_integration("bind_click", self.context("etichetta_nome")))
        self.assertTrue(self.window.sync_from_code())
        node = next(node for node in self.window.doc.widgets if node.name == "etichetta_nome")
        self.window.designer.select_widget(node.id)
        self.window.property_changed("name", "etichetta_persona")
        self.assertIn("self.etichetta_persona.bind(", self.panel.source())
        self.assertNotIn("self.etichetta_nome", self.panel.source())
        self.assertTrue(self.window._sync_ok)

    def test_deleting_integrated_widget_removes_only_generated_connection(self):
        self.assertTrue(self.panel.apply_integration("bind_click", self.context("etichetta_nome")))
        self.assertTrue(self.window.sync_from_code())
        before = ast.parse(self.panel.source())
        before_methods = {node.name for node in ast.walk(before) if isinstance(node, ast.FunctionDef)}
        node = next(node for node in self.window.doc.widgets if node.name == "etichetta_nome")
        self.window.designer.select_widget(node.id); self.window.designer.delete_selected()
        self.assertTrue(self.window._sync_ok)
        self.assertNotIn("self.etichetta_nome.bind(", self.panel.source())
        after_methods = {node.name for node in ast.walk(ast.parse(self.panel.source())) if isinstance(node, ast.FunctionDef)}
        self.assertTrue(before_methods.issubset(after_methods))
        source_to_document(self.panel.source())

    def test_play_blocks_invalid_context_even_if_ast_parse_accepts_it(self):
        self.panel.set_source("return 42\n")
        self.window.play()
        self.assertFalse(self.window.runner.running)
        self.assertIsNone(self.window._run_path)
        self.assertIn("Errore di sintassi", self.window.console.output.toPlainText())
        self.assertTrue(any(item.severity == "error" for item in self.panel.diagnostics))

    def test_syntax_check_and_help_never_change_source_or_dirty_state(self):
        self.assertEqual(self.window._check_code(), [])
        position = self.panel.source().index("ttk.Button") + 4
        self.panel.show_code_help(position)
        self.assertIn("Button", self.panel.help_browser.toPlainText())
        self.assertEqual(self.panel.source(), self.original)
        self.assertFalse(self.window._main_dirty())

    def test_text_file_is_excluded_from_python_validation(self):
        path = self.base / "note.md"; path.write_text("# I miei appunti\nQuesto non è Python.\n", encoding="utf-8")
        self.window.open_file(path)
        panel = self.window.editors.currentWidget()
        self.assertEqual(self.window._check_code(), [])
        self.assertEqual(panel.diagnostics, [])
        self.assertIn(".py", self.window.status.text())


if __name__ == "__main__": unittest.main()
