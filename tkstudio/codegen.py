"""Generate standalone Tkinter Python without overwriting user-owned code."""
from __future__ import annotations

import ast
import re
from .model import UiDocument, WidgetNode, validate_document, valid_identifier

UI_START = "# <tkstudio:ui>"
UI_END = "# </tkstudio:ui>"
HANDLERS_START = "# <tkstudio:handlers>"
HANDLERS_END = "# </tkstudio:handlers>"


class GenerationError(ValueError):
    pass


def rename_widget_references(source: str, old: str, new: str) -> str:
    """Rename actual ``self.old`` references without touching strings/comments.

    References are scoped to App, whose attributes are the visual widgets.
    Dynamic lookups such as getattr(self, 'old') cannot be refactored statically
    and remain user-owned. Python AST columns use UTF-8 byte offsets, so they
    must be converted before slicing source containing Italian or other Unicode.
    """
    if not valid_identifier(old) or not valid_identifier(new):
        raise GenerationError("Il nome del componente deve essere un identificatore Python valido e non riservato.")
    if old == new:
        return source
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise GenerationError(f"Correggi prima l'errore Python alla riga {exc.lineno}: {exc.msg}.") from exc
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "App"]
    if len(classes) != 1:
        raise GenerationError("La classe App non è riconoscibile. Il codice è stato conservato.")
    replacements = {old: new}
    # Checkbuttons own a generated BooleanVar with a matching attribute name.
    # Keep that binding and any explicit user access to it coherent on rename.
    variable_name = f"_var_{old}"
    for statement in ast.walk(classes[0]):
        if (isinstance(statement, ast.Assign) and len(statement.targets) == 1
                and isinstance(statement.targets[0], ast.Attribute)
                and isinstance(statement.targets[0].value, ast.Name)
                and statement.targets[0].value.id == "self" and statement.targets[0].attr == variable_name
                and isinstance(statement.value, ast.Call)
                and isinstance(statement.value.func, ast.Attribute)
                and isinstance(statement.value.func.value, ast.Name)
                and statement.value.func.value.id == "tk" and statement.value.func.attr == "BooleanVar"):
            replacements[variable_name] = f"_var_{new}"
            break
    lines = source.splitlines(keepends=True)
    offsets = []
    offset = 0
    for line in lines:
        offsets.append(offset)
        offset += len(line)
    edits = []

    class ReferenceVisitor(ast.NodeVisitor):
        def visit_ClassDef(self, node):
            # A nested helper class owns its own `self`, not App's widgets.
            return

        def visit_Attribute(self, node):
            if (isinstance(node.value, ast.Name) and node.value.id == "self"
                    and node.attr in replacements and node.end_lineno is not None):
                text = lines[node.end_lineno - 1]
                prefix = text.encode("utf-8")[:node.end_col_offset].decode("utf-8")
                end = offsets[node.end_lineno - 1] + len(prefix)
                start = end - len(node.attr)
                if source[start:end] != node.attr:
                    raise GenerationError("Il nome Unicode non è rappresentabile in modo univoco. Il codice è stato conservato.")
                edits.append((start, end, replacements[node.attr]))
            self.generic_visit(node)

    visitor = ReferenceVisitor()
    for statement in classes[0].body:
        visitor.visit(statement)
    result = source
    for start, end, replacement in sorted(set(edits), reverse=True):
        result = result[:start] + replacement + result[end:]
    return result


def managed_region(source: str, start: str = UI_START, end: str = UI_END) -> tuple[int, int]:
    lines = source.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line.strip() == start]
    ends = [i for i, line in enumerate(lines) if line.strip() == end]
    if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
        raise GenerationError("I marcatori del designer sono assenti, duplicati o non validi. Il codice è stato conservato.")
    return sum(len(line) for line in lines[:starts[0]]), sum(len(line) for line in lines[:ends[0] + 1])


