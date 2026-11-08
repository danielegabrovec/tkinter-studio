"""End-to-end workbench checks with isolated files, settings and recovery state."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from PyQt6.QtCore import QCoreApplication, QEvent, QSettings
from PyQt6.QtGui import QTextCursor
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMessageBox

from tkstudio.app import MainWindow
from tkstudio.codegen import generate_document
from tkstudio.model import default_document


APP = QApplication.instance() or QApplication([])


def wait_until(predicate, timeout=8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        APP.processEvents()
        if predicate():
            return True
        QTest.qWait(10)
    return bool(predicate())


class AppRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="tkstudio-app-")
        self.directory = Path(self.temporary.name)
        self.settings = QSettings(str(self.directory / "settings.ini"), QSettings.Format.IniFormat)
        self.settings_patch = patch("tkstudio.app.QSettings", return_value=self.settings)
        self.settings_patch.start()
        self.recovery_patch = patch.object(MainWindow, "_recovery_path", return_value=self.directory / "recovery.json")
        self.recovery_patch.start()
        self.question_patch = patch("tkstudio.app.QMessageBox.question", return_value=QMessageBox.StandardButton.Discard)
        self.question_patch.start()
        document = default_document()
        self.original_source = generate_document(document)
        (self.directory / "app.py").write_text(self.original_source, encoding="utf-8")
        metadata = document.to_dict()
        metadata["python_file"] = "app.py"
        self.project = self.directory / "progetto.tkui"
        self.project.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
        self.window = MainWindow(self.project, restore_session=False)
        self.window.show()
        self.results = []
        self.window.runner.finished.connect(lambda code, reason: self.results.append((code, reason)))
        APP.processEvents()

    def tearDown(self):
        self.window.sync_timer.stop()
        self.window.recovery_timer.stop()
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        APP.processEvents()
        self.settings.sync()
        self.question_patch.stop()
        self.recovery_patch.stop()
        self.settings_patch.stop()
        self.temporary.cleanup()

    def replace_source(self, editor, source):
        cursor = editor.editor.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.insertText(source)
        editor.editor.setTextCursor(cursor)

    def console(self):
        return self.window.console.output.toPlainText()

    def finish_run(self):
        self.assertTrue(wait_until(lambda: bool(self.results)), self.console())
        self.assertFalse(self.window.runner.running)
        self.assertTrue(self.window.play_button.isEnabled())
        self.assertFalse(self.window.stop_button.isEnabled())
        self.assertFalse(self.window.console.input_field.isEnabled())
        self.assertFalse(list(self.directory.glob("_tkstudio_run_*.py")))

    def test_startup_opens_requested_project_without_dirty_state(self):
        self.assertEqual(self.window.project_path, self.project.resolve())
        self.assertEqual(self.window.main_editor.source(), self.original_source)
        self.assertFalse(self.window._main_dirty())
        self.assertTrue(self.window._sync_ok)
        self.assertFalse(self.window._sync_pending)
        # Windows' offscreen plugin does not report a QFontInfo family, so
        # check the selected family and the actual glyph advance instead.
        for widget in (self.window.main_editor.editor, self.window.console.output):
            self.assertIn(widget.font().family(), ("Cascadia Code", "Consolas", "DejaVu Sans Mono", "monospace"))
            metrics = widget.fontMetrics()
            self.assertLessEqual(abs(metrics.horizontalAdvance("iiii") - metrics.horizontalAdvance("wwww")), 1)

    def test_play_uses_unsaved_editor_snapshot_without_overwriting_source(self):
        code = "from pathlib import Path\nprint('VERSIONE NON SALVATA ✓')\nprint(Path.cwd().name)\n"
        self.replace_source(self.window.main_editor, code)
        self.window.play()
        self.finish_run()
        self.assertEqual(self.results, [(0, "success")])
        self.assertIn("VERSIONE NON SALVATA ✓", self.console())
        self.assertIn(self.directory.name, self.console())
        self.assertEqual((self.directory / "app.py").read_text(encoding="utf-8"), self.original_source)
        self.assertEqual(self.window.main_editor.source(), code)
        self.assertTrue(self.window._main_dirty())

    def test_active_other_python_tab_supports_input_errors_and_traceback_mapping(self):
        disk_source = "print('VERSIONE SUL DISCO')\n"
        path = self.directory / "strumento.py"
        path.write_text(disk_source, encoding="utf-8")
        self.window.open_file(str(path))
        editor = self.window.current_editor()
        code = "name = input('Nome? ')\nprint('Ciao', name)\nraise ValueError('errore di prova')\n"
        self.replace_source(editor, code)
        self.window.play()
        self.assertTrue(wait_until(lambda: "Nome?" in self.console()))
        self.assertTrue(self.window.console.input_field.isEnabled())
        snapshot = self.window._run_path
        self.window.console.input_field.setText("Daniele")
        self.window.console._submit_input()
        self.finish_run()
        self.assertEqual(self.results[0][1], "error")
        self.assertIn("Ciao Daniele", self.console())
        self.assertIn("ValueError: errore di prova", self.console())
        self.assertEqual(path.read_text(encoding="utf-8"), disk_source)
        self.assertEqual(editor.source(), code)
        self.window.open_location(str(snapshot), 3)
        self.assertIs(self.window.current_editor(), editor)
        self.assertEqual(editor.editor.textCursor().blockNumber(), 2)
        self.assertEqual(len(editor.editor.extraSelections()), 2)

    def test_syntax_error_is_highlighted_without_starting_process(self):
        self.replace_source(self.window.main_editor, "def broken(:\n    pass\n")
        self.window.play()
        self.assertFalse(self.window.runner.running)
        self.assertFalse(self.results)
        self.assertIn("Errore di sintassi alla riga 1", self.console())
        self.assertEqual(len(self.window.main_editor.editor.extraSelections()), 2)
        self.assertTrue(self.window.play_button.isEnabled())
        self.assertFalse(list(self.directory.glob("_tkstudio_run_*.py")))

    def test_stop_cleans_up_snapshot_and_restores_controls(self):
        self.replace_source(self.window.main_editor, "import time\nprint('READY')\ntime.sleep(60)\n")
        self.window.play()
        self.assertTrue(wait_until(lambda: "READY" in self.console()))
        self.assertTrue(self.window.stop_button.isEnabled())
        self.assertFalse(self.window.play_button.isEnabled())
        self.window.runner.stop()
        self.finish_run()
        self.assertEqual(self.results[0][1], "stopped")
        self.assertEqual((self.directory / "app.py").read_text(encoding="utf-8"), self.original_source)

    def test_theme_preserves_pending_code_sync_and_does_not_dirty_clean_source(self):
        self.window.toggle_theme()
        APP.processEvents()
        self.assertFalse(self.window._main_dirty())
        self.assertFalse(self.window._sync_pending)
        source = self.window.main_editor.source().replace(repr(self.window.doc.title), repr("La mia nuova app"))
        self.replace_source(self.window.main_editor, source)
        self.assertTrue(self.window._sync_pending)
        self.assertTrue(self.window.sync_timer.isActive())
        self.window.toggle_theme()
        self.assertTrue(self.window._sync_pending)
        self.assertTrue(self.window.sync_timer.isActive())
        self.assertTrue(wait_until(lambda: not self.window._sync_pending))
        self.assertTrue(self.window._sync_ok)
        self.assertEqual(self.window.main_editor.source(), source)
        self.assertEqual(self.window.doc.title, "La mia nuova app")

    def test_callback_activation_preserves_edited_logic_and_positions_cursor(self):
        button = next(node for node in self.window.doc.widgets if node.kind == "ttk.Button")
        command = button.properties["command"]
        original = self.window.main_editor.source()
        changed = original.replace("messagebox.showinfo('Ciao!', f'Ciao, {nome}!')", "print('LOGICA PERSONALIZZATA')")
        self.assertNotEqual(original, changed)
        self.replace_source(self.window.main_editor, changed)
        self.assertTrue(self.window.sync_from_code())
        self.window.designer.widget_activated.emit(button.id)
        self.assertEqual(self.window.view_mode, "split")
        self.assertEqual(self.window.main_editor.source(), changed)
        self.assertIn("def " + command, changed)
        expected = next(i for i, line in enumerate(changed.splitlines()) if line.strip().startswith("def " + command + "(")) + 1
        self.assertEqual(self.window.main_editor.editor.textCursor().blockNumber(), expected)

    def test_traceback_after_closed_run_tab_opens_readonly_snapshot_safely(self):
        path = self.directory / "chiusa.py"
        path.write_text("print('fatto')\n", encoding="utf-8")
        self.window.open_file(str(path))
        editor = self.window.current_editor()
        self.window.play()
        snapshot = self.window._run_path
        self.finish_run()
        index = self.window.editors.indexOf(editor)
        self.window.close_editor(index)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        APP.processEvents()
        self.window.open_location(str(snapshot), 1)
        self.assertTrue(self.window.current_editor().editor.isReadOnly())
        self.assertEqual(self.window.current_editor().source(), "print('fatto')\n")

    def test_old_traceback_keeps_original_source_after_edit_and_later_run(self):
        first = "print('prima esecuzione')\nraise RuntimeError('prima')\n"
        self.replace_source(self.window.main_editor, first)
        self.window.play()
        snapshot = self.window._run_path
        self.finish_run()
        self.results.clear()
        second = "print('seconda esecuzione')\n"
        self.replace_source(self.window.main_editor, second)
        self.window.play()
        self.finish_run()
        self.window.open_location(str(snapshot), 2)
        historical = self.window.current_editor()
        self.assertIsNot(historical, self.window.main_editor)
        self.assertTrue(historical.editor.isReadOnly())
        self.assertEqual(historical.source(), first)
        self.assertEqual(self.window.main_editor.source(), second)
        self.assertEqual(historical.editor.textCursor().blockNumber(), 1)

    def test_nested_python_file_uses_its_folder_for_local_imports_and_resources(self):
        directory = self.directory / "strumenti"
        directory.mkdir()
        (directory / "modulo_locale.py").write_text("VALUE = 'IMPORT LOCALE OK'\n", encoding="utf-8")
        (directory / "dato.txt").write_text("RISORSA LOCALE OK", encoding="utf-8")
        path = directory / "strumento.py"
        code = "from pathlib import Path\nfrom modulo_locale import VALUE\nprint(VALUE)\nprint(Path('dato.txt').read_text(encoding='utf-8'))\n"
        path.write_text(code, encoding="utf-8")
        self.window.open_file(str(path))
        self.window.play()
        self.finish_run()
        self.assertEqual(self.results, [(0, "success")])
        self.assertIn("IMPORT LOCALE OK", self.console())
        self.assertIn("RISORSA LOCALE OK", self.console())
        self.assertFalse(list(directory.glob("_tkstudio_run_*.py")))
        self.assertEqual(path.read_text(encoding="utf-8"), code)

    def test_window_close_stops_owned_process_and_removes_snapshot(self):
        self.replace_source(self.window.main_editor, "import time\nprint('READY TO CLOSE')\ntime.sleep(60)\n")
        self.window.play()
        self.assertTrue(wait_until(lambda: "READY TO CLOSE" in self.console()))
        snapshot = self.window._run_path
        self.assertTrue(snapshot.exists())
        self.assertTrue(self.window.close())
        self.assertFalse(self.window.runner.running)
        self.assertFalse(snapshot.exists())
        self.assertTrue(self.results)
        self.assertEqual(self.results[-1][1], "stopped")


if __name__ == "__main__":
    unittest.main()
