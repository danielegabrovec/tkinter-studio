"""Editor-level regressions for context actions, help and live diagnostics."""
from __future__ import annotations

import os
import ast
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QCoreApplication, QEvent, Qt
from PyQt6.QtGui import QContextMenuEvent, QFontDatabase, QTextCursor
from PyQt6.QtTest import QSignalSpy, QTest
from PyQt6.QtWidgets import QApplication, QMenu

from tkstudio.assistance import Diagnostic
from tkstudio.codegen import generate_document
from tkstudio.editor import EditorPanel, python_position_to_qt, qt_position_to_python
from tkstudio.integrations import detect_context
from tkstudio.model import create_widget, default_document
from tkstudio.sync import source_to_document


class EditorAssistanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        font = Path("C:/Windows/Fonts/segoeui.ttf")
        if font.is_file(): QFontDatabase.addApplicationFont(str(font))

    def setUp(self):
        self.panel = EditorPanel()
        self.panel.resize(900, 650)
        self.panel.show()
        self.panel.editor.setFocus()
        self.app.processEvents()

    def tearDown(self):
        self.panel.syntax_timer.stop()
        self.panel.close()
        self.panel.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def source_with_button(self, callback=False):
        doc = default_document()
        node = create_widget(doc, "ttk.Button", x=30, y=440)
        node.name = "azione"
        node.properties["text"] = "Esegui"
        if callback: node.properties["command"] = "on_azione"
        return generate_document(doc)

    def select_code(self, source, fragment):
        self.panel.set_source(source)
        start = source.index(fragment)
        cursor = self.panel.editor.textCursor()
        cursor.setPosition(python_position_to_qt(source, start))
        cursor.setPosition(python_position_to_qt(source, start + len(fragment)), QTextCursor.MoveMode.KeepAnchor)
        self.panel.editor.setTextCursor(cursor)
        return detect_context(source, start, start, start + len(fragment))

    @staticmethod
    def integration_action(menu, action_id):
        for action in menu.actions():
            if action.objectName() == "integration:" + action_id: return action
            if action.menu():
                found = EditorAssistanceTests.integration_action(action.menu(), action_id)
                if found: return found
        return None

    def test_right_click_inside_selection_preserves_selected_widget_and_source(self):
        source = self.source_with_button()
        fragment = "self.azione = ttk.Button(self, text='Esegui', command='')"
        # The generator omits an empty command keyword.
        fragment = next(line.strip() for line in source.splitlines() if "self.azione =" in line)
        self.select_code(source, fragment)
        selected = self.panel.editor.textCursor().selectedText()
        changes = QSignalSpy(self.panel.source_changed)
        inside = QTextCursor(self.panel.editor.document())
        inside.setPosition(self.panel.editor.textCursor().selectionStart() + 8)
        self.panel.editor.ensureCursorVisible()
        position = self.panel.editor.cursorRect(inside).center()
        event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, position, self.panel.editor.mapToGlobal(position))
        with patch.object(QMenu, "exec", return_value=None):
            self.panel.editor.contextMenuEvent(event)
        self.assertEqual(self.panel.editor.textCursor().selectedText(), selected)
        self.assertEqual(self.panel.source(), source)
        self.assertFalse(changes)
        self.assertFalse(self.panel.editor.document().isModified())
        menu = self.panel.editor.build_context_menu()
        self.assertIsNotNone(self.integration_action(menu, "callback"))
        menu.deleteLater()

    def test_callback_insertion_is_one_undo_and_remains_compatible_with_designer(self):
        source = self.source_with_button()
        context = self.select_code(source, "self.azione =")
        changes = QSignalSpy(self.panel.source_changed)
        self.assertTrue(self.panel.apply_integration("callback", context))
        inserted = self.panel.source()
        self.assertIn("def on_azione", inserted)
        document = source_to_document(inserted)
        self.assertEqual(next(node for node in document.widgets if node.name == "azione").properties["command"], "on_azione")
        self.assertTrue(self.panel.editor.document().isModified())
        self.assertTrue(changes)
        self.panel.editor.undo()
        self.assertEqual(self.panel.source(), source)
        self.panel.editor.redo()
        self.assertEqual(self.panel.source(), inserted)

    def test_right_click_at_selection_end_does_not_collapse_selection(self):
        source = self.source_with_button()
        fragment = next(line.strip() for line in source.splitlines() if "self.azione =" in line)
        self.select_code(source, fragment)
        selected = self.panel.editor.textCursor().selectedText()
        end_cursor = QTextCursor(self.panel.editor.document())
        end_cursor.setPosition(self.panel.editor.textCursor().selectionEnd())
        position = self.panel.editor.cursorRect(end_cursor).center()
        event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, position, self.panel.editor.mapToGlobal(position))
        with patch.object(QMenu, "exec", return_value=None): self.panel.editor.contextMenuEvent(event)
        self.assertEqual(self.panel.editor.textCursor().selectedText(), selected)
        self.assertEqual(self.panel.source(), source)

    def test_existing_callback_is_opened_without_rewriting_source(self):
        source = self.source_with_button(callback=True)
        context = self.select_code(source, "self.azione =")
        changes = QSignalSpy(self.panel.source_changed)
        self.assertTrue(self.panel.apply_integration("callback", context))
        self.assertEqual(self.panel.source(), source)
        self.assertFalse(changes)
        method = next(node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.FunctionDef) and node.name == "on_azione")
        cursor_line = self.panel.editor.textCursor().blockNumber() + 1
        self.assertGreaterEqual(cursor_line, method.lineno)
        self.assertLessEqual(cursor_line, method.end_lineno)

    def test_stale_menu_action_does_not_apply_to_changed_code(self):
        source = self.source_with_button()
        self.select_code(source, "self.azione =")
        menu = self.panel.editor.build_context_menu()
        action = self.integration_action(menu, "callback")
        self.assertIsNotNone(action)
        cursor = self.panel.editor.textCursor()
        cursor.clearSelection(); cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText("\n# modifica successiva\n")
        changed = self.panel.source()
        action.trigger()
        self.assertEqual(self.panel.source(), changed)
        self.assertIn("cambiato", self.panel.help_browser.toPlainText())
        menu.deleteLater()

    def test_readonly_snapshot_allows_checks_and_help_but_not_insertion(self):
        source = self.source_with_button()
        context = self.select_code(source, "self.azione =")
        self.panel.editor.setReadOnly(True)
        self.panel.check_syntax()
        self.assertFalse(self.panel.apply_integration("callback", context))
        self.assertFalse(self.panel.integrate_button.isEnabled())
        menu = self.panel.editor.build_context_menu()
        self.assertFalse(self.integration_action(menu, "callback").isEnabled())
        self.assertEqual(self.panel.source(), source)
        self.assertEqual(self.panel.diagnostics, [])
        menu.deleteLater()

    def test_live_syntax_updates_and_clears_stale_clickable_problems(self):
        self.panel.set_source("if True\n    print('ciao')\n")
        QTest.qWait(520)
        self.assertTrue(self.panel.diagnostics)
        self.assertEqual(self.panel.diagnostics[0].severity, "error")
        self.assertEqual(self.panel.diagnostics[0].line, 1)
        self.assertIn("errore", self.panel.syntax_button.text())
        self.assertIsNotNone(self.panel.editor.diagnostic_at_line(1))
        self.assertTrue(any(selection.format.underlineStyle() != selection.format.UnderlineStyle.NoUnderline for selection in self.panel.editor.extraSelections()))
        self.panel.set_source("if True:\n    print('ciao')\n")
        self.assertEqual(self.panel.diagnostics, [])
        self.assertIsNone(self.panel.problems.item(0).data(Qt.ItemDataRole.UserRole))
        self.assertIn("Controllo", self.panel.syntax_button.text())
        QTest.qWait(520)
        self.assertEqual(self.panel.diagnostics, [])
        self.assertEqual(self.panel.syntax_button.text(), "Sintassi corretta")
        self.assertFalse(self.panel.editor.document().isModified())

    def test_manual_f8_reveals_problems_and_does_not_run_the_file(self):
        with tempfile.TemporaryDirectory() as directory:
            sentinel = Path(directory) / "non-deve-esistere.txt"
            self.panel.set_source("from pathlib import Path\n" + f"Path({str(sentinel)!r}).write_text('executed')\n" + "return 42\n")
            QTest.keyClick(self.panel.editor, Qt.Key.Key_F8)
            self.assertFalse(sentinel.exists())
            self.assertTrue(self.panel.assistance_tabs.isVisible())
            self.assertTrue(self.panel.diagnostics)
            self.assertEqual(self.panel.diagnostics[0].line, 3)

    def test_non_python_files_do_not_report_false_python_errors(self):
        self.panel.path = "documento.json"
        self.panel.set_source('{"saluto": true}')
        self.assertEqual(self.panel.check_syntax(), [])
        self.assertEqual(self.panel.syntax_button.text(), "File di testo")
        self.assertFalse(self.panel.integrate_button.isEnabled())
        self.assertFalse(self.panel.apply_integration("insert_function"))
        menu = self.panel.editor.build_context_menu()
        self.assertIsNone(self.integration_action(menu, "insert_function"))
        menu.deleteLater()

    def test_diagnostic_navigation_converts_unicode_offsets_to_qt_units(self):
        source = "nome = '😀'; valore =\n"
        self.panel.set_source(source)
        diagnostics = self.panel.check_syntax()
        self.assertTrue(diagnostics)
        diagnostic = diagnostics[0]
        self.panel.go_to_diagnostic(diagnostic)
        self.assertEqual(self.panel.editor.textCursor().position(), python_position_to_qt(source, min(diagnostic.column - 1, len(source.rstrip("\n")))))
        self.assertEqual(qt_position_to_python(source, python_position_to_qt(source, source.index("valore"))), source.index("valore"))

    def test_help_is_escaped_and_recolored_without_changing_source_or_focus(self):
        source = 'def mia_funzione():\n    """Mostra <b>testo</b> senza markup."""\n    pass\n'
        self.panel.set_source(source)
        cursor = self.panel.editor.textCursor(); cursor.setPosition(source.index("mia_funzione") + 3); self.panel.editor.setTextCursor(cursor)
        position = cursor.position(); changes = QSignalSpy(self.panel.source_changed)
        self.panel.show_code_help()
        self.assertIn("<b>testo</b>", self.panel.help_browser.toPlainText())
        dark = self.panel.help_browser.toHtml()
        self.panel.set_theme("light")
        self.assertNotEqual(dark, self.panel.help_browser.toHtml())
        self.assertEqual(self.panel.editor.textCursor().position(), position)
        self.assertEqual(self.panel.source(), source)
        self.assertFalse(changes)
        self.panel.assistance_tabs.hide()
        self.panel.set_theme("dark")
        self.assertFalse(self.panel.assistance_tabs.isVisible())

    def test_completion_uses_user_symbols_and_does_not_duplicate_self(self):
        self.panel.set_source("class App:\n    def calcola_totale(self):\n        self.risultato = 1\n        self.cal\n")
        self.panel.check_syntax()
        self.assertIn("calcola_totale", self.panel.editor.completer.model().stringList())
        self.panel.editor.moveCursor(QTextCursor.MoveOperation.End)
        cursor = self.panel.editor.textCursor(); cursor.movePosition(QTextCursor.MoveOperation.PreviousBlock); cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock); self.panel.editor.setTextCursor(cursor)
        self.panel.editor._insert_completion("self.calcola_totale")
        self.assertIn("        self.calcola_totale\n", self.panel.source())
        self.assertNotIn("self.self.", self.panel.source())

    def test_syntax_warnings_are_separate_from_runtime_error_and_widget_highlight(self):
        self.panel.set_source("value = 1\nprint(value)\n")
        warning = Diagnostic("warning", "Avviso di prova", 2, 1, 2, 6, "Controlla il valore", "test")
        self.panel.point_to_widget(1, 2)
        self.panel.highlight_error(2)
        with patch("tkstudio.assistance.analyze_source", return_value=[warning]): self.panel.check_syntax()
        self.assertEqual(self.panel.editor._widget_lines, (1, 2))
        self.assertEqual(self.panel.editor._error_line, 2)
        self.assertIn("avviso", self.panel.syntax_button.text())
        self.panel.problems.itemClicked.emit(self.panel.problems.item(0))
        self.assertEqual(self.panel.editor.textCursor().blockNumber(), 1)

    def test_error_badge_points_to_error_even_if_a_warning_precedes_it(self):
        self.panel.set_source("value = 1\nprint(value)\nreturn value\n")
        warning = Diagnostic("warning", "Avviso prima dell’errore", 1, 1, 1, 6, "", "warning")
        error = Diagnostic("error", "Return fuori funzione", 3, 1, 3, 7, "", "syntax")
        with patch("tkstudio.assistance.analyze_source", return_value=[warning, error]): self.panel.check_syntax()
        self.assertEqual(self.panel.syntax_button.text(), "1 errore · riga 3")
        self.panel.editor.set_diagnostics([warning, Diagnostic("warning", "Avviso stessa riga", 3, 1, 3, 4, "", "warning"), error])
        self.assertEqual(self.panel.editor.diagnostic_at_line(3).severity, "error")


if __name__ == "__main__": unittest.main()
