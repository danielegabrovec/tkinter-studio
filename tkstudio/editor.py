"""Small, dependency-free Python editor used by the desktop workbench."""
from __future__ import annotations

import builtins
import html
import keyword
import os
from pathlib import Path
import re
import tempfile

from PyQt6.QtCore import QEvent, QRect, QSize, QStringListModel, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QContextMenuEvent, QFont, QKeySequence, QPainter, QShortcut, QSyntaxHighlighter, QTextCharFormat, QTextCursor, QTextDocument, QTextFormat
from PyQt6.QtWidgets import QCheckBox, QCompleter, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QPlainTextEdit, QPushButton, QSizePolicy, QTabWidget, QTextBrowser, QTextEdit, QToolButton, QToolTip, QVBoxLayout, QWidget


PALETTES = {
    "dark": {"background": "#111922", "text": "#d9e4ee", "muted": "#768c9d", "gutter": "#121d28", "current": "#1b2937", "selection": "#234a66", "keyword": "#c7a3ff", "string": "#a5d6a7", "number": "#ffc287", "comment": "#778f9d", "builtin": "#6fd6e1", "function": "#a5cbff", "error": "#532b34", "widget": "#173e3b"},
    "light": {"background": "#ffffff", "text": "#253448", "muted": "#758498", "gutter": "#f2f5f8", "current": "#f1f6fb", "selection": "#d8eafd", "keyword": "#8042b3", "string": "#286b3b", "number": "#a7561d", "comment": "#687b83", "builtin": "#0d7181", "function": "#185eaa", "error": "#fce1e5", "widget": "#d6f4e9"},
}
BUILTIN_WORDS = frozenset(dir(builtins)) | {"self", "tk", "ttk"}


def qt_position_to_python(source: str, position: int) -> int:
    """Qt offsets are UTF-16 units; static analysis uses Python code points."""
    return len(source.encode("utf-16-le")[:max(0, position) * 2].decode("utf-16-le", errors="ignore"))


def python_position_to_qt(source: str, position: int) -> int:
    return len(source[:max(0, position)].encode("utf-16-le")) // 2


class PythonHighlighter(QSyntaxHighlighter):
    """Python colourisation, including multiline strings, without executing code."""

    def __init__(self, document: QTextDocument, theme: str = "dark"):
        super().__init__(document)
        self.set_theme(theme)

    def set_theme(self, theme: str) -> None:
        palette = PALETTES.get(theme, PALETTES["dark"])
        self.formats: dict[str, QTextCharFormat] = {}
        for key in ("keyword", "string", "number", "comment", "builtin", "function"):
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(palette[key]))
            if key == "keyword":
                fmt.setFontWeight(QFont.Weight.DemiBold)
            if key == "comment":
                fmt.setFontItalic(True)
            self.formats[key] = fmt
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:
        # The scanner gives strings/comments precedence over identifiers.
        state = max(0, self.previousBlockState())
        index = 0
        self.setCurrentBlockState(0)
        while index < len(text):
            if state in (1, 2):
                delimiter = "'''" if state == 1 else '"""'
                end = text.find(delimiter, index)
                if end < 0:
                    self.setFormat(index, len(text) - index, self.formats["string"])
                    self.setCurrentBlockState(state)
                    return
                self.setFormat(index, end + 3 - index, self.formats["string"])
                index = end + 3
                state = 0
                continue
            char = text[index]
            if char == "#":
                self.setFormat(index, len(text) - index, self.formats["comment"])
                break
            if text[index:index + 3] in ("'''", '"""'):
                delimiter = text[index:index + 3]
                state = 1 if delimiter == "'''" else 2
                end = text.find(delimiter, index + 3)
                if end < 0:
                    self.setFormat(index, len(text) - index, self.formats["string"])
                    self.setCurrentBlockState(state)
                    return
                self.setFormat(index, end + 3 - index, self.formats["string"])
                index = end + 3
                state = 0
                continue
            if char in "\"'":
                end = index + 1
                while end < len(text):
                    if text[end] == "\\":
                        end += 2
                    elif text[end] == char:
                        end += 1
                        break
                    else:
                        end += 1
                self.setFormat(index, end - index, self.formats["string"])
                index = end
                continue
            match = re.match(r"\b(?:0[xX][0-9a-fA-F_]+|0[bB][01_]+|\d[\d_]*(?:\.[\d_]+)?(?:[eE][+-]?\d+)?j?)\b", text[index:])
            if char.isdigit() and match:
                self.setFormat(index, len(match[0]), self.formats["number"])
                index += len(match[0])
                continue
            match = re.match(r"[A-Za-z_]\w*", text[index:])
            if match:
                word = match[0]
                if keyword.iskeyword(word) or word in {"match", "case"}:
                    self.setFormat(index, len(word), self.formats["keyword"])
                elif word in BUILTIN_WORDS:
                    self.setFormat(index, len(word), self.formats["builtin"])
                elif re.match(r"\s*\(", text[index + len(word):]):
                    self.setFormat(index, len(word), self.formats["function"])
                index += len(word)
                continue
            index += 1


