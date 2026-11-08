"""Finestra principale e coordinamento sicuro fra designer, file e codice."""
from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import weakref
import traceback

from PyQt6.QtCore import Qt, QSize, QTimer, QSettings, QStandardPaths
from PyQt6.QtGui import QAction, QActionGroup, QKeySequence, QFont, QTextCursor, QPalette, QColor
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QLabel, QPushButton, QToolButton, QTabWidget, QFileDialog, QMessageBox,
    QDialog, QFormLayout, QLineEdit, QDialogButtonBox, QComboBox, QTextBrowser,
)

from . import __version__
from .model import UiDocument, default_document, new_document, validate_document, DocumentError
from .codegen import generate_document, GenerationError, rename_widget_references
from .sync import source_to_document, SyncError
from .designer import DesignerPanel
from .editor import EditorPanel
from .runner import ProcessRunner, ConsolePanel
from .panels import FilePanel, PalettePanel, PropertyPanel, HierarchyPanel
from .theme import stylesheet, icon, PALETTES

ROOT = Path(__file__).resolve().parent.parent


def atomic_write(path: Path, text: str):
    """Scrive prima un file vicino al destinatario e sostituisce solo a scrittura conclusa."""
    fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text); stream.flush(); os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp): os.unlink(temp)


def disk_hash(path):
    try: return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError: return None


class NewProjectDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent); self.setWindowTitle("Nuovo progetto Tkinter"); self.setMinimumWidth(490)
        box = QVBoxLayout(self); box.setContentsMargins(24, 22, 24, 22); box.setSpacing(16)
        title = QLabel("Dai forma alla tua prossima idea."); title.setObjectName("sectionHeading"); box.addWidget(title)
        hint = QLabel("Una cartella con il progetto visuale e Python pronto da eseguire."); hint.setObjectName("hint"); hint.setWordWrap(True); box.addWidget(hint)
        form = QFormLayout(); form.setSpacing(12)
        self.name = QLineEdit("La mia app"); form.addRow("Nome", self.name)
        self.location = QLineEdit(str(ROOT / "progetti")); row = QHBoxLayout(); row.addWidget(self.location)
        button = QPushButton("Sfoglia…"); button.clicked.connect(self.browse); row.addWidget(button); form.addRow("Cartella", row)
        self.template = QComboBox(); self.template.addItem("Finestra vuota", "empty"); self.template.addItem("Esempio interattivo: saluto", "demo"); form.addRow("Punto di partenza", self.template)
        box.addLayout(form)
        self.error = QLabel(); self.error.setWordWrap(True); self.error.setObjectName("hint"); box.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Crea progetto"); buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Annulla")
        buttons.accepted.connect(self.validate); buttons.rejected.connect(self.reject); box.addWidget(buttons)

    def browse(self):
        path = QFileDialog.getExistingDirectory(self, "Cartella che conterrà il progetto", self.location.text())
        if path: self.location.setText(path)

    def validate(self):
        name = self.name.text().strip()
        if not name or name in (".", "..") or any(c in name for c in '\\/:*?"<>|') or name.endswith((".", " ")):
            self.error.setText("Scegli un nome valido per la cartella del progetto."); return
        self.target = Path(self.location.text()).expanduser().resolve() / name
        if self.target.exists() and any(self.target.iterdir()):
            self.error.setText("Questa cartella contiene già dei file. Scegli un altro nome."); return
        self.accept()


