"""Context-aware, source-preserving Tkinter integrations.

All inspection is static.  Source is parsed and compiled for validation, never
imported or executed.  Offsets are Python string offsets; AST byte columns are
converted before applying edits so comments, formatting and Unicode survive.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
import io
import keyword
import re
import warnings
import tokenize
from typing import Iterable
import tkinter as tk
from tkinter import ttk


class IntegrationError(ValueError):
    """An integration could not be inserted without guessing or losing code."""


@dataclass(frozen=True)
class CodeContext:
    widget_name: str | None
    widget_kind: str | None
    class_name: str | None
    declaration_line: int | None
    callback_name: str | None
    source_start: int
    source_end: int


@dataclass(frozen=True)
class CodeAction:
    id: str
    title: str
    description: str


@dataclass(frozen=True)
class CodeEdit:
    source: str
    cursor_line: int
    message: str


@dataclass
class _Widget:
    context: CodeContext
    assignment: ast.Assign | ast.AnnAssign
    call: ast.Call
    class_node: ast.ClassDef | None
    method: ast.FunctionDef | ast.AsyncFunctionDef | None
    reference: str


_KINDS = {"Button", "Label", "Frame", "LabelFrame", "Entry", "Text", "Listbox", "Canvas",
          "Checkbutton", "Radiobutton", "Combobox", "Spinbox", "Scale", "Progressbar",
          "Separator", "Treeview", "Notebook", "Scrollbar", "PanedWindow", "Menu", "Toplevel"}
_COMMAND_KINDS = {"Button", "Checkbutton", "Radiobutton", "Spinbox", "Scale", "Scrollbar"}
_VALUE_KINDS = {"Entry", "Text", "Combobox", "Spinbox", "Scale", "Listbox", "Treeview", "Checkbutton", "Radiobutton"}
_TEXT_KINDS = {"Label", "Button", "Checkbutton", "Radiobutton", "LabelFrame"}
_STATE_KINDS = {"Label", "Button", "Entry", "Text", "Listbox", "Combobox", "Spinbox", "Scale", "Checkbutton", "Radiobutton", "Treeview"}
_EVENTS = {
    "bind_click": ("<Button-1>", "click", "Gestisci clic del mouse", "Collega il clic a una funzione con parametro event."),
    "bind_double_click": ("<Double-Button-1>", "double_click", "Gestisci doppio clic", "Collega il doppio clic a una funzione, conservando i binding esistenti."),
    "bind_enter": ("<Enter>", "enter", "Gestisci ingresso del mouse", "Riceve un evento quando il puntatore entra nel componente."),
    "bind_leave": ("<Leave>", "leave", "Gestisci uscita del mouse", "Riceve un evento quando il puntatore esce dal componente."),
    "bind_return": ("<Return>", "return", "Gestisci il tasto Invio", "Collega Invio a una funzione con parametro event."),
}
_EVENT_START = "# <tkstudio:events>"
_EVENT_END = "# </tkstudio:events>"
_TK_METHODS = set(dir(tk.Tk)) | set(dir(tk.Misc)) | set(dir(ttk.Widget))


def _parse(source: str):
    try:
        tree = ast.parse(source)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            compile(source, "<integrazioni>", "exec", dont_inherit=True)
        return tree
    except (SyntaxError, ValueError, TypeError) as exc:
        if isinstance(exc, SyntaxError):
            raise IntegrationError(f"Correggi prima l'errore Python alla riga {exc.lineno}: {exc.msg}.") from exc
        raise IntegrationError("Il codice non è un sorgente Python valido.") from exc


def _offset(source: str, line: int, byte_column: int = 0) -> int:
    lines = source.splitlines(keepends=True)
    if line > len(lines): return len(source)
    text = lines[max(0, line - 1)]
    return sum(map(len, lines[:max(0, line - 1)])) + len(text.encode("utf-8")[:byte_column].decode("utf-8"))


def _span(source: str, node: ast.AST) -> tuple[int, int]:
    return _offset(source, node.lineno, node.col_offset), _offset(source, node.end_lineno, node.end_col_offset)


def _line_start(source: str, line: int) -> int: return _offset(source, line)


def _after_line(source: str, line: int) -> int:
    lines = source.splitlines(keepends=True)
    return sum(map(len, lines[:line]))


def _name(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Name): return node.id
    if isinstance(node, ast.Attribute):
        base = _name(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _parents(tree: ast.AST):
    return {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}


def _ancestor(node, parents, kinds):
    while node in parents:
        node = parents[node]
        if isinstance(node, kinds): return node
    return None


def _widgets(source: str, tree: ast.Module) -> list[_Widget]:
    aliases = {"tk": "tk", "tkinter": "tk", "ttk": "ttk"}
    constructors = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "tkinter": aliases[alias.asname or "tkinter"] = "tk"
                elif alias.name == "tkinter.ttk": aliases[alias.asname or "tkinter.ttk"] = "ttk"
        elif isinstance(node, ast.ImportFrom):
            if node.module == "tkinter":
                for alias in node.names:
                    if alias.name == "ttk": aliases[alias.asname or "ttk"] = "ttk"
                    elif alias.name in _KINDS: constructors[alias.asname or alias.name] = "tk." + alias.name
            elif node.module == "tkinter.ttk":
                for alias in node.names:
                    if alias.name in _KINDS: constructors[alias.asname or alias.name] = "ttk." + alias.name
    parents = _parents(tree)
    widgets = []
    for statement in ast.walk(tree):
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            target, call = statement.targets[0], statement.value
        elif isinstance(statement, ast.AnnAssign): target, call = statement.target, statement.value
        else: continue
        if not isinstance(call, ast.Call): continue
        raw_kind = _name(call.func)
        if raw_kind in constructors: kind = constructors[raw_kind]
        elif raw_kind and "." in raw_kind:
            prefix, short = raw_kind.rsplit(".", 1)
            if prefix not in aliases or short not in _KINDS: continue
            kind = aliases[prefix] + "." + short
        else: continue
        cls = _ancestor(statement, parents, ast.ClassDef)
        method = _ancestor(statement, parents, (ast.FunctionDef, ast.AsyncFunctionDef))
        reference = _name(target)
        if cls is not None:
            if cls not in tree.body or not method or not reference or not re.fullmatch(r"self\.[^\.]+", reference): continue
            if method not in cls.body: continue
        elif statement not in tree.body or not isinstance(target, ast.Name): continue
        callback = next((item.value for item in call.keywords if item.arg == "command"), None)
        callback_ref = _name(callback)
        callback_name = callback_ref.removeprefix("self.") if callback_ref else None
        begin, end = _span(source, statement)
        context = CodeContext(target.attr if isinstance(target, ast.Attribute) else target.id, kind,
                              cls.name if cls else None, statement.lineno, callback_name, begin, end)
        widgets.append(_Widget(context, statement, call, cls, method, reference))
    return widgets


def _same_scope(node, widget: _Widget, parents):
    cls = _ancestor(node, parents, ast.ClassDef)
    if widget.class_node: return cls is widget.class_node
    return cls is None and _ancestor(node, parents, (ast.FunctionDef, ast.AsyncFunctionDef)) is None


def detect_context(source: str, position: int, selection_start: int | None = None,
                   selection_end: int | None = None) -> CodeContext | None:
    """Find one widget in the selected declaration/reference or under the cursor.

    A selection containing two declarations is intentionally ambiguous.  A
    constructor's parent reference does not count as a second selected widget.
    """
    try: tree = _parse(source)
    except IntegrationError: return None
    widgets = _widgets(source, tree)
    position = max(0, min(len(source), position))
    start = max(0, min(len(source), selection_start if selection_start is not None else position))
    end = max(0, min(len(source), selection_end if selection_end is not None else position))
    start, end = sorted((start, end))
    selected = start != end
    line = source.count("\n", 0, position) + 1
    declarations = [widget for widget in widgets if
                    (start < widget.context.source_end and end > widget.context.source_start) if selected]
    if not selected:
        declarations = [widget for widget in widgets if widget.assignment.lineno <= line <= widget.assignment.end_lineno]
        if not declarations:
            text = source.splitlines()[line - 1] if source.splitlines() else ""
            if re.fullmatch(r"\s*# widget:[A-Za-z0-9_-]+\s*", text):
                declarations = [widget for widget in widgets if widget.assignment.lineno == line + 1]
    if declarations:
        if len(declarations) != 1: return None
        result = declarations[0]
    else:
        parents = _parents(tree); references = []
        for widget in widgets:
            for node in ast.walk(tree):
                if not isinstance(node, (ast.Name, ast.Attribute)) or _name(node) != widget.reference or not _same_scope(node, widget, parents): continue
                begin, finish = _span(source, node)
                if (start < finish and end > begin) if selected else node.lineno <= line <= node.end_lineno:
                    references.append(widget); break
        unique = {(item.context.widget_name, item.context.class_name, item.context.source_start): item for item in references}
        if len(unique) != 1: return None
        result = next(iter(unique.values()))
    # Reassignments in the same scope make later insertion unsafe.
    if sum(item.context.widget_name == result.context.widget_name and item.class_node is result.class_node for item in widgets) != 1: return None
    return result.context


def _locate(source: str, tree: ast.Module, context: CodeContext) -> _Widget:
    candidates = [widget for widget in _widgets(source, tree) if widget.context == context]
    if len(candidates) != 1:
        raise IntegrationError("La selezione non corrisponde più al codice corrente. Seleziona di nuovo il componente.")
    return candidates[0]


def _methods(widget, tree):
    owner = widget.class_node if widget.class_node else tree
    return {node.name: node for node in owner.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _owned_names(owner):
    """Names that must not be shadowed by a new helper, including attributes."""
    names = {node.name for node in owner.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    if isinstance(owner, ast.ClassDef):
        for node in ast.walk(owner):
            if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store) and isinstance(node.value, ast.Name) and node.value.id == "self": names.add(node.attr)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and node in owner.body: names.add(node.id)
        names.update(_TK_METHODS)
    for statement in owner.body:
        targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target] if isinstance(statement, ast.AnnAssign) else []
        for target in targets:
            names.update(node.id for node in ast.walk(target) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store))
        if isinstance(statement, (ast.Import, ast.ImportFrom)):
            names.update(alias.asname or alias.name.split(".")[0] for alias in statement.names)
    return names


def _call_name(widget, function_name): return "self." + function_name if widget.class_node else function_name


def _callback_safe(widget):
    if any(item.arg is None for item in widget.call.keywords): return False
    command = next((item.value for item in widget.call.keywords if item.arg == "command"), None)
    if command is None or (isinstance(command, ast.Constant) and command.value in (None, "")): return True
    ref = _name(command)
    if widget.class_node: return bool(ref and ref.startswith("self.") and ref.count(".") == 1)
    return isinstance(command, ast.Name)


def _hook_anchor(widget, tree):
    if not widget.class_node: return widget.assignment
    if widget.assignment not in widget.method.body: return None
    init = _methods(widget, tree).get("__init__")
    if init is None or isinstance(init, ast.AsyncFunctionDef): return None
    if widget.method is init:
        if any(isinstance(node, ast.Return) for node in ast.walk(init)): return None
        return init.body[-1]
    for statement in init.body:
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call) and _name(statement.value.func) == "self." + widget.method.name:
            return statement
    return None


def _selection_event(widget):
    return {"Combobox": "<<ComboboxSelected>>", "Listbox": "<<ListboxSelect>>", "Treeview": "<<TreeviewSelect>>"}.get(widget.context.widget_kind.split(".")[-1])


def _binding(widget, tree, sequence):
    """Return an existing binding's simple handler, or False for dynamic ones."""
    owner = widget.class_node if widget.class_node else tree
    parents = _parents(tree)
    for node in ast.walk(owner):
        if not isinstance(node, ast.Call) or _name(node.func) != widget.reference + ".bind" or not node.args: continue
        if widget.class_node and _ancestor(node, parents, ast.ClassDef) is not widget.class_node: continue
        try: bound_sequence = ast.literal_eval(node.args[0])
        except (ValueError, TypeError): continue
        if bound_sequence == sequence:
            function = node.args[1] if len(node.args) > 1 else next((item.value for item in node.keywords if item.arg == "func"), None)
            if function is None: continue  # A bind(sequence) query does not install a handler.
            ref = _name(function)
            if not ref: return False
            if widget.class_node and ref.startswith("self.") and ref.count(".") == 1: return ref[5:]
            if not widget.class_node and isinstance(function, ast.Name): return ref
            return False
    return None


