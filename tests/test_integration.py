"""Desktop integration: designer, Python, history and actual project files.

The tests run without visible windows. Settings and recovery are redirected to
temporary INI/files, so no user Registry or restored session is changed.
"""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPointF, QSettings
from PyQt6.QtWidgets import QApplication, QMessageBox

from tkstudio.app import MainWindow
from tkstudio.codegen import generate_document
from tkstudio.model import default_document


class MainWindowIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])
        cls.application.setApplicationName("TkStudioIntegrationTests")

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="tkstudio integration è ")
        self.base = Path(self.temporary.name)
        self.project = self.base / "progetto.tkui"
        self.python = self.base / "app.py"
        self.original_document = default_document()
        self.original_source = generate_document(self.original_document)
        self.python.write_text(self.original_source, encoding="utf-8")
        data = self.original_document.to_dict()
        data["python_file"] = "app.py"
        self.project.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        self.settings_patch = patch("tkstudio.app.QSettings", lambda *args: QSettings(str(self.base / "settings.ini"), QSettings.Format.IniFormat))
        self.recovery_patch = patch.object(MainWindow, "_recovery_path", lambda window: self.base / "recovery.json")
        self.warning_patch = patch("tkstudio.app.QMessageBox.warning", return_value=QMessageBox.StandardButton.Ok)
        self.question_patch = patch("tkstudio.app.QMessageBox.question", return_value=QMessageBox.StandardButton.Cancel)
        self.settings_patch.start()
        self.recovery_patch.start()
        self.warning = self.warning_patch.start()
        self.question = self.question_patch.start()
        self.window = MainWindow(self.project, restore_session=False)
        self.window.recovery_timer.stop()
        self.application.processEvents()

    def tearDown(self):
        self.window.sync_timer.stop()
        self.window.recovery_timer.stop()
        with patch.object(self.window, "_allow_switch", return_value=True):
            self.window.close()
        self.window.deleteLater()
        self.application.processEvents()
        self.question_patch.stop()
        self.warning_patch.stop()
        self.recovery_patch.stop()
        self.settings_patch.stop()
        self.temporary.cleanup()

    def edit_source(self, source):
        # setPlainText emits the real user editing signal; EditorPanel.set_source
        # deliberately suppresses that signal during a programmatic refresh.
        self.window.main_editor.editor.setPlainText(source)
        self.window.sync_timer.stop()

    def test_project_opens_with_synced_canvas_and_no_pending_changes(self):
        self.assertTrue(self.window._sync_ok)
        self.assertFalse(self.window._main_dirty())
        self.assertEqual(self.window.main_editor.source(), self.original_source)
        self.assertEqual(self.window.doc.to_dict(), self.original_document.to_dict())
        self.assertEqual(set(self.window.designer.view.items_by_id), {node.id for node in self.original_document.widgets})

    def test_canvas_add_generates_python_and_can_undo_and_redo(self):
        original = self.window.doc.to_dict()
        node = self.window.designer.add_widget("ttk.Button", position=(560, 420))
        self.assertIsNotNone(node)
        changed_source = self.window.main_editor.source()
        changed_document = copy.deepcopy(self.window.doc.to_dict())
        self.assertIn(f"self.{node.name} = ttk.Button(", changed_source)
        self.assertIn(f"# widget:{node.id}", changed_source)
        self.assertTrue(self.window._main_dirty())
        self.window.undo()
        self.assertEqual(self.window.doc.to_dict(), original)
        self.assertEqual(self.window.main_editor.source(), self.original_source)
        self.window.redo()
        self.assertEqual(self.window.doc.to_dict(), changed_document)
        self.assertEqual(self.window.main_editor.source(), changed_source)

    def test_editing_python_literals_updates_canvas_without_rewriting_source(self):
        node = next(node for node in self.window.doc.widgets if node.name == "saluta")
        source = self.original_source.replace("text='Saluta'", "text='Prova adesso'")
        self.edit_source(source)
        self.assertTrue(self.window._sync_pending)
        self.assertFalse(self.window.designer.view.editable)
        self.assertTrue(self.window.sync_from_code())
        self.assertTrue(self.window.designer.view.editable)
        self.assertEqual(self.window.doc.find(node.id).properties["text"], "Prova adesso")
        self.assertEqual(self.window.designer.view.items_by_id[node.id].node.properties["text"], "Prova adesso")
        self.assertEqual(self.window.main_editor.source(), source)

    def test_custom_callback_survives_later_canvas_drag(self):
        custom_line = "        print('Logica personale preservata: è un test')"
        source = self.original_source.replace("        nome = self.nome.get().strip() or 'Mondo'",
                                              custom_line + "\n        nome = self.nome.get().strip() or 'Mondo'")
        self.edit_source(source)
        self.assertTrue(self.window.sync_from_code())
        node = next(node for node in self.window.doc.widgets if node.name == "saluta")
        item = self.window.designer.view.items_by_id[node.id]
        self.window.designer.view.begin_gesture()
        item.setPos(QPointF(80, 160))
        self.window.designer.view.end_gesture()
        result = self.window.main_editor.source()
        self.assertIn(custom_line, result)
        self.assertEqual(result.count("def on_saluta(self):"), 1)
        self.assertIn("self.saluta.place(x=80, y=160, width=148, height=36)", result)
        self.assertTrue(self.window._sync_ok)

    def test_unsupported_expression_locks_designer_and_save_preserves_python(self):
        source = self.original_source.replace("text='Saluta'", "text=str(40 + 2)")
        original_model = self.window.doc.to_dict()
        self.edit_source(source)
        self.assertFalse(self.window.sync_from_code())
        self.assertFalse(self.window.designer.view.editable)
        self.assertIsNone(self.window.designer.add_widget("ttk.Label"))
        self.assertEqual(self.window.doc.to_dict(), original_model)
        self.assertTrue(self.window.save_project())
        self.assertEqual(self.python.read_text(encoding="utf-8"), source)
        self.window.load_project(self.project)
        self.assertFalse(self.window._sync_ok)
        self.assertFalse(self.window.designer.view.editable)
        self.assertEqual(self.window.main_editor.source(), source)

    def test_save_and_reopen_preserve_both_visual_document_and_source(self):
        node = self.window.designer.add_widget("tk.Text", position=(400, 400))
        self.window.selection_changed(node.id)
        self.window.property_changed("properties.text", "Contenuto su due righe\ncon accenti: è, ì, ò")
        document = copy.deepcopy(self.window.doc.to_dict())
        source = self.window.main_editor.source()
        self.assertTrue(self.window.save_project())
        saved = json.loads(self.project.read_text(encoding="utf-8"))
        self.assertEqual(saved.pop("python_file"), "app.py")
        self.assertEqual(saved, document)
        self.window.load_project(self.project)
        self.assertEqual(self.window.doc.to_dict(), document)
        self.assertEqual(self.window.main_editor.source(), source)
        self.assertFalse(self.window._main_dirty())

    def test_cancel_external_source_conflict_leaves_both_disk_files_unchanged(self):
        self.window.designer.add_widget("ttk.Label", position=(500, 470))
        external = "# Modifica esterna da preservare\n" + self.original_source
        self.python.write_text(external, encoding="utf-8")
        model_bytes = self.project.read_bytes()
        editor_source = self.window.main_editor.source()
        self.assertFalse(self.window.save_project())
        self.assertEqual(self.python.read_text(encoding="utf-8"), external)
        self.assertEqual(self.project.read_bytes(), model_bytes)
        self.assertEqual(self.window.main_editor.source(), editor_source)
        self.assertTrue(self.window._main_dirty())
        self.assertIn("cambiato sul disco", self.question.call_args.args[2])

    def test_cancel_external_project_conflict_does_not_write_python_first(self):
        self.window.designer.add_widget("ttk.Label", position=(500, 470))
        self.project.write_text(self.project.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        source_bytes, model_bytes = self.python.read_bytes(), self.project.read_bytes()
        self.assertFalse(self.window.save_project())
        self.assertEqual(self.python.read_bytes(), source_bytes)
        self.assertEqual(self.project.read_bytes(), model_bytes)

    def test_undo_to_incompatible_saved_source_keeps_designer_locked(self):
        incompatible = self.original_source.replace("text='Saluta'", "text=str(40 + 2)")
        self.python.write_text(incompatible, encoding="utf-8")
        self.window.load_project(self.project)
        self.assertFalse(self.window._sync_ok)
        self.edit_source(self.original_source)
        self.assertTrue(self.window.sync_from_code())
        self.window.undo()
        self.assertEqual(self.window.main_editor.source(), incompatible)
        self.assertFalse(self.window._sync_ok)
        self.assertFalse(self.window.designer.view.editable)

    def test_invalid_widget_name_is_rejected_without_losing_document_or_code(self):
        node = next(node for node in self.window.doc.widgets if node.name == "saluta")
        previous = copy.deepcopy(self.window.doc.to_dict())
        source = self.window.main_editor.source()
        self.window.selection_changed(node.id)
        self.window.property_changed("name", "destroy")
        self.assertEqual(self.window.doc.to_dict(), previous)
        self.assertEqual(self.window.main_editor.source(), source)
        self.assertTrue(self.warning.called)

    def test_rename_widget_from_inspector_keeps_existing_callback_references(self):
        node = next(node for node in self.window.doc.widgets if node.name == "nome")
        self.window.selection_changed(node.id)
        self.window.property_changed("name", "nome_utente")
        source = self.window.main_editor.source()
        self.assertTrue(self.window._sync_ok)
        self.assertEqual(self.window.doc.find(node.id).name, "nome_utente")
        self.assertIn("nome = self.nome_utente.get().strip()", source)
        self.assertIn("self.nome_utente = ttk.Entry", source)
        self.assertNotIn("self.nome.get()", source)

    def test_rename_checkbutton_from_inspector_preserves_sync_and_variable(self):
        node = self.window.designer.add_widget("ttk.Checkbutton", position=(500, 480))
        self.window.selection_changed(node.id)
        self.window.property_changed("name", "consenso")
        self.assertTrue(self.window._sync_ok)
        self.assertEqual(self.window.doc.find(node.id).name, "consenso")
        self.assertIn("variable=self._var_consenso", self.window.main_editor.source())


if __name__ == "__main__":
    unittest.main()