class LineNumberArea(QWidget):
    def __init__(self, editor: "CodeEditor"):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self.editor.line_number_area_width(), 0)

    def paintEvent(self, event) -> None:
        self.editor.paint_line_numbers(event)

    def mousePressEvent(self, event) -> None:
        block = self.editor.firstVisibleBlock()
        top = self.editor.blockBoundingGeometry(block).translated(self.editor.contentOffset()).top()
        while block.isValid() and top <= event.position().y():
            height = self.editor.blockBoundingRect(block).height()
            if top <= event.position().y() < top + height:
                diagnostic = self.editor.diagnostic_at_line(block.blockNumber() + 1)
                if diagnostic is not None:
                    self.editor.diagnostic_activated.emit(diagnostic)
                    event.accept()
                    return
            top += height
            block = block.next()
        super().mousePressEvent(event)


class CodeEditor(QPlainTextEdit):
    cursor_position_changed = pyqtSignal(int, int)
    integration_requested = pyqtSignal(object, str)
    contextual_help_requested = pyqtSignal(int)
    diagnostic_activated = pyqtSignal(object)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("pythonEditor")
        self.setAccessibleName("Editor del codice Python")
        self.setAccessibleDescription("Scrivi il programma. Tab indenta, Ctrl+Spazio suggerisce parole, Ctrl+F cerca.")
        font = QFont("Cascadia Code", 11)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(font)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)
        self.setCenterOnScroll(True)
        self.setPlaceholderText("# Scrivi qui il tuo codice Python…")
        self.line_number_area = LineNumberArea(self)
        self._error_line: int | None = None
        self._widget_lines: tuple[int, int] | None = None
        self._diagnostics = []
        self._context_menu_source = ""
        self._highlighted_source = self.toPlainText()
        self._theme = "dark"
        self.highlighter = PythonHighlighter(self.document())
        self.blockCountChanged.connect(self._update_gutter_width)
        self.updateRequest.connect(self._update_gutter)
        self.cursorPositionChanged.connect(self._cursor_changed)
        self.textChanged.connect(self._clear_error_on_edit)
        self._update_gutter_width()
        words = sorted(set(keyword.kwlist + dir(builtins) + ["self", "tkinter", "ttk", "Tk", "Frame", "Label", "Button", "Entry", "Text", "Listbox", "Canvas", "Checkbutton", "Radiobutton", "Combobox", "Treeview", "Notebook", "StringVar", "BooleanVar", "IntVar", "mainloop", "configure", "place", "grid", "pack", "bind", "command", "geometry", "title", "destroy", "messagebox"]))
        self._base_completion_words = words
        self.completer = QCompleter(QStringListModel(words, self), self)
        self.completer.setWidget(self)
        self.completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.activated[str].connect(self._insert_completion)
        self.set_theme("dark")

    def set_theme(self, theme: str) -> None:
        self._theme = theme if theme in PALETTES else "dark"
        palette = PALETTES[self._theme]
        self.setStyleSheet(f"QPlainTextEdit {{ background: {palette['background']}; color: {palette['text']}; border: none; selection-background-color: {palette['selection']}; padding: 8px 6px; font-family: 'Cascadia Code', 'Consolas', 'DejaVu Sans Mono', monospace; font-size: 13px; }}")
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)
        self._update_gutter_width()
        self.highlighter.set_theme(self._theme)
        self.line_number_area.update()
        self._highlight_current_line()

    def line_number_area_width(self) -> int:
        return 22 + self.fontMetrics().horizontalAdvance("9") * max(2, len(str(self.blockCount())))

    def _update_gutter_width(self, *_args) -> None:
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _update_gutter(self, rect: QRect, dy: int) -> None:
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(0, rect.y(), self.line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_gutter_width()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        rect = self.contentsRect()
        self.line_number_area.setGeometry(QRect(rect.left(), rect.top(), self.line_number_area_width(), rect.height()))

    def paint_line_numbers(self, event) -> None:
        palette = PALETTES[self._theme]
        painter = QPainter(self.line_number_area)
        painter.setFont(self.font())
        painter.fillRect(event.rect(), QColor(palette["gutter"]))
        block = self.firstVisibleBlock()
        number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        current = self.textCursor().blockNumber()
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                diagnostic = self.diagnostic_at_line(number + 1)
                if diagnostic is not None:
                    color = QColor("#f28f98" if diagnostic.severity == "error" else "#dfaf50")
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(color)
                    painter.drawEllipse(3, top + max(2, self.fontMetrics().height() // 2 - 3), 6, 6)
                painter.setPen(QColor(palette["text"] if number == current else palette["muted"]))
                painter.drawText(0, top, self.line_number_area.width() - 12, self.fontMetrics().height(), Qt.AlignmentFlag.AlignRight, str(number + 1))
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            number += 1

    def _cursor_changed(self) -> None:
        self._highlight_current_line()
        self.line_number_area.update()
        cursor = self.textCursor()
        self.cursor_position_changed.emit(cursor.blockNumber() + 1, cursor.positionInBlock() + 1)

    def _clear_error_on_edit(self) -> None:
        source = self.toPlainText()
        if source == self._highlighted_source:
            return
        self._highlighted_source = source
        self._diagnostics = []
        self.line_number_area.update()
        if self._error_line is not None or self._widget_lines is not None:
            self._error_line = None
            self._widget_lines = None
        self._highlight_current_line()

    def _highlight_current_line(self) -> None:
        selections = []
        current = QTextEdit.ExtraSelection()
        current.format.setBackground(QColor(PALETTES[self._theme]["current"]))
        current.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        current.cursor = self.textCursor()
        current.cursor.clearSelection()
        selections.append(current)
        if self._widget_lines is not None:
            first, last = self._widget_lines
            for line in range(first, last + 1):
                block = self.document().findBlockByNumber(line - 1)
                if not block.isValid():
                    continue
                declaration = QTextEdit.ExtraSelection()
                declaration.format.setBackground(QColor(PALETTES[self._theme]["widget"]))
                declaration.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
                declaration.cursor = QTextCursor(block)
                selections.append(declaration)
        if self._error_line:
            block = self.document().findBlockByNumber(self._error_line - 1)
            if block.isValid():
                error = QTextEdit.ExtraSelection()
                error.format.setBackground(QColor(PALETTES[self._theme]["error"]))
                error.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
                error.cursor = QTextCursor(block)
                selections.append(error)
        for diagnostic in self._diagnostics:
            selection = self._diagnostic_selection(diagnostic)
            if selection is not None:
                selections.append(selection)
        self.setExtraSelections(selections)

    def _diagnostic_selection(self, diagnostic):
        block = self.document().findBlockByNumber(max(0, diagnostic.line - 1))
        if not block.isValid():
            return None
        column = max(0, diagnostic.column - 1)
        start = block.position() + python_position_to_qt(block.text(), min(column, len(block.text())))
        end_line = getattr(diagnostic, "end_line", None) or diagnostic.line
        end_block = self.document().findBlockByNumber(max(diagnostic.line, end_line) - 1)
        if not end_block.isValid():
            end_block = block
        end_column = max(0, (getattr(diagnostic, "end_column", None) or diagnostic.column + 1) - 1)
        end = end_block.position() + python_position_to_qt(end_block.text(), min(end_column, len(end_block.text())))
        if end <= start:
            start = max(block.position(), start - 1)
            end = min(self.document().characterCount() - 1, start + 1)
        selection = QTextEdit.ExtraSelection()
        selection.cursor = QTextCursor(self.document())
        selection.cursor.setPosition(start)
        selection.cursor.setPosition(max(start, end), QTextCursor.MoveMode.KeepAnchor)
        selection.format.setUnderlineStyle(QTextCharFormat.UnderlineStyle.SpellCheckUnderline)
        selection.format.setUnderlineColor(QColor("#ee7b88" if diagnostic.severity == "error" else "#d5a33d"))
        selection.format.setToolTip(diagnostic.message + ("\n" + diagnostic.hint if diagnostic.hint else ""))
        return selection

    def set_diagnostics(self, diagnostics) -> None:
        self._diagnostics = list(diagnostics)
        self.line_number_area.update()
        self._highlight_current_line()

    def diagnostic_at_line(self, line):
        matching = [item for item in self._diagnostics if item.line <= line <= (getattr(item, "end_line", None) or item.line)]
        return next((item for item in matching if item.severity == "error"), matching[0] if matching else None)

    def viewportEvent(self, event):
        if event.type() == QEvent.Type.ToolTip:
            cursor = self.cursorForPosition(event.pos())
            diagnostic = self.diagnostic_at_line(cursor.blockNumber() + 1)
            if diagnostic is not None:
                QToolTip.showText(event.globalPos(), diagnostic.message + ("\n" + diagnostic.hint if diagnostic.hint else ""), self)
                event.accept()
                return True
        return super().viewportEvent(event)

    def set_completion_words(self, words) -> None:
        self.completer.model().setStringList(sorted(set(self._base_completion_words).union(words)))

    def integration_context(self):
        from .integrations import detect_context
        source = self.toPlainText()
        cursor = self.textCursor()
        start = qt_position_to_python(source, cursor.selectionStart()) if cursor.hasSelection() else None
        end = qt_position_to_python(source, cursor.selectionEnd()) if cursor.hasSelection() else None
        return detect_context(source, qt_position_to_python(source, cursor.position()), start, end)

    def build_context_menu(self, *, integrations_only=False):
        from .integrations import IntegrationError, available_actions
        source = self.toPlainText()
        self._context_menu_source = source
        menu = QMenu(self) if integrations_only else self.createStandardContextMenu()
        menu.setToolTipsVisible(True)
        if not integrations_only:
            menu.addSeparator()
        context = None
        try:
            context = self.integration_context()
            actions = available_actions(source, context)
        except (IntegrationError, SyntaxError, ValueError):
            actions = []
        python_file = getattr(self, "_is_python_file", True)
        if python_file:
            label = f"Integra {context.widget_name}" if context is not None and context.widget_name else "Inserisci nel codice"
            submenu = menu if integrations_only else menu.addMenu(label)
            if context is not None:
                title = submenu.addAction(f"{context.widget_kind} · {context.widget_name}")
                title.setEnabled(False)
                submenu.addSeparator()
            for entry in actions:
                action = submenu.addAction(entry.title)
                action.setObjectName("integration:" + entry.id)
                action.setToolTip(entry.description)
                action.setStatusTip(entry.description)
                action.setEnabled(not self.isReadOnly())
                action.triggered.connect(lambda checked=False, c=context, key=entry.id, expected=source: self._request_integration(c, key, expected))
            if not actions:
                info = submenu.addAction("Correggi la sintassi per usare le integrazioni")
                info.setEnabled(False)
            menu.addSeparator()
        help_action = menu.addAction("Aiuto sul codice\tCtrl+I")
        help_action.setObjectName("code-help")
        position = qt_position_to_python(source, self.textCursor().position())
        help_action.triggered.connect(lambda checked=False, pos=position: self.contextual_help_requested.emit(pos))
        return menu

    def _request_integration(self, context, action_id, expected_source):
        self._context_menu_source = expected_source
        self.integration_requested.emit(context, action_id)

    def contextMenuEvent(self, event):
        if event.reason() != QContextMenuEvent.Reason.Keyboard:
            clicked = self.cursorForPosition(event.pos())
            current = self.textCursor()
            if not current.hasSelection() or not current.selectionStart() <= clicked.position() <= current.selectionEnd():
                self.setTextCursor(clicked)
        menu = self.build_context_menu()
        menu.exec(event.globalPos())
        menu.deleteLater()

    def highlight_error(self, line: int | None) -> None:
        self._error_line = line
        self._highlight_current_line()

    def point_to_widget(self, start_line: int | None, end_line: int | None = None) -> None:
        """Reveal a declaration range (1-based, inclusive) without taking focus."""
        if start_line is None or start_line < 1 or start_line > self.blockCount():
            self._widget_lines = None
            self._highlight_current_line()
            return
        last = min(self.blockCount(), max(start_line, end_line if end_line is not None else start_line))
        self._widget_lines = (start_line, last)
        self.setTextCursor(QTextCursor(self.document().findBlockByNumber(start_line - 1)))
        self.centerCursor()
        self._highlight_current_line()

    def go_to_line(self, line: int) -> None:
        block = self.document().findBlockByNumber(max(0, line - 1))
        if block.isValid():
            self.setTextCursor(QTextCursor(block))
            self.centerCursor()
            self.setFocus()

    def _indent_selection(self, dedent: bool = False) -> None:
        cursor = self.textCursor()
        start, end = cursor.selectionStart(), cursor.selectionEnd()
        first = self.document().findBlock(start).blockNumber()
        last_block = self.document().findBlock(end)
        last = last_block.blockNumber()
        if end > start and last_block.position() == end:
            last -= 1
        edit = QTextCursor(self.document())
        edit.beginEditBlock()
        adjusted_start, adjusted_end = start, end
        for number in range(last, first - 1, -1):
            block = self.document().findBlockByNumber(number)
            pos = block.position()
            edit.setPosition(pos)
            if dedent:
                prefix = re.match(r"^(?: {1,4}|\t)", block.text())
                count = len(prefix[0]) if prefix else 0
                if count:
                    edit.setPosition(pos + count, QTextCursor.MoveMode.KeepAnchor)
                    edit.removeSelectedText()
                    adjusted_end -= min(count, max(0, end - pos))
                    if pos < start:
                        adjusted_start -= min(count, start - pos)
            else:
                edit.insertText("    ")
                adjusted_end += 4
                if pos < start or (pos == start and start == end):
                    adjusted_start += 4
        edit.endEditBlock()
        cursor.setPosition(max(0, adjusted_start))
        cursor.setPosition(max(0, adjusted_end), QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(cursor)

    def _insert_completion(self, completion: str) -> None:
        cursor = self.textCursor()
        cursor.select(QTextCursor.SelectionType.WordUnderCursor)
        if completion.startswith("self."):
            source = self.toPlainText()
            start = qt_position_to_python(source, cursor.selectionStart())
            if source[max(0, start - 5):start] == "self.":
                end = cursor.selectionEnd()
                cursor.setPosition(python_position_to_qt(source, start - 5))
                cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(completion)
        self.setTextCursor(cursor)

    def _show_completion(self) -> None:
        cursor = self.textCursor()
        cursor.select(QTextCursor.SelectionType.WordUnderCursor)
        self.completer.setCompletionPrefix(cursor.selectedText())
        rect = self.cursorRect()
        rect.setWidth(max(240, self.completer.popup().sizeHintForColumn(0) + 32))
        self.completer.complete(rect)

    def keyPressEvent(self, event) -> None:
        key = event.key()
        modifiers = event.modifiers()
        if self.completer.popup().isVisible() and key in (Qt.Key.Key_Enter, Qt.Key.Key_Return, Qt.Key.Key_Escape, Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            event.ignore()
            return
        if key == Qt.Key.Key_Space and modifiers & Qt.KeyboardModifier.ControlModifier:
            self._show_completion()
            return
        if key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            if key == Qt.Key.Key_Backtab or modifiers & Qt.KeyboardModifier.ShiftModifier:
                self._indent_selection(True)
            elif self.textCursor().hasSelection():
                self._indent_selection(False)
            else:
                cursor = self.textCursor()
                cursor.insertText(" " * (4 - cursor.positionInBlock() % 4))
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            cursor = self.textCursor()
            before = cursor.block().text()[:cursor.positionInBlock()]
            indent = re.match(r"[ \t]*", before)[0].replace("\t", "    ")
            if before.rstrip().endswith(":"):
                indent += "    "
            cursor.beginEditBlock()
            cursor.insertText("\n" + indent)
            cursor.endEditBlock()
            return
        if key == Qt.Key.Key_Backspace and not self.textCursor().hasSelection():
            cursor = self.textCursor()
            before = cursor.block().text()[:cursor.positionInBlock()]
            if before and before.isspace() and not modifiers:
                count = (cursor.positionInBlock() - 1) % 4 + 1
                cursor.setPosition(cursor.position() - count, QTextCursor.MoveMode.KeepAnchor)
                cursor.removeSelectedText()
                return
        super().keyPressEvent(event)


class EditorPanel(QWidget):
    source_changed = pyqtSignal()
    diagnostics_changed = pyqtSignal(object)
    assistance_message = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.path: str | None = None
        self._theme = "dark"
        self._help_entry = None
        self.diagnostics = []
        self._checked_source = None
        self.editor = CodeEditor(self)
        self.syntax_timer = QTimer(self)
        self.syntax_timer.setSingleShot(True)
        self.syntax_timer.setInterval(450)
        self.syntax_timer.timeout.connect(self.check_syntax)
        self._last_source = self.editor.toPlainText()
        self.editor.textChanged.connect(self._emit_source_change)
        self.find_bar = QWidget(self)
        find_layout = QHBoxLayout(self.find_bar)
        find_layout.setContentsMargins(12, 8, 12, 8)
        find_layout.setSpacing(6)
        self.find_field = QLineEdit()
        self.find_field.setPlaceholderText("Cerca nel codice…")
        self.find_field.setAccessibleName("Testo da cercare")
        self.replace_field = QLineEdit()
        self.replace_field.setPlaceholderText("Sostituisci con…")
        self.replace_field.setAccessibleName("Testo sostitutivo")
        self.case_checkbox = QCheckBox("Aa")
        self.case_checkbox.setToolTip("Distingui maiuscole e minuscole")
        self.case_checkbox.setAccessibleName("Distingui maiuscole e minuscole")
        self.find_status = QLabel("")
        self.find_status.setMinimumWidth(65)
        for widget in (self.find_field, self.replace_field, self.case_checkbox):
            find_layout.addWidget(widget)
        for text, tooltip, callback in (("↑", "Occorrenza precedente (Maiusc+Invio)", lambda: self.find_next(True)), ("↓", "Occorrenza successiva (Invio)", self.find_next), ("Sostituisci", "Sostituisci l'occorrenza selezionata", self.replace_one), ("Tutte", "Sostituisci tutte le occorrenze", self.replace_all), ("Chiudi", "Chiudi ricerca (Esc)", self.hide_find)):
            button = QPushButton(text)
            button.setToolTip(tooltip)
            button.setAccessibleName(tooltip)
            button.clicked.connect(callback)
            find_layout.addWidget(button)
        find_layout.addWidget(self.find_status)
        self.find_bar.hide()
        self.find_field.returnPressed.connect(self.find_next)
        self.replace_field.returnPressed.connect(self.replace_one)
        self.find_field.textChanged.connect(lambda: self.find_status.clear())
        self.assist_bar = QWidget(self)
        self.assist_bar.setObjectName("codeAssistBar")
        assist = QHBoxLayout(self.assist_bar)
        assist.setContentsMargins(8, 3, 8, 3)
        assist.setSpacing(4)
        self.integrate_button = QToolButton()
        self.integrate_button.setText("Integra ▾")
        self.integrate_button.setAccessibleName("Inserisci integrazioni nel codice")
        self.integrate_button.setToolTip("Azioni per il componente selezionato o sotto il cursore")
        self.integrate_button.clicked.connect(self.show_integrations)
        assist.addWidget(self.integrate_button)
        self.code_help_button = QToolButton()
        self.code_help_button.setText("Aiuto")
        self.code_help_button.setAccessibleName("Aiuto sul codice Python e Tkinter")
        self.code_help_button.setToolTip("Spiegazione ed esempio del simbolo sotto il cursore · Ctrl+I")
        self.code_help_button.clicked.connect(lambda: self.show_code_help())
        assist.addWidget(self.code_help_button)
        assist.addStretch()
        self.syntax_button = QToolButton()
        self.syntax_button.setText("Controllo…")
        self.syntax_button.setAccessibleName("Stato sintassi Python")
        self.syntax_button.setToolTip("Controlla sintassi e mostra i problemi · F8")
        self.syntax_button.clicked.connect(lambda: self.check_syntax(reveal=True))
        assist.addWidget(self.syntax_button)
        self.assistance_tabs = QTabWidget()
        self.assistance_tabs.setObjectName("codeAssistance")
        self.assistance_tabs.setDocumentMode(True)
        self.assistance_tabs.setMaximumHeight(240)
        self.assistance_tabs.setMinimumHeight(125)
        self.problems = QListWidget()
        self.problems.setAccessibleName("Problemi di sintassi del file Python")
        self.problems.setWordWrap(True)
        self.problems.itemClicked.connect(self._activate_diagnostic)
        self.problems.itemActivated.connect(self._activate_diagnostic)
        self.help_browser = QTextBrowser()
        self.help_browser.setAccessibleName("Aiuto contestuale Python e Tkinter")
        self.help_browser.setOpenExternalLinks(True)
        self.assistance_tabs.addTab(self.problems, "Problemi")
        self.assistance_tabs.addTab(self.help_browser, "Aiuto codice")
        close_assist = QToolButton()
        close_assist.setText("×")
        close_assist.setToolTip("Chiudi aiuto e problemi")
        close_assist.setAccessibleName("Chiudi pannello aiuto e problemi")
        close_assist.clicked.connect(self.assistance_tabs.hide)
        self.assistance_tabs.setCornerWidget(close_assist)
        self.assistance_tabs.hide()
        self.editor.integration_requested.connect(self._integration_requested)
        self.editor.contextual_help_requested.connect(self.show_code_help)
        self.editor.diagnostic_activated.connect(self.go_to_diagnostic)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.assist_bar)
        layout.addWidget(self.find_bar)
        layout.addWidget(self.editor, 1)
        layout.addWidget(self.assistance_tabs)
        self._shortcuts = []
        for sequence, callback in (("Ctrl+F", self.show_find), ("Ctrl+H", lambda: self.show_find(True)), ("Ctrl+G", self._ask_line), ("Escape", self.hide_find), ("F8", lambda: self.check_syntax(reveal=True)), ("Ctrl+I", lambda: self.show_code_help())):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(callback)
            self._shortcuts.append(shortcut)
        self._schedule_assistance()

    def source(self) -> str:
        return self.editor.toPlainText()

    def _emit_source_change(self) -> None:
        # QSyntaxHighlighter and theme formatting can emit textChanged too.
        # Consumers only need notification when the actual source changed.
        source = self.source()
        if source != self._last_source:
            self._last_source = source
            self._schedule_assistance()
            self.source_changed.emit()

    def set_source(self, text: str, preserve_cursor: bool = False) -> None:
        if text == self.source():
            return
        cursor = self.editor.textCursor()
        position = cursor.position()
        anchor = cursor.anchor()
        scrollbar = self.editor.verticalScrollBar()
        scroll = scrollbar.value()
        blocked = self.editor.blockSignals(True)
        self.editor.setPlainText(text)
        self.editor._clear_error_on_edit()
        if preserve_cursor:
            cursor = self.editor.textCursor()
            maximum = self.editor.document().characterCount() - 1
            cursor.setPosition(min(anchor, maximum))
            cursor.setPosition(min(position, maximum), QTextCursor.MoveMode.KeepAnchor)
            self.editor.setTextCursor(cursor)
            scrollbar.setValue(scroll)
        self.editor.document().setModified(False)
        self._last_source = text
        self.editor.blockSignals(blocked)
        self.editor._update_gutter_width()
        self.editor._highlight_current_line()
        self._schedule_assistance()

    def open_path(self, path: str | Path) -> None:
        target = Path(path).resolve()
        self.set_source(target.read_text(encoding="utf-8-sig"))
        self.path = str(target)
        self._schedule_assistance()

    def save_path(self, path: str | Path | None = None) -> None:
        target_name = path or self.path
        if not target_name:
            raise ValueError("Scegli un file in cui salvare il codice.")
        target = Path(target_name).resolve()
        fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(self.source())
            os.replace(temp_name, target)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        self.path = str(target)
        self.editor.document().setModified(False)
        self._schedule_assistance()

    def set_theme(self, theme: str) -> None:
        self._theme = theme if theme in PALETTES else "dark"
        self.editor.set_theme(theme)
        self._update_assistance_colors()
        if self._help_entry is not None:
            self._render_help_entry(self._help_entry)

    def go_to_line(self, line: int) -> None:
        self.editor.go_to_line(line)

    def highlight_error(self, line: int | None) -> None:
        self.editor.highlight_error(line)

    def point_to_widget(self, start_line: int | None, end_line: int | None = None) -> None:
        self.editor.point_to_widget(start_line, end_line)

    def show_find(self, replace: bool = False) -> None:
        selected = self.editor.textCursor().selectedText()
        if selected and "\u2029" not in selected:
            self.find_field.setText(selected)
        self.replace_field.setVisible(replace)
        self.find_bar.show()
        self.find_field.setFocus()
        self.find_field.selectAll()

    def hide_find(self) -> None:
        if self.find_bar.isVisible():
            self.find_bar.hide()
            self.editor.setFocus()

    def _flags(self, backwards: bool = False):
        flags = QTextDocument.FindFlag(0)
        if self.case_checkbox.isChecked():
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        if backwards:
            flags |= QTextDocument.FindFlag.FindBackward
        return flags

    def find_next(self, backwards: bool = False) -> bool:
        needle = self.find_field.text()
        if not needle:
            return False
        found = self.editor.find(needle, self._flags(backwards))
        if not found:
            cursor = self.editor.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End if backwards else QTextCursor.MoveOperation.Start)
            self.editor.setTextCursor(cursor)
            found = self.editor.find(needle, self._flags(backwards))
        self.find_status.setText("" if found else "Non trovato")
        return found

    def replace_one(self) -> None:
        needle = self.find_field.text()
        if not needle:
            return
        cursor = self.editor.textCursor()
        selected = cursor.selectedText()
        equal = selected == needle if self.case_checkbox.isChecked() else selected.casefold() == needle.casefold()
        if equal:
            cursor.insertText(self.replace_field.text())
            self.editor.setTextCursor(cursor)
        self.find_next()

    def replace_all(self) -> int:
        needle = self.find_field.text()
        if not needle:
            return 0
        document = self.editor.document()
        edit = QTextCursor(document)
        edit.beginEditBlock()
        search = QTextCursor(document)
        count = 0
        while True:
            found = document.find(needle, search, self._flags())
            if found.isNull():
                break
            found.insertText(self.replace_field.text())
            search = found
            count += 1
        edit.endEditBlock()
        self.find_status.setText(f"{count} sostituzioni")
        return count

    def _ask_line(self) -> None:
        line, accepted = QInputDialog.getInt(self, "Vai alla riga", "Numero di riga", self.editor.textCursor().blockNumber() + 1, 1, self.editor.blockCount())
        if accepted:
            self.go_to_line(line)

    def is_python_file(self) -> bool:
        return not self.path or Path(self.path).suffix.lower() in (".py", ".pyw")

    def _schedule_assistance(self):
        self._checked_source = None
        self.diagnostics = []
        self.editor.set_diagnostics([])
        self.problems.clear()
        pending = QListWidgetItem("Controllo in corso…")
        pending.setFlags(Qt.ItemFlag.NoItemFlags)
        self.problems.addItem(pending)
        self.assistance_tabs.setTabText(0, "Problemi (…)")
        python_file = self.is_python_file()
        self.editor._is_python_file = python_file
        self.integrate_button.setEnabled(python_file and not self.editor.isReadOnly())
        self.syntax_button.setText("Controllo…" if python_file else "File di testo")
        self.syntax_button.setToolTip("Controllo in attesa della pausa di scrittura" if python_file else "Il controllo Python è disponibile per i file .py e .pyw")
        self._update_assistance_colors()
        self.syntax_timer.start()
        self.diagnostics_changed.emit([])

    def _update_assistance_colors(self):
        palette = PALETTES.get(self._theme, PALETTES["dark"])
        if self._checked_source is None:
            color = palette["muted"]
        elif any(item.severity == "error" for item in self.diagnostics):
            color = "#f28f98" if self._theme == "dark" else "#a41f32"
        elif self.diagnostics:
            color = "#e0b55d" if self._theme == "dark" else "#876000"
        else:
            color = "#62dfbf" if self._theme == "dark" else "#087e68"
        self.syntax_button.setStyleSheet(f"QToolButton {{ color: {color}; font-size: 11px; padding: 4px 6px; }}")
        self.integrate_button.setStyleSheet("QToolButton { font-size: 11px; padding: 4px 6px; }")
        self.code_help_button.setStyleSheet("QToolButton { font-size: 11px; padding: 4px 6px; }")

    def check_syntax(self, reveal=False):
        """Compile without execution; this never imports or runs the edited file."""
        from .assistance import analyze_source, completion_words
        self.syntax_timer.stop()
        source = self.source()
        python_file = self.is_python_file()
        self.editor._is_python_file = python_file
        self.integrate_button.setEnabled(python_file and not self.editor.isReadOnly())
        if not python_file:
            self.diagnostics = []
            self._checked_source = None
            self.syntax_button.setText("File di testo")
            self.syntax_button.setToolTip("Questo file non viene controllato come Python.")
            self.editor.set_diagnostics([])
            self._update_assistance_colors()
            self.diagnostics_changed.emit([])
            return []
        self.diagnostics = analyze_source(source, self.path or "<editor>")
        self._checked_source = source
        self.editor.set_diagnostics(self.diagnostics)
        self.editor.set_completion_words(completion_words(source))
        self.problems.clear()
        errors = sum(item.severity == "error" for item in self.diagnostics)
        warnings = len(self.diagnostics) - errors
        for diagnostic in self.diagnostics:
            category = "Errore" if diagnostic.severity == "error" else "Avviso"
            detail = f"{category} · riga {diagnostic.line}, col. {diagnostic.column}\n{diagnostic.message}"
            if diagnostic.hint: detail += "\n" + diagnostic.hint
            item = QListWidgetItem(detail)
            item.setData(Qt.ItemDataRole.UserRole, diagnostic)
            item.setToolTip(diagnostic.message + ("\n" + diagnostic.hint if diagnostic.hint else ""))
            self.problems.addItem(item)
        if not self.diagnostics:
            item = QListWidgetItem("Nessun errore di sintassi. Il controllo non esegue il programma.")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.problems.addItem(item)
            self.syntax_button.setText("Sintassi corretta")
        elif errors:
            first_error = next(item for item in self.diagnostics if item.severity == "error")
            self.syntax_button.setText(f"{errors} " + ("errori" if errors > 1 else "errore") + f" · riga {first_error.line}")
        else:
            self.syntax_button.setText(f"{warnings} avvis" + ("i" if warnings > 1 else "o"))
        self.syntax_button.setToolTip("\n\n".join(item.message + ("\n" + item.hint if item.hint else "") for item in self.diagnostics) if self.diagnostics else "Sintassi Python corretta. I nomi, i tipi e gli errori di esecuzione richiedono ulteriori verifiche.")
        self.assistance_tabs.setTabText(0, f"Problemi ({len(self.diagnostics)})")
        self._update_assistance_colors()
        self.diagnostics_changed.emit(list(self.diagnostics))
        if reveal:
            self.assistance_tabs.setCurrentWidget(self.problems)
            self.assistance_tabs.show()
        return list(self.diagnostics)

    def _activate_diagnostic(self, item):
        diagnostic = item.data(Qt.ItemDataRole.UserRole)
        if diagnostic is not None:
            self.go_to_diagnostic(diagnostic)

    def go_to_diagnostic(self, diagnostic):
        block = self.editor.document().findBlockByNumber(max(0, diagnostic.line - 1))
        if not block.isValid():
            return
        position = block.position() + python_position_to_qt(block.text(), max(0, diagnostic.column - 1))
        cursor = QTextCursor(self.editor.document())
        cursor.setPosition(min(position, block.position() + block.length() - 1))
        self.editor.setTextCursor(cursor)
        self.editor.centerCursor()
        self.editor.setFocus()
        self.assistance_message.emit(diagnostic.message + (" — " + diagnostic.hint if diagnostic.hint else ""))

    def show_code_help(self, position=None):
        from .assistance import help_for_symbol
        source = self.source()
        if position is None:
            position = qt_position_to_python(source, self.editor.textCursor().position())
        entry = help_for_symbol(source, position)
        self._help_entry = entry
        self._render_help_entry(entry)
        self.assistance_tabs.setCurrentWidget(self.help_browser)
        self.assistance_tabs.show()
        return entry

    def _render_help_entry(self, entry):
        signature = getattr(entry, "signature", "")
        example = getattr(entry, "example", "")
        url = getattr(entry, "url", "")
        body = f"<h3>{html.escape(entry.title)}</h3>"
        if signature:
            body += f"<pre>{html.escape(signature)}</pre>"
        body += "<p>" + html.escape(entry.body).replace("\n", "<br>") + "</p>"
        if example:
            body += f"<h4>Esempio</h4><pre>{html.escape(example)}</pre>"
        if url:
            body += f'<p><a href="{html.escape(url, quote=True)}">Documentazione ufficiale</a></p>'
        palette = PALETTES[self._theme]
        self.help_browser.setHtml(f"<html><head><style>body {{ color:{palette['text']}; font-family:'Segoe UI'; font-size:12px; }} h3 {{ color:{palette['function']}; }} pre {{ font-family:'Cascadia Code','Consolas',monospace; white-space:pre-wrap; }} a {{ color:{palette['builtin']}; }}</style></head><body>{body}</body></html>")

    def show_integrations(self):
        self.editor._is_python_file = self.is_python_file()
        menu = self.editor.build_context_menu(integrations_only=True)
        menu.exec(self.integrate_button.mapToGlobal(self.integrate_button.rect().bottomLeft()))
        menu.deleteLater()

    def _integration_requested(self, context, action_id):
        return self.apply_integration(action_id, context, expected_source=self.editor._context_menu_source)

    def apply_integration(self, action_id, context=None, *, expected_source=None):
        from .integrations import IntegrationError, apply_action
        if self.editor.isReadOnly() or not self.is_python_file():
            self._show_assistance_message("Questo file non è modificabile come codice Python.")
            return False
        source = self.source()
        if expected_source is not None and source != expected_source:
            self._show_assistance_message("Il codice è cambiato. Riapri il menu per aggiornare le integrazioni.")
            return False
        try:
            if context is None and action_id != "insert_function":
                context = self.editor.integration_context()
            result = apply_action(source, context, action_id)
        except (IntegrationError, SyntaxError, ValueError) as exc:
            self._show_assistance_message(str(exc))
            return False
        if result.source != source:
            cursor = QTextCursor(self.editor.document())
            cursor.beginEditBlock()
            cursor.select(QTextCursor.SelectionType.Document)
            cursor.insertText(result.source)
            cursor.endEditBlock()
            self.editor.setTextCursor(cursor)
        self.editor.go_to_line(result.cursor_line)
        self.check_syntax()
        self.assistance_message.emit(result.message)
        return True

    def _show_assistance_message(self, message):
        self._help_entry = None
        self.help_browser.setPlainText(message)
        self.assistance_tabs.setCurrentWidget(self.help_browser)
        self.assistance_tabs.show()
        self.assistance_message.emit(message)