def available_actions(source: str, context: CodeContext | None) -> list[CodeAction]:
    generic = CodeAction("insert_function", "Inserisci una nuova funzione", "Aggiunge una funzione Python autonoma, senza sostituire la selezione.")
    if context is None: return [generic]
    try: tree = _parse(source); widget = _locate(source, tree, context)
    except IntegrationError: return []
    kind = context.widget_kind.split(".")[-1]; actions = []
    if kind in _COMMAND_KINDS and _callback_safe(widget):
        existing = context.callback_name
        actions.append(CodeAction("callback", f"Apri funzione {existing}" if existing else "Collega una funzione al comando", "Apre il callback già collegato, oppure crea una funzione e la collega con command."))
    event_ids = ["bind_click", "bind_double_click"]
    if kind in {"Entry", "Text", "Combobox", "Spinbox"}: event_ids.append("bind_return")
    event_ids.extend(["bind_enter", "bind_leave"])
    if _hook_anchor(widget, tree) is not None:
        for action_id in event_ids:
            sequence, _, title, description = _EVENTS[action_id]
            binding = _binding(widget, tree, sequence)
            if binding is False: continue
            actions.append(CodeAction(action_id, ("Apri gestione: " + title.lower()) if binding else title, description))
        if sequence := _selection_event(widget):
            binding = _binding(widget, tree, sequence)
            if binding is not False:
                actions.append(CodeAction("bind_selection", "Apri gestione della selezione" if binding else "Gestisci cambio di selezione", f"Collega l’evento {sequence} a una funzione con parametro event."))
    if kind in _VALUE_KINDS: actions.append(CodeAction("read_value", "Crea funzione per leggere il valore", "Inserisce una funzione che legge e restituisce il contenuto o la selezione del componente."))
    if kind in _TEXT_KINDS: actions.append(CodeAction("set_text", "Crea funzione per cambiare il testo", "Inserisce una funzione con parametro testo che aggiorna il componente."))
    if kind in _STATE_KINDS: actions.append(CodeAction("toggle_state", "Crea funzione per abilitare/disabilitare", "Inserisce una funzione con parametro attivo; non altera lo stato iniziale."))
    actions.append(CodeAction("show_message", "Crea funzione per mostrare un messaggio", "Inserisce una funzione con messagebox.showinfo pronta da richiamare."))
    return actions


