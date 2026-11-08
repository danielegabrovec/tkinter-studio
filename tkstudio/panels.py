"""Libreria componenti, proprietà e navigazione del progetto."""
from __future__ import annotations

import ast
from pathlib import Path

from PyQt6.QtCore import Qt, QMimeData, QSize, pyqtSignal, QSortFilterProxyModel, QDir
from PyQt6.QtGui import QDrag, QFileSystemModel, QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QAbstractItemView, QScrollArea, QFormLayout, QSpinBox,
    QDoubleSpinBox, QCheckBox, QComboBox, QPushButton, QColorDialog,
    QTreeWidget, QTreeWidgetItem, QTreeView, QMenu, QInputDialog, QMessageBox,
)

from .model import UiDocument, WIDGET_SPECS, supported_properties
from .theme import widget_icon, icon, PALETTES


def heading(text, hint=None):
    wrap = QWidget()
    box = QVBoxLayout(wrap); box.setContentsMargins(14, 13, 14, 8); box.setSpacing(5)
    label = QLabel(text.upper()); label.setObjectName("sectionTitle"); box.addWidget(label)
    if hint:
        label = QLabel(hint); label.setObjectName("hint"); label.setWordWrap(True); box.addWidget(label)
    return wrap


class WidgetList(QListWidget):
    def startDrag(self, supportedActions):
        current = self.currentItem()
        if not current or not current.data(Qt.ItemDataRole.UserRole): return
        kind = current.data(Qt.ItemDataRole.UserRole)
        mime = QMimeData(); mime.setData("application/x-tkstudio-widget", kind.encode("utf-8"))
        drag = QDrag(self); drag.setMimeData(mime)
        pixmap = current.icon().pixmap(32, 32); drag.setPixmap(pixmap)
        drag.exec(Qt.DropAction.CopyAction)


class PalettePanel(QWidget):
    add_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        box = QVBoxLayout(self); box.setContentsMargins(0, 0, 0, 0); box.setSpacing(4)
        box.addWidget(heading("Componenti", "Trascina sul canvas o fai doppio clic."))
        self.search = QLineEdit(); self.search.setPlaceholderText("Cerca un componente…"); self.search.setAccessibleName("Cerca componenti Tkinter")
        row = QHBoxLayout(); row.setContentsMargins(12, 0, 12, 5); row.addWidget(self.search); box.addLayout(row)
        self.list = WidgetList(); self.list.setDragEnabled(True); self.list.setIconSize(QSize(20, 20)); self.list.setSpacing(2)
        self.list.setAccessibleName("Libreria componenti Tkinter")
        box.addWidget(self.list)
        self.search.textChanged.connect(self.populate)
        self.list.itemDoubleClicked.connect(lambda item: self.add_requested.emit(item.data(Qt.ItemDataRole.UserRole)) if item.data(Qt.ItemDataRole.UserRole) else None)
        self.theme = "dark"; self.populate()

    def populate(self, query=""):
        self.list.clear(); query = self.search.text().casefold()
        groups = {}
        for kind, spec in WIDGET_SPECS.items():
            if query and query not in f"{kind} {spec.label} {spec.category} {spec.description}".casefold(): continue
            groups.setdefault(spec.category, []).append((kind, spec))
        for category, entries in groups.items():
            title = QListWidgetItem(category.upper()); title.setFlags(Qt.ItemFlag.NoItemFlags)
            title.setForeground(QColor(PALETTES[self.theme]["muted"])); font = title.font(); font.setPointSize(8); font.setBold(True); title.setFont(font)
            self.list.addItem(title)
            for kind, spec in entries:
                item = QListWidgetItem(widget_icon(kind, PALETTES[self.theme]["muted"]), spec.label)
                item.setData(Qt.ItemDataRole.UserRole, kind); item.setToolTip(f"{kind}\n{spec.description}\nTrascina oppure fai doppio clic per aggiungere.")
                self.list.addItem(item)
        if not groups:
            item = QListWidgetItem("Nessun componente trovato"); item.setFlags(Qt.ItemFlag.NoItemFlags); self.list.addItem(item)

    def set_theme(self, theme):
        self.theme = theme; self.populate()


