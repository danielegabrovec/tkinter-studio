"""Behaviour checks for editing and execution; no desktop interaction required."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from PyQt6.QtCore import QCoreApplication, QEvent, QObject, Qt, QUrl
from PyQt6.QtGui import QTextCursor
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from tkstudio.editor import EditorPanel, PALETTES
from tkstudio.runner import ConsolePanel, ProcessRunner


APP = QApplication.instance() or QApplication([])


def wait_until(predicate, timeout: float = 7.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        APP.processEvents()
        if predicate():
            return True
        QTest.qWait(10)
    return bool(predicate())


class EditorTests(unittest.TestCase):
    def setUp(self):
        self.panel = EditorPanel()
        self.panel.resize(1000, 600)
        self.panel.show()
        self.panel.editor.setFocus()
        APP.processEvents()

    def tearDown(self):
        self.panel.close()
        self.panel.deleteLater()
        APP.processEvents()

    def test_programmatic_source_does_not_emit_user_change(self):
        changes = []
        self.panel.source_changed.connect(lambda: changes.append(True))
        self.panel.set_source("print('Ciao')\n")
        self.assertFalse(changes)
        self.panel.editor.insertPlainText("# Prova\n")
        self.assertTrue(changes)

    def test_autoindent_and_tab_are_undoable(self):
        editor = self.panel.editor
        self.panel.set_source("def saluta():")
        editor.moveCursor(QTextCursor.MoveOperation.End)
        QTest.keyClick(editor, Qt.Key.Key_Return)
        self.assertEqual(self.panel.source(), "def saluta():\n    ")
        QTest.keyClick(editor, Qt.Key.Key_Tab)
        self.assertEqual(self.panel.source(), "def saluta():\n        ")
        QTest.keyClick(editor, Qt.Key.Key_Backspace)
        self.assertEqual(self.panel.source(), "def saluta():\n    ")
        editor.undo()
        self.assertEqual(self.panel.source(), "def saluta():\n        ")

    def test_selection_indent_and_dedent(self):
        editor = self.panel.editor
        original = "one\ntwo\nthree"
        self.panel.set_source(original)
        cursor = editor.textCursor()
        cursor.setPosition(0)
        cursor.setPosition(8, QTextCursor.MoveMode.KeepAnchor)
        editor.setTextCursor(cursor)
        QTest.keyClick(editor, Qt.Key.Key_Tab)
        self.assertEqual(self.panel.source(), "    one\n    two\nthree")
        QTest.keyClick(editor, Qt.Key.Key_Backtab)
        self.assertEqual(self.panel.source(), original)

    def test_replace_all_does_not_repeat_replacement_matches(self):
        self.panel.set_source("test test\nTEST")
        self.panel.find_field.setText("test")
        self.panel.replace_field.setText("test_more")
        self.assertEqual(self.panel.replace_all(), 3)
        self.assertEqual(self.panel.source(), "test_more test_more\ntest_more")
        self.panel.editor.undo()
        self.assertEqual(self.panel.source(), "test test\nTEST")

    def test_atomic_save_and_reopen_unicode(self):
        source = "# Città e caffè\nprint('✓')\n"
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "città.py"
            self.panel.set_source(source)
            self.panel.save_path(target)
            self.assertEqual(target.read_text(encoding="utf-8"), source)
            self.panel.set_source("changed")
            self.panel.open_path(target)
            self.assertEqual(self.panel.source(), source)
            self.assertEqual(self.panel.path, str(target.resolve()))

    def test_line_navigation_error_and_theme(self):
        self.panel.set_source("first\nsecond\nthird\n")
        self.panel.go_to_line(3)
        self.assertEqual(self.panel.editor.textCursor().blockNumber(), 2)
        self.panel.highlight_error(2)
        self.assertEqual(len(self.panel.editor.extraSelections()), 2)
        self.panel.set_theme("light")
        self.panel.editor.insertPlainText("x")
        self.assertEqual(len(self.panel.editor.extraSelections()), 1)

    def test_multiline_strings_are_highlighted_without_execution(self):
        self.panel.set_source('text = """first\nsecond\nthird"""\nvalue = 42\n')
        self.panel.editor.highlighter.rehighlight()
        document = self.panel.editor.document()
        self.assertEqual(document.findBlockByNumber(0).userState(), 2)
        self.assertEqual(document.findBlockByNumber(1).userState(), 2)
        self.assertEqual(document.findBlockByNumber(2).userState(), 0)

    def test_point_to_widget_reveals_exact_lines_without_focus_or_source_change(self):
        source = "# prima\nself.titolo = ttk.Label(self, text='Ciao')\nself.titolo.place(x=20, y=20)\n# dopo\n"
        self.panel.set_source(source)
        self.panel.show_find()
        self.panel.find_field.setFocus()
        APP.processEvents()
        focus = APP.focusWidget()
        changes = []
        self.panel.source_changed.connect(lambda: changes.append(True))
        self.panel.point_to_widget(2, 3)
        self.assertIs(APP.focusWidget(), focus)
        self.assertEqual(self.panel.editor.textCursor().blockNumber(), 1)
        self.assertEqual(self.panel.source(), source)
        self.assertFalse(self.panel.editor.document().isModified())
        self.assertFalse(changes)
        declarations = [selection.cursor.blockNumber() + 1 for selection in self.panel.editor.extraSelections() if selection.format.background().color().name() == PALETTES["dark"]["widget"]]
        self.assertEqual(declarations, [2, 3])

    def test_widget_highlight_preserves_error_across_theme_and_clears_on_edit(self):
        self.panel.set_source("first\nsecond\nthird\nfourth\n")
        self.panel.highlight_error(3)
        self.panel.point_to_widget(2, 3)
        self.assertEqual(self.panel.editor._error_line, 3)
        self.assertEqual(len(self.panel.editor.extraSelections()), 4)
        self.panel.set_theme("light")
        self.assertEqual(self.panel.editor._widget_lines, (2, 3))
        self.assertEqual(self.panel.editor._error_line, 3)
        declarations = [selection.cursor.blockNumber() + 1 for selection in self.panel.editor.extraSelections() if selection.format.background().color().name() == PALETTES["light"]["widget"]]
        self.assertEqual(declarations, [2, 3])
        self.panel.editor.insertPlainText("changed")
        self.assertIsNone(self.panel.editor._widget_lines)
        self.assertIsNone(self.panel.editor._error_line)

    def test_clear_widget_range_leaves_error_and_programmatic_source_clears_stale_range(self):
        self.panel.set_source("first\nsecond\nthird\n")
        self.panel.highlight_error(3)
        self.panel.point_to_widget(2)
        self.assertEqual(self.panel.editor._widget_lines, (2, 2))
        self.panel.point_to_widget(None)
        self.assertIsNone(self.panel.editor._widget_lines)
        self.assertEqual(self.panel.editor._error_line, 3)
        self.assertEqual(len(self.panel.editor.extraSelections()), 2)
        self.panel.point_to_widget(2, 99)
        self.assertEqual(self.panel.editor._widget_lines, (2, self.panel.editor.blockCount()))
        self.panel.set_source("completely different\n")
        self.assertIsNone(self.panel.editor._widget_lines)
        self.assertIsNone(self.panel.editor._error_line)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.runner = ProcessRunner()
        self.outputs = []
        self.results = []
        self.runner.output.connect(lambda text, channel: self.outputs.append((text, channel)))
        self.runner.finished.connect(lambda code, reason: self.results.append((code, reason)))

    def tearDown(self):
        self.runner.shutdown()
        self.runner.deleteLater()
        APP.processEvents()
        self.directory.cleanup()

    def script(self, source: str) -> Path:
        path = Path(self.directory.name) / "prova città.py"
        path.write_text(source, encoding="utf-8")
        return path

    def output(self, channel="stdout"):
        return "".join(text for text, kind in self.outputs if kind == channel)

    def test_success_unicode_and_project_working_directory(self):
        path = self.script("from pathlib import Path\nprint('Città ✓')\nprint(Path.cwd().name)\n")
        self.runner.run(str(path), self.directory.name)
        self.assertTrue(wait_until(lambda: bool(self.results)))
        self.assertEqual(self.results, [(0, "success")])
        self.assertIn("Città ✓", self.output())
        self.assertIn(Path(self.directory.name).name, self.output())

    def test_stdin_and_error_output(self):
        path = self.script("name = input('Nome? ')\nprint('Ciao', name)\nraise ValueError('prova')\n")
        self.runner.run(str(path))
        self.assertTrue(wait_until(lambda: "Nome?" in self.output()))
        self.runner.write_stdin("Daniele")
        self.assertTrue(wait_until(lambda: bool(self.results)))
        self.assertIn("Ciao Daniele", self.output())
        self.assertIn("ValueError: prova", self.output("stderr"))
        self.assertEqual(self.results[0][1], "error")

    def test_stop_is_async_and_allows_rerun(self):
        path = self.script("import time\nprint('ready')\ntime.sleep(60)\n")
        self.runner.run(str(path))
        self.assertTrue(wait_until(lambda: "ready" in self.output()))
        start = time.monotonic()
        self.runner.stop()
        self.assertLess(time.monotonic() - start, 0.5)
        self.assertTrue(wait_until(lambda: bool(self.results)))
        self.assertEqual(self.results[0][1], "stopped")
        self.results.clear()
        path.write_text("print('again')\n", encoding="utf-8")
        self.runner.run(str(path))
        self.assertTrue(wait_until(lambda: bool(self.results)))
        self.assertEqual(self.results, [(0, "success")])

    def test_failed_start_emits_exactly_one_completion(self):
        path = self.script("pass\n")
        fake = Path(self.directory.name) / "not-python.txt"
        fake.write_text("not an executable", encoding="utf-8")
        self.runner.set_interpreter(str(fake))
        self.runner.run(str(path))
        self.assertTrue(wait_until(lambda: bool(self.results)))
        APP.processEvents()
        self.assertEqual(self.results, [(-1, "failed_start")])

    def test_second_run_is_rejected_while_running(self):
        path = self.script("import time\ntime.sleep(60)\n")
        self.runner.run(str(path))
        with self.assertRaises(RuntimeError):
            self.runner.run(str(path))

    def test_pythonw_launch_and_selection_use_python_in_same_virtual_environment(self):
        scripts = Path(self.directory.name) / ".venv" / "Scripts"
        scripts.mkdir(parents=True)
        windowed = scripts / "pythonw.exe"
        console = scripts / "python.exe"
        windowed.touch()
        console.touch()
        with patch("tkstudio.runner.sys.executable", str(windowed)):
            runner = ProcessRunner()
        try:
            self.assertEqual(Path(runner.interpreter), console)
            runner.set_interpreter(str(windowed))
            self.assertEqual(Path(runner.interpreter), console)
        finally:
            runner.deleteLater()
            APP.processEvents()

    def test_stop_fallback_timer_is_cancelled_and_owned_by_runner(self):
        owner = QObject()
        runner = ProcessRunner(owner)
        path = self.script("import time\ntime.sleep(60)\n")
        self.assertIs(runner._stop_timer.parent(), runner)
        runner.run(str(path))
        self.assertTrue(wait_until(lambda: bool(runner.process.processId())))
        runner.stop()
        self.assertTrue(runner._stop_timer.isActive())
        runner.shutdown()
        self.assertFalse(runner._stop_timer.isActive())
        errors = []
        with patch.object(sys, "excepthook", lambda *details: errors.append(details)):
            owner.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            QTest.qWait(1600)
            APP.processEvents()
        self.assertFalse(errors, "A delayed stop callback touched a deleted QProcess")


class ConsoleTests(unittest.TestCase):
    def test_traceback_links_and_bounded_output(self):
        panel = ConsolePanel()
        try:
            panel.append_output('  File "C:/project/main.py", line 12, in method\n', "stderr")
            block = panel.output.document().firstBlock()
            formats = [fragment.fragment().charFormat() for fragment in iter_block(block)]
            self.assertTrue(any(fmt.isAnchor() for fmt in formats))
            activated = []
            panel.location_activated.connect(lambda path, line: activated.append((path, line)))
            url = QUrl.fromLocalFile("C:/project/main.py")
            url.setFragment("12")
            panel._location_clicked(url)
            self.assertEqual(activated[0][1], 12)
            panel.append_output("line\n" * 5500)
            self.assertLessEqual(panel.output.document().blockCount(), 5000)
        finally:
            panel.deleteLater()
            APP.processEvents()


def iter_block(block):
    iterator = block.begin()
    while not iterator.atEnd():
        yield iterator
        iterator += 1


if __name__ == "__main__":
    unittest.main()