def _patch(source: str, edits: Iterable[tuple[int, int, str]]) -> str:
    ordered = sorted(edits, key=lambda item: (item[0], item[1]), reverse=True)
    boundary = len(source) + 1
    for begin, end, text in ordered:
        if begin < 0 or end < begin or end > len(source) or end > boundary:
            raise IntegrationError("Le modifiche si sovrappongono. Il codice originale è stato conservato.")
        source = source[:begin] + text + source[end:]; boundary = begin
    return source


def _unique(base, names):
    if base not in names and not keyword.iskeyword(base): return base
    index = 2
    while f"{base}_{index}" in names: index += 1
    return f"{base}_{index}"


def _method_text(widget, name, parameters, body):
    indent = " " * (widget.class_node.col_offset + 4) if widget.class_node else ""
    signature = ("self" + (", " + parameters if parameters else "")) if widget.class_node else parameters
    lines = [f"{indent}def {name}({signature}):"] + [indent + "    " + line if line else "" for line in body]
    return "\n".join(lines) + "\n"


def _append_method(source, tree, widget, text):
    if widget.class_node:
        cls = widget.class_node
        following = [node for node in tree.body if node.lineno > cls.end_lineno]
        limit = min((min([node.lineno] + [item.lineno for item in getattr(node, "decorator_list", [])]) for node in following), default=len(source.splitlines()) + 1)
        lines = source.splitlines(keepends=True)
        line = cls.end_lineno + 1
        while line < limit:
            content = lines[line - 1]
            if content.strip() and not content[0].isspace(): break
            line += 1
        offset = _line_start(source, line)
    else:
        # A function used by command must exist before the constructor executes.
        offset = _line_start(source, widget.assignment.lineno)
    prefix = "" if offset == 0 or source[:offset].endswith("\n\n") else "\n"
    return offset, offset, prefix + text + "\n"


