"""Static source edits and actual Tkinter hookups for context integrations."""
from __future__ import annotations

import ast
import io
import unittest
from contextlib import redirect_stdout

from tkstudio.codegen import generate_document, rename_widget_references
from tkstudio.integrations import (CodeContext, IntegrationError, available_actions,
                                   apply_action, detect_context, reconcile_integrations)
from tkstudio.model import UiDocument, WIDGET_SPECS, create_widget, default_document
from tkstudio.sync import source_to_document


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.doc = default_document()
        self.source = generate_document(self.doc)

    def context(self, source=None, name="saluta"):
        source = source or self.source
        needle = "self." + name + " ="
        return detect_context(source, source.index(needle))

    def test_detects_constructor_placement_and_indentation(self):
        for needle in ("self.saluta =", "self.saluta.place", "        self.saluta ="):
            with self.subTest(needle=needle):
                context = detect_context(self.source, self.source.index(needle))
                self.assertEqual(context.widget_name, "saluta")
                self.assertEqual(context.widget_kind, "ttk.Button")
                self.assertEqual(context.callback_name, "on_saluta")

    def test_constructor_selection_ignores_parent_reference_but_multiple_widgets_are_ambiguous(self):
        first = self.source.index("self.etichetta_nome =")
        end = self.source.index("self.etichetta_nome.place", first)
        self.assertEqual(detect_context(self.source, first, first, end).widget_name, "etichetta_nome")
        end = self.source.index("self.nome.place", end)
        self.assertIsNone(detect_context(self.source, first, first, end))

    def test_invalid_code_is_not_executed_or_offered_as_widget(self):
        self.assertIsNone(detect_context("print('NEVER')\nif", 0))
        with self.assertRaises(IntegrationError): apply_action("return 3", None, "insert_function")

    def test_arbitrary_code_is_not_executed_during_inspection(self):
        source = "raise RuntimeError('must not run')\n" + self.source
        self.assertEqual(self.context(source).widget_name, "saluta")
        self.assertTrue(available_actions(source, self.context(source)))

    def test_stale_context_is_rejected(self):
        context = self.context()
        with self.assertRaises(IntegrationError): apply_action("# shifted\n" + self.source, context, "set_text")

    def test_aliased_imports_and_module_widget_are_detected(self):
        for prefix, constructor, expected in (
            ("import tkinter as gui", "gui.Button", "tk.Button"),
            ("from tkinter.ttk import Button as Action", "Action", "ttk.Button"),
            ("from tkinter import ttk as themed", "themed.Button", "ttk.Button"),
        ):
            source = f"{prefix}\nbutton = {constructor}(text='Vai')\n"
            with self.subTest(constructor=constructor):
                self.assertEqual(detect_context(source, source.index("button =")).widget_kind, expected)

    def test_existing_callback_is_opened_without_changes(self):
        edit = apply_action(self.source, self.context(), "callback")
        self.assertEqual(edit.source, self.source)
        self.assertIn("nome = self.nome.get()", edit.source.splitlines()[edit.cursor_line - 1])

    def test_missing_command_is_wired_and_callback_is_idempotent(self):
        doc = UiDocument(); node = create_widget(doc, "ttk.Button"); source = generate_document(doc)
        context = self.context(source, node.name)
        edit = apply_action(source, context, "callback")
        self.assertIn(f"command=self.on_{node.name}", edit.source)
        self.assertEqual(source_to_document(edit.source).find(node.id).properties["command"], "on_" + node.name)
        repeat = apply_action(edit.source, self.context(edit.source, node.name), "callback")
        self.assertEqual(edit.source, repeat.source)

    def test_scale_callback_accepts_the_value_argument(self):
        doc = UiDocument(); node = create_widget(doc, "ttk.Scale"); source = generate_document(doc)
        edit = apply_action(source, self.context(source, node.name), "callback")
        self.assertIn(f"def on_{node.name}(self, value):", edit.source)

    def test_dynamic_callback_is_never_overwritten(self):
        source = self.source.replace("command=self.on_saluta", "command=lambda: print('personalizzato')")
        actions = {item.id for item in available_actions(source, self.context(source))}
        self.assertNotIn("callback", actions)
        with self.assertRaises(IntegrationError): apply_action(source, self.context(source), "callback")
        self.assertIn("command=lambda", source)

    def test_inherited_callback_does_not_shadow_tk_destroy(self):
        source = self.source.replace("command=self.on_saluta", "command=self.destroy")
        edit = apply_action(source, self.context(source), "callback")
        self.assertEqual(edit.source, source)
        self.assertNotIn("def destroy", edit.source)

    def test_command_insertion_preserves_multiline_comments_and_trailing_commas(self):
        for call in (
            "ttk.Button(self, text='Vai',)",
            "ttk.Button(\n            self,\n            text='Vai',  # testo utente\n        )",
            "ttk.Button(\n            self,\n            text='Vai'  # testo utente\n        )",
            "ttk.Button(\n            self, text='Vai',)",
        ):
            source = "from tkinter import ttk\nclass App:\n    def __init__(self):\n        self.pulsante = " + call + "\n"
            with self.subTest(call=call):
                edit = apply_action(source, self.context(source, "pulsante"), "callback")
                compile(edit.source, "<test>", "exec")
                self.assertIn("command=self.on_pulsante", edit.source)
                if "# testo utente" in source: self.assertIn("# testo utente", edit.source)

    def test_binding_is_outside_ui_region_and_survives_regeneration(self):
        edit = apply_action(self.source, self.context(name="etichetta_nome"), "bind_click")
        document = source_to_document(edit.source)
        regenerated = generate_document(document, edit.source)
        self.assertIn("self.etichetta_nome.bind('<Button-1>'", regenerated)
        self.assertIn("def on_etichetta_nome_click(self, event):", regenerated)
        ui = regenerated.split("# <tkstudio:ui>")[1].split("# </tkstudio:ui>")[0]
        self.assertNotIn(".bind(", ui)
        self.assertEqual(regenerated.count("self._tkstudio_connect_events()"), 1)
        self.assertEqual(document.to_dict(), source_to_document(regenerated).to_dict())

    def test_multiple_events_have_one_hook_and_repeated_action_does_not_duplicate(self):
        edit = apply_action(self.source, self.context(), "bind_click")
        second = apply_action(edit.source, self.context(edit.source), "bind_enter")
        repeated = apply_action(second.source, self.context(second.source), "bind_click")
        self.assertEqual(second.source, repeated.source)
        self.assertEqual(second.source.count("self._tkstudio_connect_events()"), 1)
        self.assertEqual(second.source.count("def _tkstudio_connect_events("), 1)

    def test_widget_specific_events_and_read_helpers(self):
        for kind, expected in (("ttk.Entry", "bind_return"), ("ttk.Combobox", "bind_selection"), ("tk.Listbox", "bind_selection"), ("ttk.Treeview", "bind_selection")):
            doc = UiDocument(); node = create_widget(doc, kind); source = generate_document(doc)
            with self.subTest(kind=kind):
                context = self.context(source, node.name)
                self.assertIn(expected, {item.id for item in available_actions(source, context)})
                edit = apply_action(source, context, expected)
                self.assertEqual(len(source_to_document(edit.source).widgets), 1)
                read = apply_action(edit.source, self.context(edit.source, node.name), "read_value")
                compile(read.source, "<test>", "exec")

    def test_all_available_actions_for_every_widget_compile_and_preserve_visual_model(self):
        for kind in WIDGET_SPECS:
            doc = UiDocument(); node = create_widget(doc, kind); source = generate_document(doc)
            context = self.context(source, node.name)
            for action in available_actions(source, context):
                with self.subTest(kind=kind, action=action.id):
                    edit = apply_action(source, context, action.id)
                    compile(edit.source, "<test>", "exec")
                    self.assertEqual(len(source_to_document(edit.source).widgets), 1)

    def test_unicode_offsets_and_user_strings_are_preserved(self):
        source = self.source.replace("text='Saluta'", "text='Caffè ☕, ciao'")
        source = source.replace("nome = self.nome.get()", "# caffè ☕ e self.saluta restano qui\n        nome = self.nome.get()")
        edit = apply_action(source, self.context(source), "bind_click")
        self.assertIn("text='Caffè ☕, ciao'", edit.source)
        self.assertIn("# caffè ☕ e self.saluta restano qui", edit.source)
        self.assertIn("nome = self.nome.get()", edit.source)

    def test_module_callbacks_and_bindings_are_defined_before_use(self):
        source = "import tkinter as tk\nfrom tkinter import ttk\nroot = tk.Tk()\nbutton = ttk.Button(root, text='Vai')\nroot.mainloop()\n"
        context = detect_context(source, source.index("button ="))
        for action in ("callback", "bind_click"):
            with self.subTest(action=action):
                edit = apply_action(source, context, action)
                self.assertLess(edit.source.index("def on_button"), edit.source.index("button ="))
                if action == "bind_click": self.assertLess(edit.source.index("button.bind("), edit.source.index("root.mainloop()"))

    def test_namespace_collisions_choose_unique_idempotent_helpers(self):
        source = self.source.replace("        self.build_ui()", "        self.leggi_nome = 42\n        self.build_ui()")
        edit = apply_action(source, self.context(source, "nome"), "read_value")
        self.assertIn("def leggi_nome_2(self):", edit.source)
        repeat = apply_action(edit.source, self.context(edit.source, "nome"), "read_value")
        self.assertEqual(repeat.source, edit.source)
        source = "nuova_funzione = 42\n"
        self.assertIn("def nuova_funzione_2():", apply_action(source, None, "insert_function").source)

    def test_generic_function_is_before_main_guard_and_preserves_source(self):
        edit = apply_action(self.source, None, "insert_function")
        self.assertLess(edit.source.index("def nuova_funzione"), edit.source.index("if __name__"))
        self.assertIn(self.source.split("if __name__")[0].strip(), edit.source)
        self.assertEqual(len(source_to_document(edit.source).widgets), 7)

    def test_reconcile_after_rename_and_delete_removes_only_generated_binding(self):
        edit = apply_action(self.source, self.context(name="etichetta_nome"), "bind_click")
        renamed = rename_widget_references(edit.source, "etichetta_nome", "nome_etichetta")
        remaining = {node.name for node in self.doc.widgets} - {"etichetta_nome"}
        output = reconcile_integrations(renamed, remaining)
        self.assertNotIn("self.nome_etichetta.bind(", output)
        self.assertIn("def on_etichetta_nome_click(self, event):", output)
        self.assertIn("self._tkstudio_connect_events()", output)
        compile(output, "<test>", "exec")

    def test_dynamic_existing_binding_and_conditional_widget_are_not_modified(self):
        source = self.source.replace("        self._configure_styles()", "        self._configure_styles()\n        self.saluta.bind('<Button-1>', lambda event: print('utente'))")
        self.assertNotIn("bind_click", {item.id for item in available_actions(source, self.context(source))})
        source = "from tkinter import ttk\nclass App:\n    def __init__(self):\n        if False:\n            self.test = ttk.Label(self)\n"
        context = self.context(source, "test")
        self.assertFalse(any(action.id.startswith("bind_") for action in available_actions(source, context)))

    def test_actual_tk_helpers_and_binding_registration(self):
        source = self.source
        for name, action in (("etichetta_nome", "bind_click"), ("etichetta_nome", "set_text"), ("nome", "read_value"), ("saluta", "toggle_state")):
            source = apply_action(source, self.context(source, name), action).source
        namespace = {"__name__": "tkstudio_integration_test"}
        exec(compile(source, "<trusted-generated-fixture>", "exec"), namespace)
        app = namespace["App"]()
        try:
            app.withdraw(); app.update_idletasks()
            self.assertTrue(app.etichetta_nome.bind("<Button-1>"))
            app.aggiorna_testo_etichetta_nome("Aggiornato")
            self.assertEqual(app.etichetta_nome.cget("text"), "Aggiornato")
            self.assertEqual(app.leggi_nome(), "Mondo")
            app.abilita_saluta(False); self.assertTrue(app.saluta.instate(("disabled",)))
            app.abilita_saluta(True); self.assertFalse(app.saluta.instate(("disabled",)))
        finally: app.destroy()


if __name__ == "__main__": unittest.main()
