import ast
import copy
import json
import unittest

from tkstudio.codegen import generate_document, GenerationError, rename_widget_references
from tkstudio.model import (DocumentError, UiDocument, WIDGET_SPECS, create_widget,
                            default_document, new_document, validate_document)
from tkstudio.sync import source_to_document, SyncError


class ModelTests(unittest.TestCase):
    def test_json_roundtrip_and_clone_are_independent(self):
        doc = default_document()
        restored = UiDocument.from_dict(json.loads(json.dumps(doc.to_dict(), ensure_ascii=False)))
        self.assertEqual(restored.to_dict(), doc.to_dict())
        cloned = doc.clone()
        cloned.widgets[0].properties['text'] = 'Diverso'
        self.assertNotEqual(cloned.widgets[0].properties, doc.widgets[0].properties)

    def test_reject_invalid_names_duplicates_and_parent_cycle(self):
        for name in ('class', 'bad name', 'title', 'winfo_width', '_private', ''):
            doc = new_document()
            widget = create_widget(doc, 'ttk.Button')
            widget.name = name
            with self.assertRaises(DocumentError):
                validate_document(doc)
        doc = new_document()
        first = create_widget(doc, 'ttk.Frame')
        second = create_widget(doc, 'ttk.Frame', first.id)
        first.parent = second.id
        with self.assertRaises(DocumentError):
            validate_document(doc)

    def test_reject_unknown_properties_and_unsupported_version(self):
        doc = new_document()
        create_widget(doc, 'ttk.Button').properties['made_up'] = True
        with self.assertRaises(DocumentError):
            validate_document(doc)
        with self.assertRaises(DocumentError):
            UiDocument.from_dict({'schema_version': 99})