def _cursor_line(source, name, cls_name=None):
    tree = _parse(source)
    owner = next((node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == cls_name), tree) if cls_name else tree
    method = next((node for node in owner.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name), None)
    return method.lineno + 1 if method else 1


def _command_patch(source, widget, handler):
    reference = _call_name(widget, handler)
    command = next((item for item in widget.call.keywords if item.arg == "command"), None)
    if command:
        begin, end = _span(source, command.value); return begin, end, reference
    begin, end = _span(source, widget.call)
    # Insert before ')' while preserving existing argument formatting/comments.
    closing = end - 1
    inside = source[begin:closing]
    arguments = list(widget.call.args) + [item.value for item in widget.call.keywords]
    end_arg = max((_span(source, item)[1] for item in arguments), default=begin + 1)
    tail = source[end_arg:closing]
    try:
        trailing_comma = any(token.type == tokenize.OP and token.string == "," for token in tokenize.generate_tokens(io.StringIO("(" + tail + "\n)").readline))
    except tokenize.TokenError:
        raise IntegrationError("Il formato degli argomenti non è riconoscibile senza modificare il codice esistente.")
    if "\n" not in inside:
        comma = " " if trailing_comma else ", " if arguments else ""
        return closing, closing, comma + "command=" + reference
    # Multiline calls: insert a fresh keyword line before the closing line.
    line_start = source.rfind("\n", 0, closing) + 1
    closing_prefix = source[line_start:closing]
    if closing_prefix.strip():
        return closing, closing, (" " if trailing_comma else ", ") + "command=" + reference
    comma_patch = None
    if arguments and not trailing_comma:
        # Appending before an inline comment would require token rewriting.
        # Reparse a minimal suffix to see if the final argument ends first.
        comma_patch = (end_arg, end_arg, ",")
    indent = closing_prefix + "    "
    addition = (line_start, line_start, f"{indent}command={reference},\n")
    return [addition] + ([comma_patch] if comma_patch else [])


