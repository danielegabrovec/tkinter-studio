"""Validated, UI-independent project model for TkStudio."""
from __future__ import annotations

from dataclasses import dataclass, field
import copy
import keyword
import re
import uuid
from typing import Any
import tkinter as tk


class DocumentError(ValueError):
    """A project cannot safely be interpreted as a visual document."""


@dataclass(frozen=True)
class WidgetSpec:
    label: str
    category: str
    default_width: int
    default_height: int
    default_properties: dict[str, Any]
    container: bool = False
    description: str = ""


WIDGET_SPECS: dict[str, WidgetSpec] = {
    "ttk.Label": WidgetSpec("Etichetta", "Essenziali", 160, 30, {"text": "Etichetta", "anchor": "w"}, description="Un testo o una didascalia."),
    "ttk.Button": WidgetSpec("Pulsante", "Essenziali", 130, 36, {"text": "Pulsante", "command": ""}, description="Un'azione collegata a una funzione Python."),
    "ttk.Entry": WidgetSpec("Campo di testo", "Essenziali", 220, 34, {"text": "", "show": ""}, description="Una riga di testo modificabile."),
    "ttk.Checkbutton": WidgetSpec("Casella di spunta", "Essenziali", 190, 30, {"text": "Accetto", "command": ""}, description="Un'opzione che può essere selezionata."),
    "ttk.Radiobutton": WidgetSpec("Scelta singola", "Essenziali", 190, 30, {"text": "Opzione", "value": "opzione", "command": ""}, description="Una scelta fra opzioni alternative."),
    "ttk.Combobox": WidgetSpec("Elenco a discesa", "Essenziali", 220, 34, {"values": ["Prima scelta", "Seconda scelta", "Terza scelta"], "state": "readonly", "text": ""}, description="Una scelta da un elenco."),
    "ttk.Spinbox": WidgetSpec("Selettore numerico", "Essenziali", 140, 34, {"from_": 0, "to": 100, "increment": 1, "text": ""}, description="Un numero con frecce di incremento."),
    "ttk.Frame": WidgetSpec("Contenitore", "Contenitori", 340, 200, {"padding": 0, "relief": "flat"}, True, "Raggruppa elementi con coordinate relative."),
    "ttk.LabelFrame": WidgetSpec("Gruppo con titolo", "Contenitori", 340, 200, {"text": "Gruppo", "padding": 0}, True, "Un contenitore con titolo e bordo."),
    "ttk.Separator": WidgetSpec("Separatore", "Contenitori", 260, 2, {"orient": "horizontal"}, description="Una linea per separare sezioni."),
    "tk.Text": WidgetSpec("Area di testo", "Dati e contenuti", 300, 160, {"text": "", "wrap": "word"}, description="Testo modificabile su più righe."),
    "tk.Listbox": WidgetSpec("Elenco", "Dati e contenuti", 220, 150, {"items": ["Primo elemento", "Secondo elemento"], "selectmode": "browse"}, description="Un elenco di elementi selezionabili."),
    "ttk.Treeview": WidgetSpec("Tabella / albero", "Dati e contenuti", 340, 180, {"columns": ["nome", "valore"], "show": "headings"}, description="Una tabella con colonne o una struttura ad albero."),
    "tk.Canvas": WidgetSpec("Area di disegno", "Dati e contenuti", 280, 180, {"background": "#ffffff", "highlightthickness": 1}, description="Una superficie per disegni e grafica Tkinter."),
    "ttk.Scale": WidgetSpec("Cursore", "Indicatori", 220, 32, {"from_": 0, "to": 100, "orient": "horizontal"}, description="Un valore regolabile trascinando un cursore."),
    "ttk.Progressbar": WidgetSpec("Barra di avanzamento", "Indicatori", 240, 22, {"value": 60, "maximum": 100, "mode": "determinate", "orient": "horizontal"}, description="Visualizza un avanzamento o uno stato di attesa."),
}

# Each property is passed to the actual Tkinter constructor, except the explicit
# content helpers below. Unknown options would make exported programs fail.
_EXTRA_OPTIONS = {
    "ttk.Label": {"justify", "padding", "relief", "wraplength", "state", "cursor", "font", "foreground", "background", "borderwidth"},
    "ttk.Button": {"state", "padding", "cursor"},
    "ttk.Entry": {"state", "justify", "cursor"},
    "ttk.Checkbutton": {"state", "onvalue", "offvalue", "cursor"},
    "ttk.Radiobutton": {"state", "cursor"},
    "ttk.Combobox": {"justify", "cursor", "text"},
    "ttk.Spinbox": {"values", "state", "justify", "text", "command", "wrap"},
    "ttk.Frame": {"borderwidth", "cursor"},
    "ttk.LabelFrame": {"relief", "borderwidth", "labelanchor", "cursor"},
    "ttk.Separator": set(),
    "tk.Text": {"foreground", "background", "font", "state", "relief", "borderwidth", "padx", "pady"},
    "tk.Listbox": {"foreground", "background", "font", "state", "relief", "borderwidth"},
    "ttk.Treeview": {"selectmode", "padding"},
    "tk.Canvas": {"relief", "borderwidth", "cursor"},
    "ttk.Scale": {"value", "state", "command", "length"},
    "ttk.Progressbar": {"length"},
}