class PropertyPanel(QWidget):
    changed = pyqtSignal(str, object)
    callback_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.doc = None; self.node_id = None; self._fields = {}; self._refreshing = False
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)
        self.summary = heading("Proprietà", "Seleziona un componente per modificarlo."); outer.addWidget(self.summary)
        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True); outer.addWidget(self.scroll)

    def _section(self, text):
        label = QLabel(text.upper()); label.setObjectName("sectionTitle"); label.setContentsMargins(0, 14, 0, 4)
        self.form.addRow(label)

    def show_document(self, doc: UiDocument, node_id=None):
        self.doc = doc; self.node_id = node_id; self._refreshing = True; self._fields = {}
        body = QWidget(); self.form = QFormLayout(body); self.form.setContentsMargins(14, 0, 14, 18); self.form.setSpacing(10)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        old = self.scroll.takeWidget()
        if old: old.deleteLater()
        self.scroll.setWidget(body)
        node = doc.find(node_id) if node_id else None
        title = QLabel(node.name if node else "Finestra principale"); title.setObjectName("sectionHeading"); title.setWordWrap(True)
        self.form.addRow(title)
        kind_label = QLabel(node.kind if node else "tk.Tk · finestra dell’applicazione"); kind_label.setObjectName("hint"); self.form.addRow(kind_label)
        if node is None:
            self._section("Finestra")
            self._field("Titolo", "title", doc.title)
            self._field("Larghezza", "width", doc.width)
            self._field("Altezza", "height", doc.height)
            self._field("Sfondo", "background", doc.background, color=True)
            self._section("Come iniziare")
            hint = QLabel("1. Trascina un componente.\n2. Cambia le proprietà.\n3. Scrivi la logica nel codice.\n4. Premi Play per provarla.")
            hint.setObjectName("hint"); hint.setWordWrap(True); hint.setMinimumHeight(90); self.form.addRow(hint)
            hint = QLabel("Le dimensioni e le posizioni sono in pixel. I contenitori possono ospitare altri componenti."); hint.setObjectName("hint"); hint.setWordWrap(True); self.form.addRow(hint)
        else:
            self._section("Identità")
            self._field("Nome Python", "name", node.name)
            parents = QComboBox(); parents.addItem("Finestra principale", None)
            descendants = {node.id}
            for _ in range(len(doc.widgets)):
                descendants.update(n.id for n in doc.widgets if n.parent in descendants)
            for n in doc.widgets:
                if n.id not in descendants and WIDGET_SPECS[n.kind].container:
                    parents.addItem(n.name, n.id)
            parents.setCurrentIndex(max(0, parents.findData(node.parent)))
            parents.currentIndexChanged.connect(lambda _: self._emit("parent", parents.currentData()))
            self.form.addRow("Contenitore", parents); self._fields["parent"] = parents
            self._section("Posizione e dimensioni")
            for key, label in (("x", "X"), ("y", "Y"), ("width", "Larghezza"), ("height", "Altezza")):
                self._field(label, key, getattr(node, key))
            self._section("Aspetto e contenuto")
            labels = {"text": "Testo", "command": "Azione / callback", "values": "Valori", "items": "Elementi", "state": "Stato", "orient": "Orientamento", "padding": "Padding", "from_": "Minimo", "to": "Massimo", "value": "Valore", "maximum": "Massimo", "anchor": "Allineamento", "justify": "Testo allineato", "font": "Font", "background": "Sfondo", "foreground": "Colore testo", "show": "Maschera", "mode": "Modalità", "columns": "Colonne", "headings": "Intestazioni", "selectmode": "Selezione"}
            props = dict(WIDGET_SPECS[node.kind].default_properties); props.update(node.properties)
            for key, value in props.items():
                self._field(labels.get(key, key), "properties." + key, value, color=key in ("background", "foreground"))
            available = sorted(supported_properties(node.kind) - set(props))
            if available:
                self._section("Altre proprietà")
                extra = QComboBox(); extra.setAccessibleName("Proprietà aggiuntiva")
                for key in available: extra.addItem(labels.get(key, key), key)
                row = QWidget(); line = QHBoxLayout(row); line.setContentsMargins(0, 0, 0, 0); line.setSpacing(4); line.addWidget(extra, 1)
                add = QPushButton("+"); add.setAccessibleName("Aggiungi proprietà"); add.setToolTip("Aggiungi la proprietà selezionata"); add.setFixedWidth(30)
                add.clicked.connect(lambda: self._add_property(extra.currentData())); line.addWidget(add); self.form.addRow(row)
            if node.kind == "ttk.Button" or "command" in props:
                button = QPushButton("Apri la funzione nel codice"); button.setObjectName("secondaryButton")
                button.clicked.connect(lambda: self.callback_requested.emit(node.id)); self.form.addRow(button)
            self._section("Suggerimento")
            hint = QLabel("Frecce: sposta di 1 px\nMaiusc + frecce: 10 px\nCtrl+D: duplica · Canc: elimina\nDoppio clic: apri il callback")
            hint.setObjectName("hint"); hint.setWordWrap(True); self.form.addRow(hint)
        self._refreshing = False

    def _field(self, label, key, value, color=False):
        if isinstance(value, bool):
            field = QCheckBox(); field.setChecked(value); field.toggled.connect(lambda val: self._emit(key, val))
        elif isinstance(value, int):
            field = QSpinBox(); field.setRange(1 if key in ("width", "height") else -100000, 100000)
            field.setValue(value); field.setKeyboardTracking(False); field.valueChanged.connect(lambda val: self._emit(key, val))
        elif isinstance(value, float):
            field = QDoubleSpinBox(); field.setRange(-1000000, 1000000); field.setDecimals(2); field.setValue(value); field.setKeyboardTracking(False)
            field.valueChanged.connect(lambda val: self._emit(key, val))
        elif key == "properties.orient":
            field = QComboBox(); field.addItems(["horizontal", "vertical"]); field.setCurrentText(str(value)); field.currentTextChanged.connect(lambda val: self._emit(key, val))
        elif key == "properties.state":
            field = QComboBox(); field.addItems(["normal", "disabled"] + (["readonly"] if self.doc.find(self.node_id).kind in ("ttk.Entry", "ttk.Combobox", "ttk.Spinbox") else []))
            field.setCurrentText(str(value)); field.currentTextChanged.connect(lambda val: self._emit(key, val))
        else:
            field = QLineEdit(repr(value) if isinstance(value, (list, tuple, dict)) else str(value))
            field.setAccessibleName(label)
            if isinstance(value, (list, tuple, dict)):
                field.setToolTip("Lista Python, ad esempio ['Primo', 'Secondo']")
            if key == "properties.command": field.setPlaceholderText("es. on_salva")
            field.editingFinished.connect(lambda f=field, k=key, v=value: self._finish(f, k, v))
        field.setAccessibleName(label); self._fields[key] = field
        if color:
            wrap = QWidget(); row = QHBoxLayout(wrap); row.setContentsMargins(0, 0, 0, 0); row.setSpacing(5); row.addWidget(field)
            button = QPushButton("…"); button.setFixedWidth(30); button.setAccessibleName("Scegli " + label.lower()); button.setToolTip("Scegli colore")
            button.clicked.connect(lambda: self._pick_color(key, field)); row.addWidget(button); self.form.addRow(label, wrap)
        else: self.form.addRow(label, field)

    def _finish(self, field, key, previous):
        try:
            text = field.text()
            value = ast.literal_eval(text) if isinstance(previous, (list, tuple, dict)) else text
            if isinstance(previous, (list, tuple)) and not isinstance(value, (list, tuple)):
                raise ValueError("Inserisci una lista Python, per esempio ['uno', 'due']")
            if value != previous: self._emit(key, value)
        except (ValueError, SyntaxError) as exc:
            field.setToolTip(str(exc)); field.setText(repr(previous)); field.setFocus()

    def _pick_color(self, key, field):
        color = QColorDialog.getColor(QColor(field.text()), self, "Scegli un colore")
        if color.isValid(): field.setText(color.name()); self._emit(key, color.name())

    def _emit(self, key, value):
        if not self._refreshing: self.changed.emit(key, value)

    def _add_property(self, key):
        defaults = {"style": "", "state": "normal", "font": ["Segoe UI", 10], "foreground": "#202b40", "background": "#ffffff", "padding": 0, "borderwidth": 1, "relief": "flat", "cursor": "", "justify": "left", "wraplength": 0, "labelanchor": "nw", "onvalue": True, "offvalue": False, "length": 120, "value": 0, "selectmode": "browse", "values": [], "show": "", "mode": "determinate", "wrap": False, "command": "", "text": "", "padx": 0, "pady": 0}
        if key: self._emit("properties." + key, defaults.get(key, ""))