class GenerationTests(unittest.TestCase):
    def test_all_widget_types_compile_and_roundtrip(self):
        doc = new_document()
        for index, kind in enumerate(WIDGET_SPECS):
            create_widget(doc, kind, x=20 + (index % 3) * 250, y=20 + (index // 3) * 80)
        source = generate_document(doc)
        ast.parse(source)
        self.assertEqual(source_to_document(source).to_dict(), doc.to_dict())

    def test_default_document_roundtrip(self):
        doc = default_document()
        source = generate_document(doc)
        self.assertIn('messagebox.showinfo', source)
        self.assertEqual(source_to_document(source).to_dict(), doc.to_dict())

    def test_label_font_and_colors_are_supported_and_roundtrip(self):
        document = new_document()
        label = create_widget(document, "ttk.Label")
        label.properties.update({"font": ["Segoe UI", 16, "bold"], "foreground": "#00aa88", "background": "#ffffff"})
        validate_document(document)
        self.assertEqual(source_to_document(generate_document(document)).to_dict(), document.to_dict())

    def test_escaping_and_nested_parent_order(self):
        doc = new_document()
        frame = create_widget(doc, 'ttk.Frame')
        label = create_widget(doc, 'ttk.Label', frame.id)
        label.properties['text'] = "L'apostrofo, le virgolette \" e la nuova\nriga: è così!"
        doc.widgets.reverse()
        source = generate_document(doc)
        result = source_to_document(source)
        self.assertEqual(result.find(label.id).properties['text'], label.properties['text'])
        self.assertEqual(result.find(label.id).parent, frame.id)

    def test_preserve_user_handler_and_add_new_stub(self):
        doc = default_document()
        source = generate_document(doc).replace("        nome = self.nome.get().strip() or 'Mondo'",
                                                "        print('mio codice personale')\n        nome = self.nome.get().strip() or 'Mondo'")
        button = create_widget(doc, 'ttk.Button', x=30, y=400)
        button.properties['command'] = 'on_nuovo'
        doc.widgets[0].properties['text'] = 'Titolo cambiato'
        changed = generate_document(doc, source)
        self.assertIn("print('mio codice personale')", changed)
        self.assertIn('def on_nuovo(self):', changed)
        self.assertEqual(changed.count('def on_saluta('), 1)
        self.assertEqual(source_to_document(changed).to_dict(), doc.to_dict())

    def test_managed_block_markers_cannot_be_lost_silently(self):
        doc = new_document()
        source = generate_document(doc).replace('# <tkstudio:ui>', '# marker rimosso')
        with self.assertRaises(GenerationError):
            generate_document(doc, source)
        with self.assertRaises(SyncError):
            source_to_document(source)

    def test_rename_widget_updates_callback_but_preserves_strings_comments_and_unicode(self):
        document = default_document()
        source = generate_document(document)
        source = source.replace("        nome = self.nome.get().strip() or 'Mondo'",
                                "        testo = 'è un nome: self.nome'; valore = self.nome.get()  # self.nome resta nel commento\n"
                                "        nome = self.nome.get().strip() or 'Mondo'")
        renamed = rename_widget_references(source, "nome", "nome_utente")
        self.assertIn("testo = 'è un nome: self.nome'; valore = self.nome_utente.get()  # self.nome resta nel commento", renamed)
        self.assertIn("nome = self.nome_utente.get().strip()", renamed)
        self.assertIn("self.nome_utente = ttk.Entry", renamed)
        self.assertIn("self.nome_utente.insert", renamed)
        node = next(node for node in document.widgets if node.name == "nome")
        node.name = "nome_utente"
        regenerated = generate_document(document, renamed)
        self.assertIn("nome = self.nome_utente.get().strip()", regenerated)
        self.assertEqual(source_to_document(regenerated).to_dict(), document.to_dict())

    def test_rename_widget_preserves_unrelated_helper_classes(self):
        source = generate_document(default_document())
        source += "\nclass Helper:\n    def __init__(self):\n        self.nome = 'proprietà indipendente'\n"
        renamed = rename_widget_references(source, "nome", "nome_utente")
        self.assertIn("self.nome = 'proprietà indipendente'", renamed)
        with self.assertRaises(GenerationError):
            rename_widget_references(source, "nome", "destroy")

    def test_rename_checkbutton_also_updates_its_generated_variable_binding(self):
        document = new_document()
        node = create_widget(document, "ttk.Checkbutton")
        old = node.name
        source = generate_document(document)
        renamed = rename_widget_references(source, old, "consenso")
        node.name = "consenso"
        self.assertIn("self._var_consenso = tk.BooleanVar", renamed)
        self.assertIn("variable=self._var_consenso", renamed)
        self.assertNotIn(f"self._var_{old}", renamed)
        self.assertEqual(source_to_document(renamed).to_dict(), document.to_dict())
        self.assertEqual(source_to_document(generate_document(document, renamed)).to_dict(), document.to_dict())

    def test_disabled_initial_content_roundtrips_and_is_present_in_real_tk_controls(self):
        import tkinter as tk
        document = new_document()
        for kind in ("ttk.Entry", "ttk.Spinbox", "tk.Text"):
            node = create_widget(document, kind)
            node.properties.update({"text": "Testo iniziale è corretto", "state": "disabled"})
        source = generate_document(document)
        self.assertEqual(source_to_document(source).to_dict(), document.to_dict())
        namespace = {"__name__": "tkstudio_test_generated"}
        exec(compile(source, "<generated Tkinter test>", "exec"), namespace)
        try:
            app = namespace["App"]()
        except tk.TclError as exc:
            if "no display name" in str(exc) or "couldn't connect to display" in str(exc):
                self.skipTest("Tkinter necessita di un display per la verifica runtime.")
            raise
        try:
            app.withdraw()
            for node in document.widgets:
                widget = getattr(app, node.name)
                value = widget.get("1.0", "end-1c") if node.kind == "tk.Text" else widget.get()
                self.assertEqual(value, node.properties["text"])
                self.assertEqual(str(widget.cget("state")), "disabled")
        finally:
            app.destroy()


class SynchronizationTests(unittest.TestCase):
    def test_literal_code_edits_update_position_text_title_and_identity(self):
        doc = default_document()
        source = generate_document(doc)
        source = source.replace("self.title('La mia prima app')", "self.title('Titolo modificato')")
        source = source.replace('self.saluta.place(x=24, y=136, width=148, height=36)',
                                'self.saluta.place(x=32, y=144, width=170, height=42)')
        source = source.replace("text='Saluta'", "text='Premimi'")
        changed = source_to_document(source, doc)
        button = next(node for node in changed.widgets if node.name == 'saluta')
        self.assertEqual(changed.title, 'Titolo modificato')
        self.assertEqual((button.x, button.y, button.width, button.height), (32, 144, 170, 42))
        self.assertEqual(button.properties['text'], 'Premimi')
        self.assertEqual(button.id, next(node.id for node in doc.widgets if node.name == 'saluta'))

    def test_unsupported_dynamic_ui_is_rejected_without_executing(self):
        doc = default_document()
        before = copy.deepcopy(doc.to_dict())
        original = generate_document(doc)
        cases = [original.replace("text='Saluta'", "text=str(1 + 2)"),
                 original.replace('command=self.on_saluta', 'command=lambda: print(1)'),
                 original.replace('self.saluta.place(x=24', 'self.saluta.place(x=some_function()'),
                 original.replace('        self.title(', "        raise RuntimeError('NON ESEGUIRE')\n        self.title(")]
        for source in cases:
            with self.assertRaises(SyncError):
                source_to_document(source, doc)
        self.assertEqual(doc.to_dict(), before)
        with self.assertRaises(GenerationError):
            generate_document(doc, cases[0])

    def test_custom_code_outside_managed_region_is_accepted(self):
        source = generate_document(default_document())
        source = source.replace('    def on_saluta(self):',
                                '    def my_business_logic(self):\n        return [x * 2 for x in range(5)]\n\n    def on_saluta(self):')
        doc = source_to_document(source)
        self.assertEqual(len(doc.widgets), 7)


if __name__ == '__main__':
    unittest.main()