_RESERVED = {
    "build_ui", "mainloop", "destroy", "title", "geometry", "configure", "config", "quit",
    "after", "bind", "unbind", "update", "update_idletasks", "children", "tk", "master",
    "withdraw", "deiconify", "resizable", "minsize", "maxsize", "protocol", "winfo_children",
    "pack", "grid", "place", "state", "focus", "event_generate", "register", "bell",
}
_RESERVED.update(name for name in dir(tk.Tk) if not name.startswith("_"))


@dataclass
class WidgetNode:
    id: str
    kind: str
    name: str
    parent: str | None = None
    x: int = 20
    y: int = 20
    width: int = 160
    height: int = 32
    properties: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "name": self.name, "parent": self.parent,
                "x": self.x, "y": self.y, "width": self.width, "height": self.height,
                "properties": copy.deepcopy(self.properties)}


@dataclass
class UiDocument:
    title: str = "La mia applicazione"
    width: int = 800
    height: int = 560
    background: str = "#f5f7fb"
    widgets: list[WidgetNode] = field(default_factory=list)

    def find(self, widget_id: str | None) -> WidgetNode | None:
        return next((w for w in self.widgets if w.id == widget_id), None)

    def clone(self) -> UiDocument:
        return copy.deepcopy(self)

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": 1, "title": self.title, "width": self.width, "height": self.height,
                "background": self.background, "widgets": [w.to_dict() for w in self.widgets]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UiDocument:
        if not isinstance(data, dict) or data.get("schema_version", 1) != 1:
            raise DocumentError("Formato di progetto non supportato (atteso schema 1).")
        try:
            raw_widgets = data.get("widgets", [])
            if not isinstance(raw_widgets, list) or len(raw_widgets) > 1000:
                raise DocumentError("Il progetto deve contenere al massimo 1000 elementi.")
            widgets = [WidgetNode(**item) for item in raw_widgets]
            document = cls(title=data.get("title", "La mia applicazione"), width=data.get("width", 800),
                           height=data.get("height", 560), background=data.get("background", "#f5f7fb"),
                           widgets=widgets)
            validate_document(document)
            return document
        except (TypeError, KeyError, AttributeError) as exc:
            raise DocumentError(f"Il file di progetto contiene dati non validi: {exc}") from exc


def valid_identifier(value: Any) -> bool:
    return (isinstance(value, str) and bool(value) and value.isidentifier()
            and not keyword.iskeyword(value) and not value.startswith("_") and value not in _RESERVED)


def supported_properties(kind: str) -> set[str]:
    return set(WIDGET_SPECS[kind].default_properties) | _EXTRA_OPTIONS.get(kind, set()) | ({"style"} if kind.startswith("ttk.") else set())


def _json_value(value: Any, depth: int = 0) -> bool:
    if depth > 5:
        return False
    if value is None or isinstance(value, (str, bool, int)):
        return True
    if isinstance(value, float):
        import math
        return math.isfinite(value)
    if isinstance(value, (list, tuple)):
        return len(value) <= 2000 and all(_json_value(v, depth + 1) for v in value)
    return False