class HierarchyPanel(QTreeWidget):
    selected = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent); self.setHeaderHidden(True); self.setAccessibleName("Struttura della finestra Tkinter")
        self.setIndentation(16); self._updating = False
        self.currentItemChanged.connect(self._selected)

    def _selected(self, item, old):
        if item and not self._updating: self.selected.emit(item.data(0, Qt.ItemDataRole.UserRole))

    def populate(self, doc, selected_id=None):
        self._updating = True; self.clear()
        root = QTreeWidgetItem([doc.title]); root.setIcon(0, icon("app")); root.setData(0, Qt.ItemDataRole.UserRole, None); self.addTopLevelItem(root)
        items = {None: root}
        waiting = list(doc.widgets)
        while waiting:
            progress = False
            for node in waiting[:]:
                if node.parent not in items: continue
                item = QTreeWidgetItem([node.name]); item.setToolTip(0, node.kind); item.setIcon(0, widget_icon(node.kind)); item.setData(0, Qt.ItemDataRole.UserRole, node.id)
                items[node.parent].addChild(item); items[node.id] = item; waiting.remove(node); progress = True
            if not progress: break
        self.expandAll(); self.setCurrentItem(items.get(selected_id, root)); self._updating = False


class ProjectFilter(QSortFilterProxyModel):
    def filterAcceptsRow(self, row, parent):
        source = self.sourceModel(); index = source.index(row, 0, parent); name = source.fileName(index)
        return name not in {".venv", "venv", "__pycache__", ".git", ".tkstudio", ".pytest_cache", "node_modules"} and not name.startswith("_tkstudio_run_")