def _ordered(document: UiDocument) -> list[WidgetNode]:
    output: list[WidgetNode] = []
    done: set[str] = set()

    def visit(node: WidgetNode) -> None:
        if node.id in done:
            return
        if node.parent is not None:
            visit(document.find(node.parent))
        output.append(node)
        done.add(node.id)

    for node in document.widgets:
        visit(node)
    return output


def _ui_block(document: UiDocument) -> str:
    lines = [f"    {UI_START}", "    def build_ui(self):", f"        self.title({document.title!r})",
             f"        self.geometry({f'{document.width}x{document.height}'!r})",
             f"        self.configure(background={document.background!r})"]
    radio_nodes = [node for node in document.widgets if node.kind == "ttk.Radiobutton"]
    if radio_nodes:
        lines.append("        self._tkstudio_radio = tk.StringVar(value='')")
    for node in _ordered(document):
        parent = "self" if node.parent is None else f"self.{document.find(node.parent).name}"
        text = node.properties.get("text", "")
        deferred_state = (node.properties.get("state") if text and node.kind in ("ttk.Entry", "ttk.Spinbox", "tk.Text")
                          and node.properties.get("state", "normal") != "normal" else None)
        options = []
        for key, value in node.properties.items():
            if key == "command":
                if value:
                    options.append(f"command=self.{value}")
            elif key == "text" and node.kind in ("ttk.Entry", "ttk.Spinbox", "ttk.Combobox", "tk.Text"):
                continue
            elif key == "items":
                continue
            elif key == "state" and deferred_state is not None:
                # Disabled/readonly controls reject insert(); initialize their
                # content first, then apply the requested final state.
                continue
            else:
                options.append(f"{key}={value!r}")
        if node.kind == "ttk.Checkbutton":
            lines.append(f"        self._var_{node.name} = tk.BooleanVar(value=False)")
            options.append(f"variable=self._var_{node.name}")
        elif node.kind == "ttk.Radiobutton":
            options.append("variable=self._tkstudio_radio")
        suffix = ", " + ", ".join(options) if options else ""
        lines.extend(["", f"        # widget:{node.id}", f"        self.{node.name} = {node.kind}({parent}{suffix})",
                      f"        self.{node.name}.place(x={node.x}, y={node.y}, width={node.width}, height={node.height})"])
        if text and node.kind in ("ttk.Entry", "ttk.Spinbox"):
            lines.append(f"        self.{node.name}.insert(0, {text!r})")
        elif text and node.kind == "ttk.Combobox":
            lines.append(f"        self.{node.name}.set({text!r})")
        elif text and node.kind == "tk.Text":
            lines.append(f"        self.{node.name}.insert('1.0', {text!r})")
        if deferred_state is not None:
            lines.append(f"        self.{node.name}.configure(state={deferred_state!r})")
        if node.kind == "tk.Listbox" and node.properties.get("items"):
            for value in node.properties["items"]:
                lines.append(f"        self.{node.name}.insert(tk.END, {value!r})")
        if node.kind == "ttk.Treeview":
            for column in node.properties.get("columns", []):
                lines.append(f"        self.{node.name}.heading({column!r}, text={str(column).replace('_', ' ').capitalize()!r})")
    lines.append(f"    {UI_END}")
    return "\n".join(lines) + "\n"


def _handler_stub(command: str, document: UiDocument) -> str:
    args = "self, *args" if any(node.kind == "ttk.Scale" and node.properties.get("command") == command
                                for node in document.widgets) else "self"
    if command == "on_saluta" and any(node.name == "nome" and node.kind == "ttk.Entry" for node in document.widgets):
        return (f"    def {command}({args}):\n"
                "        nome = self.nome.get().strip() or 'Mondo'\n"
                "        messagebox.showinfo('Ciao!', f'Ciao, {nome}!')\n")
    return (f"    def {command}({args}):\n"
            "        # Scrivi qui il comportamento del pulsante o dell'evento.\n"
            f"        print({('Evento: ' + command)!r})\n")


