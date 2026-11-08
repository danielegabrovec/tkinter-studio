"""Parse the managed, declarative Tkinter subset without executing user code."""
from __future__ import annotations

import ast
import re
import uuid
from .codegen import GenerationError, UI_START, UI_END, managed_region
from .model import DocumentError, UiDocument, WidgetNode, WIDGET_SPECS, validate_document


class SyncError(ValueError):
    """Source must remain authoritative until the user fixes its managed region."""


def _attr(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _attr(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _literal(node: ast.AST, context: str) -> object:
    try:
        value = ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError) as exc:
        raise SyncError(f"{context}: il designer supporta valori letterali (testi, numeri, elenchi), non espressioni dinamiche.") from exc
    return value


def _keywords(call: ast.Call, context: str) -> dict:
    result = {}
    for keyword in call.keywords:
        if keyword.arg is None or keyword.arg in result:
            raise SyncError(f"{context}: espansioni ** e proprietà duplicate non sono supportate dal designer.")
        result[keyword.arg] = _literal(keyword.value, context)
    return result


def source_to_document(source: str, current_document: UiDocument | None = None) -> UiDocument:
    try:
        begin, end = managed_region(source)
        tree = ast.parse(source)
    except GenerationError as exc:
        raise SyncError(str(exc)) from exc
    except SyntaxError as exc:
        raise SyncError(f"Errore Python alla riga {exc.lineno}: {exc.msg}. Correggilo prima di aggiornare il designer.") from exc
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "App"]
    if len(classes) != 1:
        raise SyncError("Il designer richiede una classe App con il metodo build_ui.")
    region_start_line = source.count("\n", 0, begin) + 1
    region_end_line = source.count("\n", 0, end)
    methods = [node for node in classes[0].body if isinstance(node, ast.FunctionDef) and node.name == "build_ui"
               and region_start_line < node.lineno < region_end_line]
    if len(methods) != 1:
        raise SyncError("Il metodo build_ui deve essere presente una sola volta tra i marcatori del designer.")
    method = methods[0]
    if method.decorator_list or len(method.args.args) != 1 or method.args.args[0].arg != "self" or method.args.defaults:
        raise SyncError("La firma di build_ui deve essere def build_ui(self), senza decoratori.")
    region_nodes = [node for node in classes[0].body if region_start_line < node.lineno < region_end_line]
    if region_nodes != [method]:
        raise SyncError("La regione del designer può contenere soltanto il metodo build_ui.")
    document = UiDocument()
    by_name: dict[str, WidgetNode] = {}
    previous = {node.name: node for node in current_document.widgets} if current_document else {}
    placed: set[str] = set()
    root_seen: set[str] = set()
    lines = source.splitlines()
    generated_vars: set[str] = set()
    for statement in method.body:
        line = statement.lineno
        if isinstance(statement, ast.Pass):
            continue
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1 and isinstance(statement.value, ast.Call):
            target = _attr(statement.targets[0])
            call = statement.value
            kind = _attr(call.func)
            if target in ("self._tkstudio_radio",) or (target and target.startswith("self._var_")):
                expected_kind = "tk.StringVar" if target == "self._tkstudio_radio" else "tk.BooleanVar"
                expected_value = "" if expected_kind == "tk.StringVar" else False
                if kind != expected_kind or call.args or _keywords(call, f"Riga {line}") != {"value": expected_value}:
                    raise SyncError(f"Riga {line}: la variabile generata è stata modificata in modo non rappresentabile.")
                generated_vars.add(target)
                continue
            if kind not in WIDGET_SPECS or not target or not target.startswith("self.") or target.count(".") != 1:
                raise SyncError(f"Riga {line}: assegnazione non supportata dal designer. Sposta la logica fuori da build_ui.")
            name = target[5:]
            if name in by_name:
                raise SyncError(f"Riga {line}: il nome {name} è duplicato.")
            if len(call.args) != 1:
                raise SyncError(f"Riga {line}: ogni elemento deve indicare un solo contenitore.")
            parent_ref = _attr(call.args[0])
            if parent_ref == "self":
                parent = None
            elif parent_ref and parent_ref.startswith("self.") and parent_ref[5:] in by_name:
                parent = by_name[parent_ref[5:]].id
            else:
                raise SyncError(f"Riga {line}: contenitore non riconosciuto o definito dopo il figlio.")
            properties = {}
            for keyword in call.keywords:
                key = keyword.arg
                if key is None or key in properties:
                    raise SyncError(f"Riga {line}: proprietà duplicate o espansioni ** non supportate.")
                if key == "command":
                    command = _attr(keyword.value)
                    if not command or not command.startswith("self.") or command.count(".") != 1:
                        raise SyncError(f"Riga {line}: command deve essere un metodo, per esempio self.on_click.")
                    properties[key] = command[5:]
                elif key == "variable":
                    variable = _attr(keyword.value)
                    expected = "self._tkstudio_radio" if kind == "ttk.Radiobutton" else f"self._var_{name}"
                    if kind not in ("ttk.Checkbutton", "ttk.Radiobutton") or variable != expected or variable not in generated_vars:
                        raise SyncError(f"Riga {line}: variabile non rappresentabile nel designer.")
                else:
                    properties[key] = _literal(keyword.value, f"Riga {line}, proprietà {key}")
            # Content helpers aren't constructor options but remain editable properties.
            if kind in ("ttk.Entry", "ttk.Spinbox", "ttk.Combobox", "tk.Text"):
                properties.setdefault("text", "")
            if kind == "tk.Listbox":
                properties["items"] = []
            if "command" in WIDGET_SPECS[kind].default_properties:
                properties.setdefault("command", "")
            widget_id = None
            if line >= 2:
                marker = re.fullmatch(r"\s*# widget:([A-Za-z0-9_-]{1,128})\s*", lines[line - 2])
                if marker:
                    widget_id = marker.group(1)
            if widget_id is None:
                widget_id = previous[name].id if name in previous else uuid.uuid4().hex
            node = WidgetNode(widget_id, kind, name, parent, properties=properties)
            document.widgets.append(node)
            by_name[name] = node
            continue
        if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call):
            raise SyncError(f"Riga {line}: istruzione dinamica non supportata. Scrivila fuori da build_ui; il codice è stato conservato.")
        call = statement.value
        function = _attr(call.func)
        if function in ("self.title", "self.geometry", "self.configure"):
            operation = function.split(".")[1]
            if operation in root_seen:
                raise SyncError(f"Riga {line}: configurazione della finestra duplicata.")
            root_seen.add(operation)
            if operation in ("title", "geometry"):
                if len(call.args) != 1 or call.keywords:
                    raise SyncError(f"Riga {line}: {operation} richiede un valore letterale.")
                value = _literal(call.args[0], f"Riga {line}")
                if operation == "title":
                    document.title = value
                else:
                    match = re.fullmatch(r"(\d+)x(\d+)", str(value))
                    if not match:
                        raise SyncError(f"Riga {line}: la geometria deve avere il formato '800x560'.")
                    document.width, document.height = map(int, match.groups())
            else:
                options = _keywords(call, f"Riga {line}")
                if call.args or set(options) != {"background"}:
                    raise SyncError(f"Riga {line}: il designer supporta configure(background=...).")
                document.background = options["background"]
            continue
        if not function or len(function.split(".")) != 3 or not function.startswith("self."):
            raise SyncError(f"Riga {line}: chiamata non supportata dal designer.")
        _, name, operation = function.split(".")
        if name not in by_name:
            raise SyncError(f"Riga {line}: elemento {name} non riconosciuto.")
        node = by_name[name]
        if operation == "place":
            if name in placed or call.args:
                raise SyncError(f"Riga {line}: ogni elemento deve avere una sola chiamata place.")
            options = _keywords(call, f"Riga {line}")
            if set(options) != {"x", "y", "width", "height"}:
                raise SyncError(f"Riga {line}: place richiede x, y, width e height in pixel.")
            for key, value in options.items():
                setattr(node, key, value)
            placed.add(name)
        elif operation == "insert" and node.kind in ("ttk.Entry", "ttk.Spinbox", "tk.Text", "tk.Listbox"):
            if len(call.args) != 2 or call.keywords:
                raise SyncError(f"Riga {line}: contenuto insert non riconosciuto.")
            value = _literal(call.args[1], f"Riga {line}")
            index = _attr(call.args[0]) if isinstance(call.args[0], ast.Attribute) else _literal(call.args[0], f"Riga {line}")
            if node.kind == "tk.Listbox" and index == "tk.END":
                node.properties["items"].append(value)
            elif node.kind in ("ttk.Entry", "ttk.Spinbox") and index == 0 and not node.properties.get("text"):
                node.properties["text"] = value
            elif node.kind == "tk.Text" and index == "1.0" and not node.properties.get("text"):
                node.properties["text"] = value
            else:
                raise SyncError(f"Riga {line}: inserimento di testo dinamico o multiplo non rappresentabile.")
        elif operation == "set" and node.kind == "ttk.Combobox" and len(call.args) == 1 and not call.keywords:
            node.properties["text"] = _literal(call.args[0], f"Riga {line}")
        elif operation == "configure" and node.kind in ("ttk.Entry", "ttk.Spinbox", "tk.Text"):
            options = _keywords(call, f"Riga {line}")
            if call.args or set(options) != {"state"} or "state" in node.properties:
                raise SyncError(f"Riga {line}: configure è supportato qui solo per lo stato finale dopo il testo iniziale.")
            node.properties["state"] = options["state"]
        elif operation == "heading" and node.kind == "ttk.Treeview" and len(call.args) == 1:
            column = _literal(call.args[0], f"Riga {line}")
            options = _keywords(call, f"Riga {line}")
            expected = str(column).replace("_", " ").capitalize()
            if column not in node.properties.get("columns", []) or options != {"text": expected}:
                raise SyncError(f"Riga {line}: intestazione tabella personalizzata non rappresentabile. Spostala fuori da build_ui.")
        else:
            raise SyncError(f"Riga {line}: {operation} non è supportato nel blocco del designer.")
    if placed != set(by_name):
        raise SyncError("Ogni elemento deve avere una chiamata place con coordinate e dimensioni.")
    if root_seen != {"title", "geometry", "configure"}:
        raise SyncError("Mancano titolo, geometria o colore della finestra nel blocco del designer.")
    try:
        validate_document(document)
    except DocumentError as exc:
        raise SyncError(str(exc)) from exc
    return document