def _generated_events(source, widget):
    if not widget.class_node: return None
    lines = source.splitlines()
    return next((node for node in widget.class_node.body if isinstance(node, ast.FunctionDef)
                 and node.lineno >= 2 and lines[node.lineno - 2].strip() == _EVENT_START), None)


def _install_binding(source, tree, widget, handler, sequence):
    suffix = f"  # tkstudio:event:{widget.context.widget_name}\n"
    line = f"{widget.reference}.bind({sequence!r}, {_call_name(widget, handler)}, add='+')"
    if not widget.class_node:
        offset = _after_line(source, widget.assignment.end_lineno)
        prefix = "" if source[:offset].endswith("\n") else "\n"
        return [(offset, offset, prefix + line + suffix)]
    init = _methods(widget, tree)["__init__"]
    indent = " " * (widget.class_node.col_offset + 4)
    method = _generated_events(source, widget)
    if method:
        method_name = method.name; offset = _after_line(source, method.end_lineno)
        edits = [(offset, offset, indent + "    " + line + suffix)]
    else:
        names = _owned_names(widget.class_node)
        method_name = _unique("_tkstudio_connect_events", names)
        text = indent + _EVENT_START + "\n" + _method_text(widget, method_name, "", ['"""Eventi collegati dal menu Integrazioni di Tkinter Studio."""', line + suffix.rstrip("\n")]) + indent + _EVENT_END + "\n"
        edits = [_append_method(source, tree, widget, text)]
    hook_ref = "self." + method_name
    called = any(isinstance(node, ast.Call) and _name(node.func) == hook_ref for node in ast.walk(init))
    if not called:
        anchor = _hook_anchor(widget, tree)
        if anchor is None: raise IntegrationError("Non trovo un punto sicuro in cui collegare gli eventi dopo la creazione dei componenti.")
        offset = _after_line(source, anchor.end_lineno)
        prefix = "" if source[:offset].endswith("\n") else "\n"
        edits.append((offset, offset, prefix + indent + "    " + hook_ref + "()\n"))
    return edits


def _find_named_function(tree, name, cls):
    owner = cls if cls else tree
    return next((node for node in owner.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name), None)


def _generated_helper(source, tree, widget, action_id):
    owner = widget.class_node if widget.class_node else tree
    lines = source.splitlines()
    for node in owner.body:
        if not isinstance(node, ast.FunctionDef) or node.lineno < 2: continue
        if lines[node.lineno - 2].strip() != "# tkstudio:helper:" + action_id: continue
        if any(isinstance(item, ast.Attribute) and (_name(item) or "").startswith(widget.reference + ".") for item in ast.walk(node)): return node
    return None