class FilePanel(QWidget):
    file_opened = pyqtSignal(str)
    folder_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent); self.root = None
        box = QVBoxLayout(self); box.setContentsMargins(0, 0, 0, 0); box.setSpacing(0)
        bar = QWidget(); row = QHBoxLayout(bar); row.setContentsMargins(14, 8, 8, 4)
        title = QLabel("ESPLORA PROGETTO"); title.setObjectName("sectionTitle"); row.addWidget(title); row.addStretch()
        button = QPushButton(); button.setIcon(icon("folder")); button.setToolTip("Apri cartella progetto"); button.setAccessibleName("Apri cartella progetto"); button.setFixedWidth(32); button.clicked.connect(self.folder_requested); row.addWidget(button); box.addWidget(bar)
        self.root_label = QLabel("Nessun progetto"); self.root_label.setObjectName("hint"); self.root_label.setContentsMargins(14, 2, 12, 6); box.addWidget(self.root_label)
        self.model = QFileSystemModel(); self.model.setFilter(QDir.Filter.AllDirs | QDir.Filter.Files | QDir.Filter.NoDotAndDotDot)
        self.proxy = ProjectFilter(); self.proxy.setSourceModel(self.model)
        self.tree = QTreeView(); self.tree.setModel(self.proxy); self.tree.setHeaderHidden(True); self.tree.setIndentation(14); self.tree.setAnimated(False)
        self.tree.setAccessibleName("File e cartelle del progetto"); self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        for column in range(1, 4): self.tree.hideColumn(column)
        self.tree.doubleClicked.connect(self._open); self.tree.customContextMenuRequested.connect(self._menu); box.addWidget(self.tree)

    def set_root(self, path):
        self.root = Path(path).resolve(); self.model.setRootPath(str(self.root)); self.tree.setRootIndex(self.proxy.mapFromSource(self.model.index(str(self.root))))
        self.root_label.setText(self.root.name); self.root_label.setToolTip(str(self.root))

    def _path(self, index):
        return Path(self.model.filePath(self.proxy.mapToSource(index))) if index.isValid() else self.root

    def _open(self, index):
        path = self._path(index)
        if path and path.is_file(): self.file_opened.emit(str(path))

    def _menu(self, pos):
        path = self._path(self.tree.indexAt(pos))
        if path is None: return
        folder = path if path.is_dir() else path.parent
        menu = QMenu(self); new_file = menu.addAction("Nuovo file…"); new_folder = menu.addAction("Nuova cartella…")
        if path.is_file(): menu.addSeparator(); open_action = menu.addAction("Apri nell’editor")
        else: open_action = None
        action = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if action == open_action and open_action: self.file_opened.emit(str(path)); return
        if action not in (new_file, new_folder): return
        name, ok = QInputDialog.getText(self, "Nuovo file" if action == new_file else "Nuova cartella", "Nome:")
        if not ok or not name.strip(): return
        name = name.strip()
        if Path(name).name != name or name in (".", "..") or any(c in name for c in '\\/:*?"<>|'):
            QMessageBox.warning(self, "Nome non valido", "Usa un nome senza separatori di cartelle o caratteri riservati."); return
        target = folder / name
        try:
            if action == new_file:
                with target.open("x", encoding="utf-8") as handle: handle.write("")
                self.file_opened.emit(str(target))
            else: target.mkdir()
        except OSError as exc: QMessageBox.warning(self, "Creazione non riuscita", str(exc))