class MainWindow(QMainWindow):
    def __init__(self, project=None, *, restore_session=True):
        super().__init__()
        self.settings = QSettings("TkinterStudio", "TkinterStudio")
        self.theme = str(self.settings.value("theme", "dark"))
        if self.theme not in PALETTES: self.theme = "dark"
        self._updating = False; self._sync_ok = True; self._sync_pending = False; self._refreshing_model = False
        self._history = []; self._history_index = -1; self._selected_id = None
        self.project_path: Path | None = None; self.project_dir = ROOT / "esempi" / "Benvenuto"
        self.source_path: Path | None = None; self._saved_source = ""; self._saved_document = None
        self._disk_versions = {}; self._run_path = None; self._run_editor = None; self._run_contexts = {}
        self.doc = default_document()
        self.runner = ProcessRunner(self)
        interpreter = self.settings.value("interpreter", "")
        if interpreter and Path(str(interpreter)).is_file(): self.runner.set_interpreter(str(interpreter))
        self.setWindowTitle("Tkinter Studio"); self.resize(1560, 970); self.setMinimumSize(1120, 720)
        self.setWindowIcon(icon("app", "#62dfbf", 48))
        self.sync_timer = QTimer(self); self.sync_timer.setSingleShot(True); self.sync_timer.setInterval(650); self.sync_timer.timeout.connect(self.sync_from_code)
        self.selection_reveal_timer = QTimer(self); self.selection_reveal_timer.setSingleShot(True); self.selection_reveal_timer.timeout.connect(self._reveal_selected_source)
        self._build_ui(); self._menus(); self._connect(); self.apply_theme(self.theme)
        self.recovery_timer = QTimer(self); self.recovery_timer.setInterval(30000); self.recovery_timer.timeout.connect(self._write_recovery); self.recovery_timer.start()
        target = Path(project) if project else None
        if target is None and restore_session:
            recent = self.settings.value("last_project", "")
            if recent and Path(str(recent)).is_file(): target = Path(str(recent))
        if target is None: target = ROOT / "esempi" / "Benvenuto" / "progetto.tkui"
        if target.exists():
            try: self.load_project(target)
            except (OSError, ValueError) as exc:
                self._load_unsaved_demo(); self.console.append_output(f"Impossibile aprire il progetto: {exc}\n", "stderr")
        else: self._load_unsaved_demo()
        if restore_session:
            geometry = self.settings.value("geometry")
            if geometry: self.restoreGeometry(geometry)
            QTimer.singleShot(300, self._offer_recovery)
        QTimer.singleShot(100, self.designer.fit)

    def _build_ui(self):
        central = QWidget(); central.setObjectName("workspace"); outer = QVBoxLayout(central); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0); self.setCentralWidget(central)
        header = QWidget(); header.setObjectName("header"); row = QHBoxLayout(header); row.setContentsMargins(18, 10, 18, 10); row.setSpacing(12)
        mark = QLabel(); mark.setPixmap(icon("app", "#62dfbf", 32).pixmap(32, 32)); row.addWidget(mark)
        brand = QLabel("Tkinter Studio"); brand.setObjectName("brand"); row.addWidget(brand); row.addSpacing(20)
        self.project_label = QLabel(); self.project_label.setObjectName("projectLabel"); row.addWidget(self.project_label); row.addStretch()
        self.new_button = QPushButton("Nuovo"); self.new_button.setIcon(icon("plus")); self.new_button.setToolTip("Nuovo progetto · Ctrl+N"); row.addWidget(self.new_button)
        self.open_button = QPushButton("Apri"); self.open_button.setIcon(icon("folder")); self.open_button.setToolTip("Apri progetto · Ctrl+O"); row.addWidget(self.open_button)
        self.save_button = QPushButton("Salva"); self.save_button.setIcon(icon("save")); self.save_button.setToolTip("Salva progetto e codice · Ctrl+S"); row.addWidget(self.save_button)
        self.theme_button = QToolButton(); self.theme_button.setIcon(icon("sun")); self.theme_button.setAccessibleName("Cambia tema chiaro o scuro"); self.theme_button.setToolTip("Cambia tema chiaro / scuro"); row.addWidget(self.theme_button)
        row.addSpacing(8)
        self.play_button = QPushButton("Play"); self.play_button.setObjectName("primaryButton"); self.play_button.setIcon(icon("play", "#102b25")); self.play_button.setToolTip("Prova il codice della scheda attiva · F5"); row.addWidget(self.play_button)
        self.stop_button = QToolButton(); self.stop_button.setIcon(icon("stop", "#ffa6ac")); self.stop_button.setToolTip("Ferma il programma · Maiusc+F5"); self.stop_button.setAccessibleName("Ferma programma"); self.stop_button.setEnabled(False); row.addWidget(self.stop_button); outer.addWidget(header)
        self.horizontal = QSplitter(Qt.Orientation.Horizontal); self.horizontal.setChildrenCollapsible(False); outer.addWidget(self.horizontal, 1)
        self.left = QSplitter(Qt.Orientation.Vertical); self.left.setChildrenCollapsible(False); self.left.setMinimumWidth(205)
        self.files = FilePanel(); self.palette = PalettePanel(); self.left.addWidget(self.files); self.left.addWidget(self.palette); self.left.setSizes([260, 540]); self.horizontal.addWidget(self.left)
        center = QWidget(); box = QVBoxLayout(center); box.setContentsMargins(0, 0, 0, 0); box.setSpacing(0)
        bar = QWidget(); bar.setObjectName("editorToolbar"); modes = QHBoxLayout(bar); modes.setContentsMargins(14, 7, 14, 7); modes.setSpacing(4)
        caption = QLabel("CREA. SCRIVI. PROVA."); caption.setObjectName("sectionTitle"); modes.addWidget(caption); modes.addStretch()
        self.mode_group = QActionGroup(self); self.mode_buttons = {}
        for key, label, image, tip in (("design", "Designer", "designer", "Solo designer · Ctrl+1"), ("split", "Affiancati", "split", "Designer e codice · Ctrl+2"), ("code", "Codice", "code", "Solo codice · Ctrl+3")):
            button = QToolButton(); button.setText(label); button.setIcon(icon(image)); button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon); button.setCheckable(True); button.setToolTip(tip); button.clicked.connect(lambda checked=False, k=key: self.set_view(k)); modes.addWidget(button); self.mode_buttons[key] = button
        modes.addStretch(); self.sync_badge = QLabel("Sincronizzato"); self.sync_badge.setObjectName("syncBadge"); modes.addWidget(self.sync_badge); box.addWidget(bar)
        self.notice = QLabel(); self.notice.setWordWrap(True); self.notice.setObjectName("syncNotice"); self.notice.hide(); box.addWidget(self.notice)
        self.vertical = QSplitter(Qt.Orientation.Vertical); self.vertical.setChildrenCollapsible(False)
        self.edit_split = QSplitter(Qt.Orientation.Horizontal); self.edit_split.setChildrenCollapsible(False)
        self.designer = DesignerPanel(); self.designer.setMinimumWidth(300); self.edit_split.addWidget(self.designer)
        self.editors = QTabWidget(); self.editors.setDocumentMode(True); self.editors.setTabsClosable(True); self.editors.setMovable(False); self.editors.setMinimumWidth(290)
        self.main_editor = EditorPanel(); self.editors.addTab(self.main_editor, icon("code"), "app.py"); self.editors.tabBar().setTabButton(0, self.editors.tabBar().ButtonPosition.RightSide, None)
        self.edit_split.addWidget(self.editors); self.edit_split.setSizes([560, 440]); self.vertical.addWidget(self.edit_split)
        console_wrap = QWidget(); console_box = QVBoxLayout(console_wrap); console_box.setContentsMargins(0, 0, 0, 0); console_box.setSpacing(0)
        bar = QWidget(); bar.setObjectName("editorToolbar"); console_row = QHBoxLayout(bar); console_row.setContentsMargins(14, 4, 8, 4)
        label = QLabel("CONSOLE"); label.setObjectName("sectionTitle"); console_row.addWidget(label)
        self.run_label = QLabel("Pronto per la tua prima esecuzione"); self.run_label.setObjectName("hint"); console_row.addSpacing(12); console_row.addWidget(self.run_label); console_row.addStretch()
        self.clear_console = QPushButton("Pulisci"); self.clear_console.setToolTip("Pulisci l’output della console"); console_row.addWidget(self.clear_console); console_box.addWidget(bar)
        self.console = ConsolePanel(); self.console.setMinimumHeight(120); console_box.addWidget(self.console); self.vertical.addWidget(console_wrap); self.vertical.setSizes([640, 200]); box.addWidget(self.vertical, 1)
        self.horizontal.addWidget(center)
        self.right_tabs = QTabWidget(); self.right_tabs.setMinimumWidth(260); self.right_tabs.setMaximumWidth(390); self.right_tabs.setDocumentMode(True)
        self.properties = PropertyPanel(); self.hierarchy = HierarchyPanel(); self.right_tabs.addTab(self.properties, "Proprietà"); self.right_tabs.addTab(self.hierarchy, "Struttura"); self.horizontal.addWidget(self.right_tabs); self.horizontal.setSizes([235, 1040, 285])
        self.status = QLabel("Pronto"); self.status.setContentsMargins(8, 0, 0, 0); self.statusBar().addWidget(self.status, 1)
        self.cursor_status = QLabel("Ln 1, Col 1"); self.statusBar().addPermanentWidget(self.cursor_status)
        self.python_status = QLabel(f"Python {sys.version_info.major}.{sys.version_info.minor}  ·  UTF-8  ·  Tkinter"); self.python_status.setContentsMargins(14, 0, 12, 0); self.statusBar().addPermanentWidget(self.python_status)
        self.set_view("design")

    def _action(self, menu, text, callback, shortcut=None, image=None):
        action = QAction(icon(image) if image else icon("file"), text, self)
        if shortcut: action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(callback); menu.addAction(action); return action

    def _menus(self):
        file_menu = self.menuBar().addMenu("File")
        self._action(file_menu, "Nuovo progetto…", self.new_project, "Ctrl+N", "plus")
        self._action(file_menu, "Apri progetto…", self.open_project, "Ctrl+O", "folder")
        self._action(file_menu, "Apri cartella…", self.open_folder)
        self._action(file_menu, "Apri file nell’editor…", self.choose_file, "Ctrl+P", "code")
        self._action(file_menu, "Ricarica file dal disco", self.reload_active)
        file_menu.addSeparator()
        self._action(file_menu, "Salva", self.save_active, "Ctrl+S", "save")
        self._action(file_menu, "Salva progetto con nome…", self.save_project_as, "Ctrl+Shift+S", "save")
        self._action(file_menu, "Esporta codice Python…", self.export_python, "Ctrl+Shift+E", "code")
        file_menu.addSeparator(); self._action(file_menu, "Esci", self.close, "Alt+F4")
        edit = self.menuBar().addMenu("Modifica")
        self.undo_action = self._action(edit, "Annulla", self.undo, "Ctrl+Z", "undo")
        self.redo_action = self._action(edit, "Ripeti", self.redo, "Ctrl+Shift+Z", "redo")
        edit.addSeparator(); self._action(edit, "Duplica componente", self.designer.duplicate_selected, None, "plus")
        self._action(edit, "Elimina componente", self.designer.delete_selected, None, "trash")
        edit.addSeparator(); self._action(edit, "Cerca nel codice…", lambda: self._show_find(False))
        self._action(edit, "Sostituisci nel codice…", lambda: self._show_find(True))
        edit.addSeparator(); self._action(edit, "Integrazioni del componente…", self._show_integrations, None, "plus")
        view = self.menuBar().addMenu("Vista")
        self._action(view, "Designer", lambda: self.set_view("design"), "Ctrl+1", "designer")
        self._action(view, "Designer e codice affiancati", lambda: self.set_view("split"), "Ctrl+2", "split")
        self._action(view, "Codice", lambda: self.set_view("code"), "Ctrl+3", "code")
        view.addSeparator(); self._action(view, "Adatta il canvas", self.designer.fit, "Ctrl+0")
        self._action(view, "Dimensioni reali (100%)", self.designer.actual_size)
        self._action(view, "Tema chiaro / scuro", self.toggle_theme)
        self._action(view, "Ripristina disposizione pannelli", self.reset_layout)
        run = self.menuBar().addMenu("Esegui")
        self.run_action = self._action(run, "Play — esegui scheda attiva", self.play, "F5", "play")
        self.stop_action = self._action(run, "Ferma programma", self.runner.stop, "Shift+F5", "stop"); self.stop_action.setEnabled(False)
        self._action(run, "Seleziona interprete Python…", self.choose_interpreter)
        self._action(run, "Controlla sintassi del codice", self._check_code, None, "check")
        help_menu = self.menuBar().addMenu("Aiuto")
        self._action(help_menu, "Guida rapida e scorciatoie", self.show_help, "F1", "info")
        self._action(help_menu, "Aiuto sul codice selezionato", self._show_code_help, None, "info")
        self._action(help_menu, "Apri esempio interattivo", self.open_demo)
        self._action(help_menu, "Informazioni", lambda: QMessageBox.about(self, "Tkinter Studio", f"<h2>Tkinter Studio {__version__}</h2><p>Disegna interfacce. Scrivi Python. Prova le tue idee.</p><p>IDE desktop in PyQt6, programmi generati in Tkinter e ttk.</p><p>Il designer è un’anteprima schematica. Play esegue i controlli Tkinter reali.</p>"))

    def _connect(self):
        self.new_button.clicked.connect(self.new_project); self.open_button.clicked.connect(self.open_project); self.save_button.clicked.connect(self.save_active)
        self.theme_button.clicked.connect(self.toggle_theme); self.play_button.clicked.connect(self.play); self.stop_button.clicked.connect(self.runner.stop)
        self.files.folder_requested.connect(self.open_folder); self.files.file_opened.connect(self.open_file)
        self.palette.add_requested.connect(self.designer.add_widget)
        self.designer.document_changed.connect(self.visual_changed); self.designer.selection_changed.connect(self.selection_changed); self.designer.widget_activated.connect(self.open_callback)
        self.hierarchy.selected.connect(self.designer.select_widget); self.properties.changed.connect(self.property_changed); self.properties.callback_requested.connect(self.open_callback)
        self.main_editor.source_changed.connect(lambda: self.editor_changed(self.main_editor)); self.main_editor.editor.cursor_position_changed.connect(self._cursor_changed)
        self.main_editor.assistance_message.connect(self.status.setText)
        self.editors.tabCloseRequested.connect(self.close_editor); self.editors.currentChanged.connect(self._tab_changed)
        self.runner.output.connect(self.console.append_output); self.runner.started.connect(self._run_started); self.runner.finished.connect(self._run_finished)
        self.console.input_submitted.connect(self.runner.write_stdin); self.console.location_activated.connect(self.open_location); self.clear_console.clicked.connect(self.console.clear)

    def current_editor(self):
        return self.main_editor if self.editors.isHidden() else self.editors.currentWidget()

    def set_view(self, mode):
        if hasattr(self, "selection_reveal_timer"): self.selection_reveal_timer.stop()
        self.view_mode = mode
        self.designer.setVisible(mode != "code"); self.editors.setVisible(mode != "design")
        for key, button in self.mode_buttons.items(): button.setChecked(key == mode)
        if mode != "code": QTimer.singleShot(30, self.designer.fit)
        if mode == "code": self.editors.currentWidget().editor.setFocus()

    def reset_layout(self):
        self.horizontal.setSizes([235, max(600, self.width() - 520), 285]); self.left.setSizes([260, 540]); self.vertical.setSizes([640, 200]); self.edit_split.setSizes([560, 440]); self.set_view("design")

    def apply_theme(self, theme):
        updating = self._updating; self._updating = True
        self.theme = theme; app = QApplication.instance(); c = PALETTES[theme]
        palette = QPalette()
        for role, value in ((QPalette.ColorRole.Window, c["panel"]), (QPalette.ColorRole.WindowText, c["text"]), (QPalette.ColorRole.Base, c["field"]), (QPalette.ColorRole.AlternateBase, c["raised"]), (QPalette.ColorRole.Text, c["text"]), (QPalette.ColorRole.Button, c["raised"]), (QPalette.ColorRole.ButtonText, c["text"]), (QPalette.ColorRole.Highlight, c["selection"]), (QPalette.ColorRole.HighlightedText, c["text"]), (QPalette.ColorRole.ToolTipBase, c["raised"]), (QPalette.ColorRole.ToolTipText, c["text"])): palette.setColor(role, QColor(value))
        app.setPalette(palette); app.setStyleSheet(stylesheet(theme))
        self.designer.set_theme(theme); self.palette.set_theme(theme); self.console.set_theme(theme)
        for index in range(self.editors.count()): self.editors.widget(index).set_theme(theme)
        self.settings.setValue("theme", theme)
        self._updating = updating

    def toggle_theme(self): self.apply_theme("light" if self.theme == "dark" else "dark")

    def _load_unsaved_demo(self):
        self.project_path = None; self.source_path = None; self.doc = default_document(); self.project_dir = ROOT / "esempi" / "Benvenuto"
        self._set_source(generate_document(self.doc)); self._saved_source = ""; self._saved_document = None
        self._refresh_model(); self._reset_history(); self.files.set_root(self.project_dir if self.project_dir.exists() else ROOT); self.update_title()

    def _set_source(self, source):
        self._updating = True
        try: self.main_editor.set_source(source, preserve_cursor=True)
        finally: self._updating = False

    def _refresh_model(self, selected_id=None):
        self._refreshing_model = True
        try:
            self.designer.set_document(self.doc)
            if selected_id: self.designer.select_widget(selected_id)
            self.properties.show_document(self.doc, selected_id); self.hierarchy.populate(self.doc, selected_id)
        finally: self._refreshing_model = False

    def selection_changed(self, node_id):
        self._selected_id = node_id; self.properties.show_document(self.doc, node_id); self.hierarchy.populate(self.doc, node_id)
        if self._updating or self._refreshing_model: return
        if node_id:
            self.point_to_widget_source(node_id)
        else:
            self.selection_reveal_timer.stop(); self.main_editor.point_to_widget(None)

    def point_to_widget_source(self, node_id, reveal=True):
        """Selezione visuale → definizione Python, senza sottrarre il focus al canvas."""
        node = self.doc.find(node_id)
        if node is None: return
        try:
            tree = ast.parse(self.main_editor.source())
            app_class = next(item for item in tree.body if isinstance(item, ast.ClassDef) and item.name == "App")
            build_ui = next(item for item in app_class.body if isinstance(item, ast.FunctionDef) and item.name == "build_ui")
            declaration = next(item for item in build_ui.body if isinstance(item, ast.Assign) and any(isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self" and target.attr == node.name for target in item.targets))
            end_line = declaration.end_lineno
            for item in build_ui.body:
                if isinstance(item, ast.Expr) and isinstance(item.value, ast.Call):
                    func = item.value.func
                    if isinstance(func, ast.Attribute) and func.attr == "place" and isinstance(func.value, ast.Attribute) and func.value.attr == node.name and isinstance(func.value.value, ast.Name) and func.value.value.id == "self":
                        end_line = max(end_line, item.end_lineno)
            self.main_editor.point_to_widget(declaration.lineno, end_line)
            self.editors.setCurrentWidget(self.main_editor)
            self.status.setText(f"{node.name} → {self.source_path.name if self.source_path else 'app.py'} · riga {declaration.lineno}")
            if reveal and self.view_mode == "design":
                # Aprire il pannello durante la pressione sposterebbe il canvas sotto
                # al puntatore: attendere anche l'intervallo del doppio clic.
                delay = QApplication.doubleClickInterval() + 60 if QApplication.mouseButtons() != Qt.MouseButton.NoButton else 0
                self.selection_reveal_timer.start(delay)
        except (SyntaxError, StopIteration, AttributeError): return

    def _reveal_selected_source(self):
        if QApplication.mouseButtons() != Qt.MouseButton.NoButton:
            self.selection_reveal_timer.start(40); return
        if self._selected_id and self.view_mode == "design": self.set_view("split")

    def _set_sync(self, valid, message=""):
        self._sync_ok = valid; self._sync_pending = False; self.designer.set_editable(valid); self.properties.setEnabled(valid); self.palette.setEnabled(valid)
        self.sync_badge.setText("Sincronizzato" if valid else "Solo codice")
        self.notice.setText(message + "  Il codice resta modificabile ed eseguibile. Il designer riprende quando build_ui torna compatibile.")
        self.notice.setVisible(not valid); self.sync_badge.setToolTip(message if message else "Designer e codice descrivono la stessa interfaccia.")

    def editor_changed(self, editor):
        if self._updating: return
        if editor is self.main_editor:
            self._sync_pending = True; self.designer.set_editable(False); self.properties.setEnabled(False); self.palette.setEnabled(False)
            self.sync_badge.setText("Aggiornamento…"); self.sync_timer.start()
        self.update_title()

    def sync_from_code(self):
        self.sync_timer.stop()
        try:
            document = source_to_document(self.main_editor.source(), self.doc)
            self.doc = document; self._set_sync(True); self._refresh_model(self._selected_id); self._record_history()
            self.status.setText("Designer aggiornato dal codice")
        except (SyncError, DocumentError) as exc:
            self._set_sync(False, str(exc)); self.status.setText("Modifica il codice per ripristinare la sincronizzazione")
        self.update_title(); return self._sync_ok

    def visual_changed(self):
        if self._updating: return
        try:
            source = self.main_editor.source()
            if self._history_index >= 0:
                previous_names = {node["name"] for node in self._history[self._history_index][0]["widgets"]}
                current_names = {node.name for node in self.doc.widgets}
                if previous_names - current_names:
                    from .integrations import reconcile_integrations
                    source = reconcile_integrations(source, current_names)
            source = generate_document(self.doc, source)
            self._set_source(source); self._set_sync(True); self._record_history()
            self.properties.show_document(self.doc, self._selected_id); self.hierarchy.populate(self.doc, self._selected_id)
            if self._selected_id: self.point_to_widget_source(self._selected_id, reveal=False)
            self.status.setText("Codice aggiornato dal designer"); self.update_title()
        except (ValueError, TypeError) as exc:
            if self._history_index >= 0:
                snapshot = self._history[self._history_index]; self.doc = UiDocument.from_dict(snapshot[0]); self._refresh_model(self._selected_id)
            self._set_sync(False, str(exc))

    def property_changed(self, key, value):
        if not self._sync_ok or self._sync_pending: return
        previous = self.doc.clone(); node = self.doc.find(self._selected_id); previous_name = node.name if node else None
        try:
            if key.startswith("properties.") and node: node.properties[key[11:]] = value
            elif node: setattr(node, key, value)
            else: setattr(self.doc, key, value)
            validate_document(self.doc)
            if key == "name" and previous_name and value != previous_name:
                self._set_source(rename_widget_references(self.main_editor.source(), previous_name, value))
            self.designer.refresh(self._selected_id); self.visual_changed()
        except (ValueError, TypeError) as exc:
            self.doc = previous; self._refresh_model(self._selected_id); self.status.setText(str(exc)); QMessageBox.warning(self, "Proprietà non valida", str(exc))

    def open_callback(self, node_id):
        if self._sync_pending and not self.sync_from_code(): return
        if not self._sync_ok: return
        node = self.doc.find(node_id)
        if not node: return
        if "command" not in node.properties and node.kind not in ("ttk.Button", "ttk.Checkbutton", "ttk.Radiobutton", "ttk.Spinbox", "ttk.Scale"):
            self.set_view("split"); self.editors.setCurrentWidget(self.main_editor)
            for line, text in enumerate(self.main_editor.source().splitlines(), 1):
                if f"self.{node.name} =" in text: self.main_editor.go_to_line(line); break
            return
        if not node.properties.get("command"):
            node.properties["command"] = "on_" + node.name; self.visual_changed()
        command = node.properties["command"]; self.set_view("split"); self.editors.setCurrentWidget(self.main_editor)
        for line, text in enumerate(self.main_editor.source().splitlines(), 1):
            if text.strip().startswith(f"def {command}("):
                self.main_editor.go_to_line(line + 1); break

    def _record_history(self):
        state = (self.doc.to_dict(), self.main_editor.source())
        if self._history_index >= 0 and self._history[self._history_index] == state: return
        self._history = self._history[:self._history_index + 1]; self._history.append(state)
        if len(self._history) > 100: self._history.pop(0)
        self._history_index = len(self._history) - 1

    def _reset_history(self):
        self._history = []; self._history_index = -1; self._record_history()

    def _restore_history(self, index):
        if not 0 <= index < len(self._history): return
        self.sync_timer.stop(); state = self._history[index]; self._history_index = index
        self.doc = UiDocument.from_dict(state[0]); self._set_source(state[1])
        try:
            self.doc = source_to_document(state[1], self.doc); self._set_sync(True)
        except SyncError as exc: self._set_sync(False, str(exc))
        self._refresh_model(self._selected_id); self.update_title()

    def undo(self):
        editor = self.current_editor()
        if editor and editor.editor.hasFocus():
            if editor.editor.document().isUndoAvailable(): editor.editor.undo()
            elif editor is self.main_editor: self._restore_history(self._history_index - 1)
        else: self._restore_history(self._history_index - 1)

    def redo(self):
        editor = self.current_editor()
        if editor and editor.editor.hasFocus() and editor.editor.document().isRedoAvailable(): editor.editor.redo()
        else: self._restore_history(self._history_index + 1)

    def _main_dirty(self):
        return self.main_editor.source() != self._saved_source or self.doc.to_dict() != self._saved_document

    def update_title(self):
        dirty = self._main_dirty(); name = self.project_dir.name if self.project_path else "Progetto senza nome"
        self.project_label.setText(name + ("  ·  modificato" if dirty else "  ·  progetto Tkinter")); self.project_label.setToolTip(str(self.project_dir))
        self.setWindowTitle(("● " if dirty else "") + name + " — Tkinter Studio")
        for index in range(self.editors.count()):
            editor = self.editors.widget(index); label = getattr(editor, "display_name", None) or (Path(editor.path).name if editor.path else "app.py")
            changed = dirty if editor is self.main_editor else editor.editor.document().isModified()
            self.editors.setTabText(index, label + (" ●" if changed else ""))

    def _allow_switch(self):
        if self.runner.running:
            QMessageBox.information(self, "Programma in esecuzione", "Ferma il programma con Stop prima di cambiare progetto."); return False
        if not self._main_dirty(): return True
        answer = QMessageBox.question(self, "Modifiche non salvate", "Salvare le modifiche del progetto prima di continuare?", QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Save)
        if answer == QMessageBox.StandardButton.Cancel: return False
        if answer == QMessageBox.StandardButton.Save: return self.save_project()
        return True

    def new_project(self):
        dialog = NewProjectDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted: return
        if not self._allow_switch(): return
        try:
            doc = default_document() if dialog.template.currentData() == "demo" else new_document(); doc.title = dialog.name.text().strip()
            source = generate_document(doc); target = dialog.target; target.mkdir(parents=True, exist_ok=True)
            atomic_write(target / "app.py", source); data = doc.to_dict(); data["python_file"] = "app.py"
            atomic_write(target / "progetto.tkui", json.dumps(data, ensure_ascii=False, indent=2) + "\n"); self.load_project(target / "progetto.tkui")
            self.status.setText("Progetto creato. Trascina il primo componente.")
        except (OSError, ValueError) as exc: self._error("Impossibile creare il progetto", exc)

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "Apri progetto Tkinter Studio", str(self.project_dir), "Progetti Tkinter Studio (*.tkui)")
        if path and self._allow_switch():
            try: self.load_project(Path(path))
            except (OSError, ValueError) as exc: self._error("Impossibile aprire il progetto", exc)

    def open_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Apri cartella progetto", str(self.project_dir))
        if not folder: return
        paths = sorted(Path(folder).glob("*.tkui"))
        if len(paths) == 1:
            if self._allow_switch():
                try: self.load_project(paths[0])
                except (OSError, ValueError) as exc: self._error("Impossibile aprire il progetto", exc)
        elif len(paths) > 1:
            path, _ = QFileDialog.getOpenFileName(self, "Scegli il progetto da aprire", folder, "Progetti (*.tkui)")
            if path and self._allow_switch():
                try: self.load_project(Path(path))
                except (OSError, ValueError) as exc: self._error("Impossibile aprire il progetto", exc)
        else:
            self.files.set_root(folder); self.status.setText("Cartella aperta. Fai doppio clic su un file per modificarlo; Play esegue la scheda attiva.")

    def load_project(self, path: Path):
        path = path.resolve(); data = json.loads(path.read_text(encoding="utf-8-sig")); doc = UiDocument.from_dict(data)
        filename = data.get("python_file", "app.py")
        if not isinstance(filename, str) or Path(filename).name != filename or not filename.endswith(".py") or any(c in filename for c in "\\/"):
            raise DocumentError("Il file Python del progetto deve essere un nome .py nella stessa cartella.")
        source_path = path.parent / filename
        source = source_path.read_text(encoding="utf-8-sig") if source_path.exists() else generate_document(doc)
        sync_error = None
        try: doc = source_to_document(source, doc)
        except SyncError as exc: sync_error = str(exc)
        self.sync_timer.stop(); self.project_path = path; self.project_dir = path.parent; self.source_path = source_path; self.doc = doc
        self.main_editor.path = str(source_path); self._set_source(source)
        self._saved_source = source if source_path.exists() else ""; self._saved_document = doc.to_dict()
        self._disk_versions[str(source_path)] = disk_hash(source_path); self._disk_versions[str(path)] = disk_hash(path)
        self.files.set_root(self.project_dir); self.console.set_working_directory(self.project_dir)
        self._set_sync(sync_error is None, sync_error or ""); self._selected_id = None; self._refresh_model(); self._reset_history(); self.editors.setCurrentWidget(self.main_editor)
        self.settings.setValue("last_project", str(path)); self.update_title(); self.status.setText("Progetto aperto · " + str(path.parent)); self.designer.fit()

    def _check_conflict(self, path):
        current = disk_hash(path); key = str(path)
        if key not in self._disk_versions:
            if current is None: return True
            text = f"Il file {path.name} esiste già. Sostituirlo?"
        elif current == self._disk_versions[key]: return True
        else: text = f"{path.name} è cambiato sul disco da quando è stato aperto. Sostituirlo con la versione dell’editor?"
        return QMessageBox.question(self, "Conferma salvataggio", text, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Yes

    def save_project(self):
        if self.project_path is None: return self.save_project_as()
        if self._sync_pending: self.sync_from_code()
        try:
            if not self._check_conflict(self.source_path) or not self._check_conflict(self.project_path): return False
            # Il Python resta autorevole anche quando il designer è sospeso.
            data = self.doc.to_dict(); data["python_file"] = self.source_path.name
            atomic_write(self.source_path, self.main_editor.source()); self._disk_versions[str(self.source_path)] = disk_hash(self.source_path)
            atomic_write(self.project_path, json.dumps(data, ensure_ascii=False, indent=2) + "\n"); self._disk_versions[str(self.project_path)] = disk_hash(self.project_path)
            self._saved_source = self.main_editor.source(); self._saved_document = self.doc.to_dict(); self.main_editor.editor.document().setModified(False)
            self._clear_recovery(); self.update_title(); self.status.setText("Progetto e codice salvati"); return True
        except (OSError, ValueError) as exc: self._error("Salvataggio non riuscito", exc); return False

    def save_project_as(self):
        folder = QFileDialog.getExistingDirectory(self, "Salva una copia del progetto in questa cartella", str(self.project_dir))
        if not folder: return False
        target = Path(folder).resolve(); project_path = target / "progetto.tkui"; source_path = target / "app.py"
        if not self._check_conflict(project_path) or not self._check_conflict(source_path): return False
        if self._sync_pending: self.sync_from_code()
        try:
            data = self.doc.to_dict(); data["python_file"] = "app.py"
            atomic_write(source_path, self.main_editor.source()); atomic_write(project_path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
            self.project_path = project_path; self.source_path = source_path; self.project_dir = target; self.main_editor.path = str(source_path)
            self._disk_versions[str(source_path)] = disk_hash(source_path); self._disk_versions[str(project_path)] = disk_hash(project_path)
            self._saved_source = self.main_editor.source(); self._saved_document = self.doc.to_dict(); self.settings.setValue("last_project", str(project_path))
            self.files.set_root(target); self.console.set_working_directory(target); self._clear_recovery(); self.update_title(); self.status.setText("Copia del progetto salvata"); return True
        except OSError as exc: self._error("Salvataggio non riuscito", exc); return False

    def save_active(self):
        editor = self.current_editor()
        if editor is self.main_editor: return self.save_project()
        if not editor.path:
            path, _ = QFileDialog.getSaveFileName(self, "Salva file", str(self.project_dir / "script.py"), "Python (*.py);;Tutti i file (*)")
            if not path: return False
        else: path = editor.path
        if not self._check_conflict(Path(path)): return False
        try:
            editor.save_path(path); self._disk_versions[str(Path(path))] = disk_hash(path); self.update_title(); self.status.setText("File salvato"); return True
        except OSError as exc: self._error("Salvataggio non riuscito", exc); return False

    def export_python(self):
        editor = self.current_editor(); path, _ = QFileDialog.getSaveFileName(self, "Esporta Python eseguibile", str(self.project_dir / "app_esportata.py"), "Python (*.py)")
        if not path: return
        try:
            ast.parse(editor.source()); atomic_write(Path(path), editor.source()); self.status.setText("Python esportato · " + path)
        except (OSError, SyntaxError) as exc: self._error("Esportazione non riuscita", exc)

    def choose_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Apri file", str(self.files.root or self.project_dir), "File di testo (*.py *.pyw *.json *.txt *.md *.toml *.tkui);;Tutti i file (*)")
        if path: self.open_file(path)

    def open_file(self, path):
        path = Path(path).resolve()
        if path.suffix.lower() == ".tkui":
            if path == self.project_path: self.editors.setCurrentWidget(self.main_editor); return
            if self._allow_switch():
                try: self.load_project(path)
                except (OSError, ValueError) as exc: self._error("Impossibile aprire il progetto", exc)
            return
        for index in range(self.editors.count()):
            editor = self.editors.widget(index)
            if editor.path and Path(editor.path) == path:
                self.editors.setCurrentIndex(index); self.set_view("split" if editor is self.main_editor else "code"); return
        try:
            if path.stat().st_size > 4 * 1024 * 1024: raise ValueError("Il file supera il limite di 4 MB dell’editor.")
            editor = EditorPanel(); editor.open_path(path); editor.set_theme(self.theme)
            self._disk_versions[str(path)] = disk_hash(path); editor.source_changed.connect(lambda e=editor: self.editor_changed(e)); editor.editor.cursor_position_changed.connect(self._cursor_changed)
            editor.assistance_message.connect(self.status.setText)
            index = self.editors.addTab(editor, icon("code" if path.suffix in (".py", ".pyw") else "file"), path.name); self.editors.setCurrentIndex(index); self.set_view("code")
        except (OSError, UnicodeError, ValueError) as exc: self._error("Impossibile aprire il file", exc)

    def close_editor(self, index):
        if index == 0: return
        editor = self.editors.widget(index)
        if editor.editor.document().isModified():
            answer = QMessageBox.question(self, "Modifiche non salvate", f"Salvare {Path(editor.path).name}?", QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
            if answer == QMessageBox.StandardButton.Cancel: return
            if answer == QMessageBox.StandardButton.Save:
                self.editors.setCurrentIndex(index)
                if not self.save_active(): return
        self.editors.removeTab(index); editor.deleteLater()

    def reload_active(self):
        editor = self.current_editor()
        if editor is self.main_editor:
            if self.project_path and self._allow_switch():
                try: self.load_project(self.project_path)
                except (OSError, ValueError) as exc: self._error("Ricaricamento non riuscito", exc)
        elif editor.path:
            if editor.editor.document().isModified() and QMessageBox.question(self, "Ricarica file", "Scartare le modifiche di questa scheda e ricaricare dal disco?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Yes: return
            try: editor.open_path(editor.path); self._disk_versions[editor.path] = disk_hash(editor.path); self.update_title()
            except (OSError, UnicodeError) as exc: self._error("Ricaricamento non riuscito", exc)

    def _tab_changed(self, index):
        if index < 0: return
        editor = self.editors.widget(index); cursor = editor.editor.textCursor(); self._cursor_changed(cursor.blockNumber() + 1, cursor.positionInBlock() + 1)

    def _cursor_changed(self, line, column): self.cursor_status.setText(f"Ln {line}, Col {column}")

    def _show_find(self, replace):
        if self.view_mode == "design": self.set_view("split")
        self.current_editor().show_find(replace)

    def _reveal_active_editor(self):
        editor = self.current_editor()
        if self.view_mode == "design":
            self.set_view("split"); self.editors.setCurrentWidget(editor)
        return editor

    def _show_integrations(self):
        self._reveal_active_editor().show_integrations()

    def _show_code_help(self):
        self._reveal_active_editor().show_code_help()

    def _check_code(self):
        editor = self._reveal_active_editor()
        if editor.path and Path(editor.path).suffix.lower() not in (".py", ".pyw"):
            self.status.setText("Il controllo Python è disponibile nelle schede .py e .pyw"); return []
        diagnostics = editor.check_syntax(reveal=True)
        errors = sum(item.severity == "error" for item in diagnostics)
        warnings = sum(item.severity == "warning" for item in diagnostics)
        self.status.setText(f"Controllo Python: {errors} errori, {warnings} avvisi" if diagnostics else "Sintassi Python corretta")
        return diagnostics

    def play(self):
        if self.runner.running: return
        editor = self.current_editor()
        if editor.path and Path(editor.path).suffix.lower() not in (".py", ".pyw"):
            self.status.setText("Play esegue un file Python: seleziona una scheda .py."); return
        source = editor.source()
        errors = [item for item in editor.check_syntax() if item.severity == "error"]
        if errors:
            first = errors[0]
            detail = first.message.removeprefix("Errore di sintassi: ")
            self.console.append_output(f"Errore di sintassi alla riga {first.line}, colonna {first.column}: {detail}\n{first.hint}\n", "stderr")
            self.set_view("split" if editor is self.main_editor else "code"); editor.go_to_diagnostic(first)
            self.run_label.setText("Correggi l’errore evidenziato"); return
        try:
            directory = Path(editor.path).parent if editor.path else self.project_dir
            directory.mkdir(parents=True, exist_ok=True)
            fd, filename = tempfile.mkstemp(prefix="_tkstudio_run_", suffix=".py", dir=directory)
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream: stream.write(source)
            self._run_path = Path(filename); self._run_editor = editor
            working_directory = self.project_dir if editor is self.main_editor else directory
            self.console.set_working_directory(working_directory)
            self._run_contexts[filename] = (weakref.ref(editor), source, editor.path)
            while len(self._run_contexts) > 32: self._run_contexts.pop(next(iter(self._run_contexts)))
            self.run_label.setText("Avvio in corso…"); self.play_button.setEnabled(False); self.run_action.setEnabled(False)
            self.stop_button.setEnabled(True); self.stop_action.setEnabled(True)
            self.runner.run(filename, str(working_directory))
        except (OSError, ValueError, RuntimeError) as exc:
            self.console.append_output(str(exc) + "\n", "stderr"); self._run_finished(-1, "failed_start")

    def _run_started(self):
        self.console.set_running(True); self.run_label.setText("In esecuzione · processo Python separato"); self.status.setText("Programma in esecuzione. Stop interrompe solo questo processo.")

    def _run_finished(self, code, reason):
        self.console.set_running(False); self.play_button.setEnabled(True); self.run_action.setEnabled(True); self.stop_button.setEnabled(False); self.stop_action.setEnabled(False)
        self.run_label.setText({"success": "Esecuzione completata", "stopped": "Programma interrotto", "error": f"Errore · codice {code}", "crash": "Il programma si è interrotto", "failed_start": "Avvio non riuscito"}.get(reason, f"Terminato · codice {code}"))
        if self._run_path:
            try: self._run_path.unlink(missing_ok=True)
            except OSError: pass
        self.status.setText(self.run_label.text())

    def open_location(self, path, line):
        context = self._run_contexts.get(str(Path(path)))
        if context:
            reference, source, original = context; editor = reference()
            try: current = editor is not None and self.editors.indexOf(editor) >= 0 and editor.source() == source
            except RuntimeError: current = False
            if not current:
                editor = EditorPanel(); editor.set_source(source); editor.editor.setReadOnly(True); editor.set_theme(self.theme)
                editor.display_name = "Esecuzione · " + (Path(original).name if original else "app.py")
                self.editors.addTab(editor, icon("code"), editor.display_name)
                editor.editor.cursor_position_changed.connect(self._cursor_changed)
            self.editors.setCurrentWidget(editor)
        else:
            if not Path(path).is_file(): return
            self.open_file(path); editor = self.editors.currentWidget()
        self.set_view("split" if editor is self.main_editor else "code"); editor.go_to_line(line); editor.highlight_error(line)

    def choose_interpreter(self):
        path, _ = QFileDialog.getOpenFileName(self, "Seleziona python.exe con supporto Tkinter", str(Path(self.runner.interpreter).parent), "Interprete Python (python.exe);;Tutti i file (*)")
        if not path: return
        try:
            self.runner.set_interpreter(path); self.settings.setValue("interpreter", path); self.python_status.setText(Path(path).name + "  ·  UTF-8  ·  Tkinter"); self.python_status.setToolTip(path); self.status.setText("Interprete selezionato: " + path)
        except (ValueError, RuntimeError) as exc: self._error("Interprete non disponibile", exc)

    def open_demo(self):
        if self._allow_switch():
            try: self.load_project(ROOT / "esempi" / "Benvenuto" / "progetto.tkui")
            except (OSError, ValueError) as exc: self._error("Esempio non disponibile", exc)

    def show_help(self):
        dialog = QDialog(self); dialog.setWindowTitle("La tua guida a Tkinter Studio"); dialog.resize(720, 650)
        layout = QVBoxLayout(dialog); browser = QTextBrowser(); browser.setOpenExternalLinks(True)
        browser.setHtml("""<h1>Un’idea, una finestra, il tuo codice.</h1>
        <p>Il designer e il codice sono due viste della stessa interfaccia. <b>Play esegue sempre il codice corrente</b>, anche se non lo hai ancora salvato.</p>
        <h2>Il primo programma</h2><ol><li>Crea un progetto con <b>File → Nuovo progetto</b>, oppure modifica l’esempio.</li><li>Trascina i componenti dalla libreria. Puoi inserirli nei contenitori.</li><li>Seleziona un componente: a destra trovi testo, nome, posizione, dimensioni e callback.</li><li>Fai doppio clic su un pulsante per aprire la funzione Python. Scrivi lì la tua logica.</li><li>Premi <b>F5</b>. Il programma Tkinter si apre in una finestra separata. La console mostra output, errori e collegamenti alle righe.</li></ol>
        <h2>Designer e codice</h2><p>Il metodo <code>build_ui</code> fra i marcatori <code>tkstudio:ui</code> descrive i componenti con valori letterali. Puoi cambiare anche dal codice testi, coordinate, dimensioni e proprietà. La vista si aggiorna automaticamente.</p>
        <p><b>Scrivi funzioni, cicli, condizioni e logica applicativa fuori da questa regione.</b> Se il codice diventa dinamico nella regione del designer, il designer si sospende e il testo viene conservato. Puoi continuare a modificare ed eseguire il programma.</p>
        <h2>Integrazioni e aiuto nel codice</h2><p>Seleziona il codice di un componente e fai <b>clic destro</b>: il menu propone integrazioni compatibili con quel tipo di controllo. Puoi creare o aprire callback, collegare eventi e inserire funzioni di esempio. Ogni inserimento è annullabile con Ctrl+Z e mantiene la logica fuori dal blocco del designer.</p>
        <p>La barra dell’editor offre anche <b>Integra</b>, <b>Aiuto codice</b> e <b>Controlla</b>. <b>Ctrl+I</b> spiega la parola o il componente al cursore con un esempio; <b>F8</b> controlla la sintassi. Il controllo automatico segnala gli errori mentre scrivi, con riga, colonna e indicazioni per correggerli. Fai clic su un problema per raggiungerlo. Questo controllo verifica la sintassi e non esegue il tuo programma.</p>
        <p>Il canvas è schematico; l’aspetto reale è quello della finestra Tkinter aperta da Play. Il layout usa <code>place</code> e coordinate in pixel; non converte automaticamente programmi arbitrari con <code>pack</code> o <code>grid</code>.</p>
        <h2>I tuoi file</h2><p><code>progetto.tkui</code> contiene la struttura visuale; <code>app.py</code> contiene il programma completo. <b>Ctrl+S</b> salva entrambi. Le altre schede si salvano singolarmente. Il Python esportato usa solo la libreria standard e non richiede l’IDE.</p>
        <h2>Scorciatoie</h2><p><b>Ctrl+1 / 2 / 3</b>: designer / affiancati / codice<br><b>Ctrl+0</b>: adatta canvas<br><b>Ctrl+S</b>: salva · <b>Ctrl+Z</b>: annulla · <b>Ctrl+Maiusc+Z</b>: ripeti<br><b>Ctrl+D</b>: duplica nel canvas · <b>Canc</b>: elimina<br><b>Frecce</b>: 1 px · <b>Maiusc+frecce</b>: 10 px<br><b>Ctrl+F / H / G</b>: cerca / sostituisci / vai alla riga<br><b>Ctrl+Spazio</b>: suggerimenti Python · <b>Ctrl+I</b>: aiuto codice<br><b>F8</b>: controlla sintassi<br><b>F5</b>: Play · <b>Maiusc+F5</b>: Stop</p>
        <p>Il menu Esegui consente di scegliere un altro interprete Python con Tkinter e le librerie del tuo progetto.</p>""")
        layout.addWidget(browser); buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close); buttons.rejected.connect(dialog.reject); layout.addWidget(buttons); dialog.exec()

    def _recovery_path(self):
        directory = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)); directory.mkdir(parents=True, exist_ok=True)
        return directory / "recovery.json"

    def _write_recovery(self):
        if not self._main_dirty(): return
        try:
            atomic_write(self._recovery_path(), json.dumps({"project": str(self.project_path) if self.project_path else None, "document": self.doc.to_dict(), "source": self.main_editor.source()}, ensure_ascii=False))
        except OSError: pass

    def _clear_recovery(self):
        try: self._recovery_path().unlink(missing_ok=True)
        except OSError: pass

    def _offer_recovery(self):
        try:
            path = self._recovery_path()
            if not path.exists(): return
            data = json.loads(path.read_text(encoding="utf-8")); document = UiDocument.from_dict(data["document"])
            if data["source"] == self.main_editor.source(): self._clear_recovery(); return
            if QMessageBox.question(self, "Recupera il lavoro", "È disponibile una bozza non salvata della sessione precedente. Recuperarla?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
                previous = data.get("project")
                if previous and Path(previous).is_file(): self.load_project(Path(previous))
                else: self.project_path = None; self.source_path = None; self.main_editor.path = None; self._saved_source = ""; self._saved_document = None
                self.doc = document; self._set_source(data["source"]); self.sync_from_code(); self._reset_history(); self.update_title()
            self._clear_recovery()
        except (OSError, ValueError, KeyError): self._clear_recovery()

    def _error(self, title, exc):
        self.status.setText(title); QMessageBox.warning(self, title, str(exc))

    def closeEvent(self, event):
        if self.runner.running: self.runner.shutdown()
        if not self._allow_switch(): event.ignore(); return
        # Anche le schede non collegate al designer mantengono le proprie modifiche.
        for index in range(self.editors.count() - 1, 0, -1):
            editor = self.editors.widget(index)
            if editor.editor.document().isModified():
                self.editors.setCurrentIndex(index)
                answer = QMessageBox.question(self, "Modifiche non salvate", f"Salvare le modifiche a {Path(editor.path).name}?", QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
                if answer == QMessageBox.StandardButton.Cancel or (answer == QMessageBox.StandardButton.Save and not self.save_active()): event.ignore(); return
        self.runner.shutdown(); self._run_finished(0, "stopped") if self._run_path else None
        self.settings.setValue("geometry", self.saveGeometry()); self._clear_recovery(); event.accept()


def main():
    app = QApplication(sys.argv); app.setApplicationName("Tkinter Studio"); app.setOrganizationName("TkinterStudio"); app.setApplicationVersion(__version__); app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    def report_exception(error_type, value, tb):
        detail = "".join(traceback.format_exception(error_type, value, tb))
        if sys.stderr is not None: sys.stderr.write(detail)
        log_path = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)) / "ultimo-errore.log"
        try: log_path.parent.mkdir(parents=True, exist_ok=True); atomic_write(log_path, detail)
        except OSError: pass
        QMessageBox.critical(None, "Errore di Tkinter Studio", f"{value}\n\nDettagli nel file:\n{log_path}")
    sys.excepthook = report_exception
    try: window = MainWindow(sys.argv[1] if len(sys.argv) > 1 else None)
    except Exception:
        report_exception(*sys.exc_info()); return 1
    window.show()
    return app.exec()