def generate_document(document: UiDocument, existing_source: str | None = None) -> str:
    validate_document(document)
    ui = _ui_block(document)
    commands = list(dict.fromkeys(str(node.properties["command"]) for node in document.widgets if node.properties.get("command")))
    if existing_source is None:
        handlers = "\n".join(_handler_stub(command, document) for command in commands)
        if not handlers:
            handlers = "    # Aggiungi qui le tue funzioni e collega il nome nella proprietà command.\n"
        return ("\"\"\"Applicazione Tkinter creata con TkStudio.\n\n"
                "Il designer aggiorna solo la regione tkstudio:ui.\n"
                "Scrivi le tue funzioni fuori da quella regione.\n\"\"\"\n"
                "import tkinter as tk\nfrom tkinter import ttk, messagebox\n\n\n"
                "class App(tk.Tk):\n"
                "    def __init__(self):\n"
                "        super().__init__()\n"
                "        self.build_ui()\n"
                "        self._configure_styles()\n\n"
                "    def _configure_styles(self):\n"
                "        style = ttk.Style(self)\n"
                "        if 'clam' in style.theme_names():\n"
                "            style.theme_use('clam')\n"
                "        style.configure('.', font=('Segoe UI', 10), background=self.cget('background'), foreground='#202b40')\n"
                "        style.configure('Hero.TLabel', font=('Segoe UI', 20, 'bold'))\n"
                "        style.configure('Muted.TLabel', foreground='#67748c')\n"
                "        style.configure('Card.TLabelframe', background='#ffffff', bordercolor='#e0e5ef', relief='solid', borderwidth=1)\n"
                "        style.configure('Card.TLabelframe.Label', background='#ffffff', foreground='#34415b', font=('Segoe UI', 10, 'bold'))\n"
                "        style.configure('Card.TLabel', background='#ffffff')\n"
                "        style.configure('TEntry', fieldbackground='#ffffff', padding=5)\n"
                "        style.configure('TButton', padding=7)\n"
                "        style.configure('Accent.TButton', background='#5267db', foreground='#ffffff', font=('Segoe UI', 10, 'bold'))\n"
                "        style.map('Accent.TButton', background=[('active', '#4255c4'), ('pressed', '#3546ad')])\n\n"
                + ui + "\n" + f"    {HANDLERS_START}\n" + handlers + f"    {HANDLERS_END}\n\n\n"
                "if __name__ == '__main__':\n"
                "    app = App()\n"
                "    app.mainloop()\n")
    try:
        tree = ast.parse(existing_source)
    except SyntaxError as exc:
        raise GenerationError(f"Correggi prima l'errore Python alla riga {exc.lineno}: {exc.msg}. Il codice è stato conservato.") from exc
    # Never erase executable statements or dynamic expressions added by hand
    # to the designer region. The caller can keep editing/running that source.
    from .sync import source_to_document, SyncError
    try:
        source_to_document(existing_source)
    except SyncError as exc:
        raise GenerationError(str(exc)) from exc
    begin, end = managed_region(existing_source)
    output = existing_source[:begin] + ui + existing_source[end:]
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "App"]
    if len(classes) != 1:
        raise GenerationError("La classe App non è riconoscibile. Il codice è stato conservato.")
    methods = {node.name for node in classes[0].body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    missing = [command for command in commands if command not in methods]
    if missing:
        begin_handlers, end_handlers = managed_region(output, HANDLERS_START, HANDLERS_END)
        end_marker = output.rfind("    " + HANDLERS_END, begin_handlers, end_handlers)
        if end_marker < 0:
            raise GenerationError("Il blocco delle funzioni non è valido. Il codice è stato conservato.")
        output = output[:end_marker] + "\n" + "\n".join(_handler_stub(command, document) for command in missing) + output[end_marker:]
    try:
        ast.parse(output)
    except SyntaxError as exc:
        raise GenerationError(f"Il codice rigenerato non è valido: {exc.msg}.") from exc
    return output
