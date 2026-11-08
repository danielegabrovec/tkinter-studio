"""Asynchronous execution and a bounded, navigable Python output console."""
from __future__ import annotations

import codecs
import os
from pathlib import Path
import re
import shutil
import signal
import sys

from PyQt6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, QUrl, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor, QTextFormat
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextBrowser, QVBoxLayout, QWidget


class ProcessRunner(QObject):
    output = pyqtSignal(str, str)
    started = pyqtSignal()
    finished = pyqtSignal(int, str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._interpreter = self._console_interpreter(sys.executable)
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        if os.name != "nt" and hasattr(QProcess, "UnixProcessFlag"):
            self.process.setUnixProcessParameters(QProcess.UnixProcessFlag.CreateNewSession)
        self.process.readyReadStandardOutput.connect(self._read_stdout)
        self.process.readyReadStandardError.connect(self._read_stderr)
        self.process.started.connect(self._on_started)
        self.process.finished.connect(self._on_finished)
        self.process.errorOccurred.connect(self._on_error)
        self._stop_requested = False
        self._finished_emitted = True
        self._run_token = 0
        self._decoders = self._new_decoders()
        self._kill_helpers: list[QProcess] = []
        self._stop_token = 0
        self._stop_timer = QTimer(self)
        self._stop_timer.setSingleShot(True)
        self._stop_timer.timeout.connect(self._force_stop_current)

    @staticmethod
    def _new_decoders():
        return {channel: codecs.getincrementaldecoder("utf-8")("replace") for channel in ("stdout", "stderr")}

    @staticmethod
    def _console_interpreter(path: str) -> str:
        """Keep the same environment while giving user programs standard I/O."""
        candidate = Path(path)
        if candidate.name.casefold() == "pythonw.exe":
            console = candidate.with_name("python.exe")
            if console.is_file():
                return str(console)
        return path

    @property
    def interpreter(self) -> str:
        return self._interpreter

    @property
    def running(self) -> bool:
        return self.process.state() != QProcess.ProcessState.NotRunning

    def set_interpreter(self, path: str) -> None:
        if self.running:
            raise RuntimeError("Arresta il programma prima di cambiare interprete.")
        resolved = shutil.which(path) or (str(Path(path).resolve()) if Path(path).is_file() else None)
        if not resolved:
            raise ValueError("L'interprete Python selezionato non esiste.")
        self._interpreter = self._console_interpreter(resolved)

    def run(self, script_path: str, working_directory: str | None = None, args: list[str] | None = None) -> None:
        if self.running:
            raise RuntimeError("Un programma è già in esecuzione. Premi Stop prima di avviarne un altro.")
        target = Path(script_path).resolve()
        if not target.is_file():
            raise FileNotFoundError(f"Il file da eseguire non esiste: {target}")
        directory = Path(working_directory).resolve() if working_directory else target.parent
        if not directory.is_dir():
            raise NotADirectoryError(f"La cartella di esecuzione non esiste: {directory}")
        self._run_token += 1
        self._stop_timer.stop()
        self._stop_requested = False
        self._finished_emitted = False
        self._decoders = self._new_decoders()
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("PYTHONUTF8", "1")
        environment.insert("PYTHONIOENCODING", "utf-8")
        environment.insert("PYTHONUNBUFFERED", "1")
        self.process.setProcessEnvironment(environment)
        self.process.setWorkingDirectory(str(directory))
        self.output.emit(f"▶ {target.name}  ·  {self._interpreter}\n", "system")
        self.process.start(self._interpreter, ["-u", str(target), *(args or [])])

    def _on_started(self) -> None:
        self.started.emit()

    def _read_channel(self, channel: str, data: bytes, final: bool = False) -> None:
        text = self._decoders[channel].decode(data, final=final)
        if text:
            self.output.emit(text, channel)

    def _read_stdout(self) -> None:
        self._read_channel("stdout", bytes(self.process.readAllStandardOutput()))

    def _read_stderr(self) -> None:
        self._read_channel("stderr", bytes(self.process.readAllStandardError()))

    def _on_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self.output.emit(f"Avvio non riuscito: {self.process.errorString()}\n", "stderr")
            self._emit_finished(-1, "failed_start")
        elif error not in (QProcess.ProcessError.Crashed,):
            self.output.emit(f"Errore del processo: {self.process.errorString()}\n", "stderr")

    def _on_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        self._read_stdout()
        self._read_stderr()
        self._read_channel("stdout", b"", final=True)
        self._read_channel("stderr", b"", final=True)
        if self._stop_requested:
            reason, message = "stopped", "■ Programma arrestato.\n"
        elif exit_status == QProcess.ExitStatus.CrashExit:
            reason, message = "crash", f"Il programma si è interrotto (codice {exit_code}).\n"
        elif exit_code:
            reason, message = "error", f"Terminato con codice {exit_code}.\n"
        else:
            reason, message = "success", "✓ Esecuzione completata.\n"
        self.output.emit(message, "system")
        self._emit_finished(exit_code, reason)

    def _emit_finished(self, exit_code: int, reason: str) -> None:
        if self._finished_emitted:
            return
        self._stop_timer.stop()
        self._finished_emitted = True
        self.finished.emit(exit_code, reason)

    def write_stdin(self, text: str) -> None:
        if self.running:
            self.process.write((text.rstrip("\r\n") + "\n").encode("utf-8"))

    def stop(self) -> None:
        if not self.running:
            return
        self._stop_requested = True
        pid = int(self.process.processId())
        token = self._run_token
        if pid:
            if os.name == "nt":
                # The PID belongs to this QProcess, never to a name-based search.
                # /T also closes subprocesses created by the user's program.
                helper = QProcess(self)
                helper.setStandardOutputFile(QProcess.nullDevice())
                helper.setStandardErrorFile(QProcess.nullDevice())
                self._kill_helpers.append(helper)
                helper.finished.connect(lambda _code, _status, task=helper: self._release_helper(task))
                helper.errorOccurred.connect(lambda error, task=helper: self._helper_error(task, error))
                helper.start("taskkill", ["/PID", str(pid), "/T", "/F"])
            else:
                try:
                    os.killpg(pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    self.process.terminate()
        else:
            self.process.kill()
        self._stop_token = token
        self._stop_timer.start(1500)

    def _release_helper(self, helper: QProcess) -> None:
        if helper in self._kill_helpers:
            self._kill_helpers.remove(helper)
            helper.deleteLater()

    def _helper_error(self, helper: QProcess, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self.process.kill()
            self._release_helper(helper)

    def _force_stop(self, token: int) -> None:
        if token == self._run_token and self.running and self._stop_requested:
            if os.name != "nt":
                try:
                    os.killpg(int(self.process.processId()), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
            self.process.kill()

    def _force_stop_current(self) -> None:
        self._force_stop(self._stop_token)

    def shutdown(self) -> None:
        """Use during application close to avoid destroying a live QProcess."""
        self.stop()
        if self.running and not self.process.waitForFinished(2000):
            self.process.kill()
            self.process.waitForFinished(1000)
        for helper in list(self._kill_helpers):
            if helper.state() != QProcess.ProcessState.NotRunning:
                helper.waitForFinished(1000)
        self._stop_timer.stop()


class ConsolePanel(QWidget):
    input_submitted = pyqtSignal(str)
    location_activated = pyqtSignal(str, int)
    CHANNEL_PROPERTY = int(QTextFormat.Property.UserProperty) + 1

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._theme = "dark"
        self._directory = Path.cwd()
        self.output = QTextBrowser()
        self.output.setObjectName("outputConsole")
        self.output.setOpenLinks(False)
        self.output.setOpenExternalLinks(False)
        self.output.setUndoRedoEnabled(False)
        self.output.document().setMaximumBlockCount(5000)
        self.output.setAccessibleName("Console di esecuzione Python")
        font = QFont("Cascadia Code", 10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.output.setFont(font)
        self.output.anchorClicked.connect(self._location_clicked)
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Input per il programma… premi Invio")
        self.input_field.setAccessibleName("Input del programma Python")
        self.send_button = QPushButton("Invia")
        self.send_button.setToolTip("Invia la riga al programma in esecuzione")
        self.send_button.clicked.connect(self._submit_input)
        self.input_field.returnPressed.connect(self._submit_input)
        row = QHBoxLayout()
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(8)
        row.addWidget(self.input_field, 1)
        row.addWidget(self.send_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.output, 1)
        layout.addLayout(row)
        self.set_running(False)
        self.set_theme("dark")

    def set_theme(self, theme: str) -> None:
        self._theme = theme
        dark = theme != "light"
        background, foreground = ("#111922", "#d9e4ee") if dark else ("#ffffff", "#253448")
        self.output.setStyleSheet(f"QTextBrowser {{ border: none; background: {background}; color: {foreground}; padding: 10px 14px; selection-background-color: {'#234a66' if dark else '#d8eafd'}; font-family: 'Cascadia Code', 'Consolas', 'DejaVu Sans Mono', monospace; font-size: 12px; }}")
        # Existing output keeps its semantic channel when the theme changes.
        document = self.output.document()
        block = document.firstBlock()
        recolor = []
        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                fmt = fragment.charFormat()
                color = "#85bdff" if dark else "#185eaa"
                if not fmt.isAnchor():
                    color = self._channel_color(str(fmt.property(self.CHANNEL_PROPERTY) or "stdout"))
                recolor.append((fragment.position(), fragment.length(), color))
                iterator += 1
            block = block.next()
        for position, length, color in recolor:
            cursor = QTextCursor(document)
            cursor.setPosition(position)
            cursor.setPosition(position + length, QTextCursor.MoveMode.KeepAnchor)
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            cursor.mergeCharFormat(fmt)

    def _channel_color(self, channel: str) -> str:
        palette = ({"stdout": "#d9e4ee", "stderr": "#ff9b9b", "system": "#91a7b7", "input": "#6fd6e1"} if self._theme != "light" else {"stdout": "#253448", "stderr": "#ad263a", "system": "#64748b", "input": "#0d7181"})
        return palette.get(channel, palette["stdout"])

    def set_working_directory(self, directory: str | Path) -> None:
        self._directory = Path(directory).resolve()

    def set_running(self, running: bool) -> None:
        self.input_field.setEnabled(running)
        self.send_button.setEnabled(running)

    def _submit_input(self) -> None:
        if not self.input_field.isEnabled():
            return
        text = self.input_field.text()
        self.input_field.clear()
        self.append_output(text + "\n", "input")
        self.input_submitted.emit(text)

    def clear(self) -> None:
        self.output.clear()

    def append_output(self, text: str, channel: str = "stdout") -> None:
        if not text:
            return
        bar = self.output.verticalScrollBar()
        follow = bar.value() >= bar.maximum() - 4
        cursor = self.output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        start_position = cursor.position()
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(self._channel_color(channel)))
        fmt.setProperty(self.CHANNEL_PROPERTY, channel)
        cursor.insertText(text, fmt)
        self._link_tracebacks(max(0, start_position - 1024))
        if follow:
            self.output.setTextCursor(cursor)
            self.output.ensureCursorVisible()

    def _link_tracebacks(self, position: int) -> None:
        document = self.output.document()
        block = document.findBlock(min(position, document.characterCount() - 1))
        while block.isValid():
            for match in re.finditer(r'File "([^"\n]+)", line (\d+)', block.text()):
                filename, line = match.group(1), int(match.group(2))
                if filename.startswith("<"):
                    continue
                path = Path(filename)
                if not path.is_absolute():
                    path = self._directory / path
                url = QUrl.fromLocalFile(str(path.resolve()))
                url.setFragment(str(line))
                fmt = QTextCharFormat()
                fmt.setAnchor(True)
                fmt.setAnchorHref(url.toString())
                fmt.setForeground(QColor("#85bdff" if self._theme != "light" else "#185eaa"))
                fmt.setFontUnderline(True)
                cursor = QTextCursor(document)
                cursor.setPosition(block.position() + match.start(1))
                cursor.setPosition(block.position() + match.end(), QTextCursor.MoveMode.KeepAnchor)
                cursor.mergeCharFormat(fmt)
            block = block.next()

    def _location_clicked(self, url: QUrl) -> None:
        if url.isLocalFile():
            try:
                line = int(url.fragment())
            except ValueError:
                return
            self.location_activated.emit(url.toLocalFile(), max(1, line))