def validate_document(document: UiDocument) -> None:
    if not isinstance(document, UiDocument):
        raise DocumentError("Documento non valido.")
    if not isinstance(document.title, str) or not isinstance(document.background, str):
        raise DocumentError("Titolo e colore della finestra devono essere testi.")
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", document.background):
        raise DocumentError("Il colore della finestra deve essere esadecimale, per esempio #f5f7fb.")
    for key, value in (("larghezza", document.width), ("altezza", document.height)):
        if type(value) is not int or not 120 <= value <= 8192:
            raise DocumentError(f"La {key} della finestra deve essere fra 120 e 8192 pixel.")
    if not isinstance(document.widgets, list) or len(document.widgets) > 1000:
        raise DocumentError("Il progetto deve contenere al massimo 1000 elementi.")
    names: set[str] = set()
    ids: set[str] = set()
    for node in document.widgets:
        if not isinstance(node, WidgetNode) or node.kind not in WIDGET_SPECS:
            raise DocumentError("Il progetto contiene un tipo di elemento sconosciuto.")
        if not isinstance(node.id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", node.id) or node.id in ids:
            raise DocumentError("Gli identificativi degli elementi devono essere validi e univoci.")
        ids.add(node.id)
        if not valid_identifier(node.name) or node.name in names:
            raise DocumentError(f"Nome Python non valido o già utilizzato: {node.name!r}.")
        names.add(node.name)
        for key in ("x", "y", "width", "height"):
            value = getattr(node, key)
            if type(value) is not int or not (0 if key in ("x", "y") else 1) <= value <= 32768:
                raise DocumentError(f"Valore {key} non valido per {node.name}.")
        if not isinstance(node.properties, dict):
            raise DocumentError(f"Proprietà non valide per {node.name}.")
        for key, value in node.properties.items():
            if key not in supported_properties(node.kind):
                raise DocumentError(f"La proprietà {key!r} non è supportata per {node.kind}.")
            if not _json_value(value):
                raise DocumentError(f"Il valore di {key!r} per {node.name} non è un valore semplice.")
            if key == "command" and (not isinstance(value, str) or (value and not valid_identifier(value))):
                raise DocumentError(f"Il comando di {node.name} deve essere il nome di una funzione Python.")
            if key in ("values", "items", "columns") and not isinstance(value, (list, tuple)):
                raise DocumentError(f"La proprietà {key} di {node.name} deve essere un elenco.")
            if key in ("items", "columns") and not all(isinstance(item, str) for item in value):
                raise DocumentError(f"La proprietà {key} di {node.name} deve contenere solo testi.")
            if key == "columns" and len(set(value)) != len(value):
                raise DocumentError(f"Le colonne di {node.name} devono essere univoche.")
            if key in ("text", "show") and not isinstance(value, str):
                raise DocumentError(f"La proprietà {key} di {node.name} deve essere un testo.")
    for node in document.widgets:
        command = node.properties.get("command")
        if command and command in names:
            raise DocumentError(f"Il comando {command!r} coincide con il nome di un elemento.")
        ancestors: set[str] = {node.id}
        parent_id = node.parent
        while parent_id is not None:
            if len(ancestors) > 32:
                raise DocumentError("La gerarchia può contenere al massimo 32 livelli di contenitori.")
            if parent_id in ancestors:
                raise DocumentError("La gerarchia degli elementi contiene un ciclo.")
            ancestors.add(parent_id)
            parent = document.find(parent_id)
            if parent is None or not WIDGET_SPECS[parent.kind].container:
                raise DocumentError(f"Il contenitore di {node.name} non esiste o non è un contenitore.")
            parent_id = parent.parent


def create_widget(document: UiDocument, kind: str, parent: str | None = None,
                  x: int = 20, y: int = 20) -> WidgetNode:
    if kind not in WIDGET_SPECS:
        raise DocumentError(f"Tipo non supportato: {kind}.")
    if parent is not None:
        parent_node = document.find(parent)
        if parent_node is None or not WIDGET_SPECS[parent_node.kind].container:
            raise DocumentError("Il contenitore scelto non è valido.")
    spec = WIDGET_SPECS[kind]
    base = {"Label": "etichetta", "Button": "pulsante", "Entry": "campo", "Frame": "contenitore",
            "LabelFrame": "gruppo", "Checkbutton": "spunta", "Radiobutton": "scelta", "Combobox": "elenco",
            "Spinbox": "numero", "Separator": "separatore", "Text": "testo", "Listbox": "lista",
            "Treeview": "tabella", "Canvas": "disegno", "Scale": "cursore", "Progressbar": "avanzamento"}[kind.split(".")[1]]
    index = 1
    existing = {w.name for w in document.widgets}
    while f"{base}_{index}" in existing:
        index += 1
    node = WidgetNode(uuid.uuid4().hex, kind, f"{base}_{index}", parent, int(x), int(y),
                      spec.default_width, spec.default_height, copy.deepcopy(spec.default_properties))
    document.widgets.append(node)
    return node


def new_document() -> UiDocument:
    return UiDocument()


def default_document() -> UiDocument:
    document = UiDocument(title="La mia prima app", width=800, height=560)
    title = create_widget(document, "ttk.Label", x=40, y=36)
    title.name = "titolo"
    title.width, title.height = 660, 34
    title.properties["text"] = "La tua prossima idea comincia qui."
    title.properties["style"] = "Hero.TLabel"
    description = create_widget(document, "ttk.Label", x=40, y=78)
    description.name = "descrizione"
    description.width = 680
    description.properties["text"] = "Modifica questa interfaccia, scrivi il codice e premi Play."
    description.properties["style"] = "Muted.TLabel"
    group = create_widget(document, "ttk.LabelFrame", x=40, y=140)
    group.name = "profilo"
    group.width, group.height = 720, 244
    group.properties["text"] = "Il tuo primo programma"
    group.properties["style"] = "Card.TLabelframe"
    label = create_widget(document, "ttk.Label", group.id, 24, 38)
    label.name = "etichetta_nome"
    label.properties["text"] = "Come ti chiami?"
    label.properties["style"] = "Card.TLabel"
    entry = create_widget(document, "ttk.Entry", group.id, 24, 78)
    entry.name = "nome"
    entry.width = 420
    entry.properties["text"] = "Mondo"
    button = create_widget(document, "ttk.Button", group.id, 24, 136)
    button.name = "saluta"
    button.width = 148
    button.properties.update({"text": "Saluta", "command": "on_saluta", "style": "Accent.TButton"})
    footer = create_widget(document, "ttk.Label", x=40, y=422)
    footer.name = "suggerimento"
    footer.width, footer.height = 700, 44
    footer.properties["text"] = "Trascina un componente dalla libreria per aggiungerlo alla finestra."
    footer.properties["style"] = "Muted.TLabel"
    return document