def apply_action(source: str, context: CodeContext | None, action_id: str) -> CodeEdit:
    tree = _parse(source)
    if context is None:
        if action_id != "insert_function": raise IntegrationError("Seleziona prima il codice di un componente Tkinter.")
        names = _owned_names(tree)
        name = _unique("nuova_funzione", names)
        # Insert before a main guard, so the helper is defined before application startup.
        guard = next((node for node in tree.body if isinstance(node, ast.If) and "__name__" in (ast.get_source_segment(source, node.test) or "")), None)
        offset = _line_start(source, guard.lineno) if guard else len(source)
        prefix = "" if offset == 0 else "\n\n"
        output = _patch(source, [(offset, offset, prefix + f"def {name}():\n    \"\"\"Descrivi qui lo scopo della funzione.\"\"\"\n    pass\n\n")])
        _parse(output)
        return CodeEdit(output, _cursor_line(output, name), "Funzione inserita. Sostituisci pass con il tuo codice.")
    widget = _locate(source, tree, context)
    if action_id not in {item.id for item in available_actions(source, context)}:
        raise IntegrationError("Questa integrazione non è disponibile per il componente selezionato.")
    methods = _methods(widget, tree)
    names = _owned_names(widget.class_node if widget.class_node else tree)
    short = context.widget_kind.split(".")[-1]
    helper_action = action_id in {"read_value", "set_text", "toggle_state", "show_message"}
    if helper_action and (existing_helper := _generated_helper(source, tree, widget, action_id)):
        return CodeEdit(source, existing_helper.lineno + 1, "Funzione già presente; il codice è stato conservato.")
    edits = []; parameters = ""; handler = None
    if action_id == "callback":
        if context.callback_name:
            handler = context.callback_name
            if method := methods.get(handler): return CodeEdit(source, method.lineno + 1, "Callback esistente aperto; il codice è stato conservato.")
            if widget.class_node and (handler in _TK_METHODS or not handler.startswith("on_")):
                return CodeEdit(source, context.declaration_line, "Il callback è già collegato, ma la sua definizione non è locale. Il codice è stato conservato.")
            if not widget.class_node and handler in names:
                return CodeEdit(source, context.declaration_line, "Il callback è già collegato, ma la sua definizione non è locale. Il codice è stato conservato.")
        else: handler = _unique("on_" + context.widget_name, names)
        parameters = "value" if short in {"Scale", "Scrollbar"} else ""
        if short == "Scrollbar": parameters = "*args"
        body = [f"# Scrivi qui il comportamento di {context.widget_name}.", f"print({('Comando: ' + context.widget_name)!r})"]
        patch = _command_patch(source, widget, handler)
        edits.extend(patch if isinstance(patch, list) else [patch])
    elif action_id.startswith("bind_"):
        if action_id == "bind_selection": sequence, suffix = _selection_event(widget), "selection"
        else: sequence, suffix, _, _ = _EVENTS[action_id]
        existing = _binding(widget, tree, sequence)
        if existing:
            if method := methods.get(existing): return CodeEdit(source, method.lineno + 1, "Gestione evento già presente; il codice è stato conservato.")
            if widget.class_node and (existing in _TK_METHODS or not existing.startswith("on_")):
                return CodeEdit(source, context.declaration_line, "L’evento è già collegato a una funzione non locale. Il codice è stato conservato.")
            if not widget.class_node and existing in names:
                return CodeEdit(source, context.declaration_line, "L’evento è già collegato a una funzione non locale. Il codice è stato conservato.")
            handler = existing
        else: handler = _unique(f"on_{context.widget_name}_{suffix}", names)
        parameters = "event"
        body = [f"# Evento {sequence} su {context.widget_name}.", f"print({('Evento: ' + context.widget_name + ' ' + sequence)!r})"]
        # Apply the hookup first; reparsing gives accurate offsets for the function insertion.
        output = source if existing else _patch(source, _install_binding(source, tree, widget, handler, sequence))
        tree = _parse(output)
        fresh = next(item for item in _widgets(output, tree) if item.context.widget_name == context.widget_name and item.context.class_name == context.class_name)
        output = _patch(output, [_append_method(output, tree, fresh, _method_text(fresh, handler, parameters, body))])
        _parse(output)
        return CodeEdit(output, _cursor_line(output, handler, context.class_name), f"Evento {sequence} collegato. Scrivi il comportamento nella funzione evidenziata.")
    elif action_id == "read_value":
        handler = "leggi_" + context.widget_name
        ref = widget.reference
        local_names = {context.widget_name} if not widget.class_node else set()
        index_name, item_name = _unique("indice", local_names), _unique("elemento", local_names)
        value_name = _unique("valore", local_names)
        expression = f"{ref}.get()"
        if short == "Text": expression = f"{ref}.get('1.0', 'end-1c')"
        elif short == "Listbox": expression = f"[{ref}.get({index_name}) for {index_name} in {ref}.curselection()]"
        elif short == "Treeview": expression = f"[{ref}.item({item_name}, 'values') for {item_name} in {ref}.selection()]"
        elif short in {"Checkbutton", "Radiobutton"}:
            expression = f"{ref}.instate(('selected',))" if context.widget_kind.startswith("ttk.") else f"{ref}.getvar({ref}.cget('variable'))"
        body = [f"{value_name} = {expression}", f"return {value_name}"]
    elif action_id == "set_text":
        parameter_name = _unique("testo", {context.widget_name} if not widget.class_node else set())
        handler = "aggiorna_testo_" + context.widget_name; parameters = parameter_name + "='Nuovo testo'"
        body = [f"{widget.reference}.configure(text={parameter_name})"]
    elif action_id == "toggle_state":
        parameter_name = _unique("attivo", {context.widget_name} if not widget.class_node else set())
        handler = "abilita_" + context.widget_name; parameters = parameter_name + "=True"
        body = [f"{widget.reference}.state(['!disabled'] if {parameter_name} else ['disabled'])"] if context.widget_kind.startswith("ttk.") else [f"{widget.reference}.configure(state='normal' if {parameter_name} else 'disabled')"]
    elif action_id == "show_message":
        local_names = {context.widget_name} if not widget.class_node else set()
        parameter_name = _unique("testo", local_names); alias = _unique("_tkstudio_messagebox", local_names)
        handler = "mostra_messaggio_" + context.widget_name; parameters = parameter_name + "='Operazione completata.'"
        body = [f"from tkinter import messagebox as {alias}", f"{alias}.showinfo('Messaggio', {parameter_name}, parent={widget.reference}.winfo_toplevel())"]
    else: raise IntegrationError("Integrazione sconosciuta.")
    if action_id != "callback" and handler in methods:
        return CodeEdit(source, methods[handler].lineno + 1, "Funzione già presente; il codice è stato conservato.")
    if action_id != "callback": handler = _unique(handler, names)
    helper_marker = ((" " * (widget.class_node.col_offset + 4) if widget.class_node else "") + "# tkstudio:helper:" + action_id + "\n") if helper_action else ""
    edits.append(_append_method(source, tree, widget, helper_marker + _method_text(widget, handler, parameters, body)))
    output = _patch(source, edits); _parse(output)
    return CodeEdit(output, _cursor_line(output, handler, context.class_name), "Funzione inserita. Puoi completarla nel codice evidenziato.")


def reconcile_integrations(source: str, existing_widget_names: Iterable[str]) -> str:
    """Drop only tagged, generated event hookups whose widget was deleted.

    Handler bodies are deliberately retained, as are untagged user bindings.
    This operation does not infer or remove arbitrary user references.
    """
    tree = _parse(source); names = set(existing_widget_names); lines = source.splitlines(keepends=True); edits = []
    for cls in (node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "App"):
        for method in (node for node in cls.body if isinstance(node, ast.FunctionDef) and node.lineno >= 2 and lines[node.lineno - 2].strip() == _EVENT_START):
            for statement in method.body:
                if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call): continue
                call = statement.value; ref = _name(call.func)
                if not ref or not re.fullmatch(r"self\.[^\.]+\.bind", ref): continue
                name = ref.split(".")[1]
                if name in names: continue
                segment = "".join(lines[statement.lineno - 1:statement.end_lineno])
                if "# tkstudio:event:" not in segment: continue
                edits.append((_line_start(source, statement.lineno), _after_line(source, statement.end_lineno), ""))
    output = _patch(source, edits); _parse(output); return output
