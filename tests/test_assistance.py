"""Assistenza senza esecuzione: CPython, guida contestuale e suggerimenti."""
import ast
from pathlib import Path
import tempfile
import unittest
import warnings

from tkstudio.assistance import analyze_source, help_for_symbol, completion_words


class SyntaxAssistanceTests(unittest.TestCase):
    def test_valid_code_has_no_errors_and_is_not_executed(self):
        with tempfile.TemporaryDirectory() as directory:
            sentinel = Path(directory) / "never-created.txt"
            source = f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('executed')\nraise RuntimeError('not executed')\n"
            self.assertEqual(analyze_source(source), [])
            self.assertFalse(sentinel.exists())

    def test_missing_colon_has_precise_location_and_help(self):
        source = "nome = 'Ada'\nif nome\n    print(nome)\n"
        result = analyze_source(source)
        self.assertEqual(len(result), 1)
        diagnostic = result[0]
        self.assertEqual(diagnostic.severity, "error")
        self.assertEqual(diagnostic.line, 2)
        self.assertEqual(diagnostic.column, 8)
        self.assertIn(":", diagnostic.hint)
        self.assertGreater(diagnostic.end_column, diagnostic.column)

    def test_compile_catches_context_errors_that_ast_parse_accepts(self):
        for source in ("return 2\n", "break\n", "continue\n", "nonlocal missing\n", "await work()\n", "def f(a, a):\n    pass\n"):
            with self.subTest(source=source):
                ast.parse(source)
                result = analyze_source(source)
                self.assertEqual(result[0].severity, "error")
                self.assertEqual(result[0].code, "SyntaxError")

    def test_indentation_and_tab_errors_have_useful_hints(self):
        for source in ("def f():\npass\n", "if True:\n\tprint(1)\n        print(2)\n"):
            with self.subTest(source=source):
                diagnostic = analyze_source(source)[0]
                self.assertIn("Indentazione", diagnostic.message)
                self.assertIn("spazi" if diagnostic.code == "TabError" else "rientro", diagnostic.hint)

    def test_syntax_warning_is_collected_without_polluting_filters(self):
        old_filters = list(warnings.filters)
        result = analyze_source("value = 1 is 1\n")
        self.assertTrue(result)
        self.assertEqual(result[0].severity, "warning")
        self.assertEqual(result[0].code, "SyntaxWarning")
        self.assertIn("==", result[0].hint)
        self.assertEqual(warnings.filters, old_filters)

    def test_unicode_offsets_and_multiple_lines_remain_codepoints(self):
        source = "nome = '🙂'\nè = 'ok'; valore =\n"
        error = analyze_source(source)[0]
        try: compile(source, "test.py", "exec")
        except SyntaxError as expected:
            self.assertEqual((error.line, error.column), (expected.lineno, expected.offset))
        else: self.fail("Expected SyntaxError")

    def test_nul_and_surrogate_input_are_reported_without_crash(self):
        for source in ("nome = 1\n\x00", "nome = '\ud800'\n"):
            with self.subTest(source=repr(source)):
                result = analyze_source(source)
                self.assertEqual(result[0].severity, "error")
                self.assertGreaterEqual(result[0].line, 1)
                self.assertGreaterEqual(result[0].column, 1)

    def test_first_compile_error_is_reported_without_runtime_name_checks(self):
        self.assertEqual(analyze_source("missing_function()\n"), [])
        self.assertEqual(analyze_source("import module_not_installed_anywhere\n"), [])
        self.assertEqual(len(analyze_source("if x\n    y =\n")), 1)


class ContextHelpTests(unittest.TestCase):
    SOURCE = """import tkinter as ui
from tkinter import ttk as themed
from tkinter import Text as Area
class App(ui.Tk):
    def __init__(self):
        self.campo = themed.Entry(self)
        self.testo = Area(self)
        self.azione = themed.Button(self, text='Salva', command=self.on_salva)
    def on_salva(self, event=None):
        valore = self.campo.get()
        contenuto = self.testo.get('1.0', 'end-1c')
        print(event.widget)
"""

    def help_at(self, fragment, offset=0):
        position = self.SOURCE.index(fragment) + offset
        return help_for_symbol(self.SOURCE, position)

    def test_alias_constructor_and_assigned_widget_reference_are_resolved(self):
        self.assertIn("ttk.Entry", self.help_at("themed.Entry", len("themed.")).title)
        self.assertIn("ttk.Entry", self.help_at("self.campo.get", len("self.")).title)
        self.assertIn("tk.Text", self.help_at("Area(self)").title)

    def test_entry_and_text_get_have_different_correct_signatures(self):
        entry = self.help_at("self.campo.get", len("self.campo."))
        text = self.help_at("self.testo.get", len("self.testo."))
        self.assertEqual(entry.signature, "widget.get()")
        self.assertEqual(text.signature, "widget.get('1.0', 'end-1c')")

    def test_command_help_explains_reference_and_event_arguments(self):
        result = self.help_at("command=")
        self.assertIn("senza", result.body)
        self.assertIn("event", result.body)
        self.assertIn("command=", result.signature)

    def test_event_field_and_python_keyword_help_are_available_offline(self):
        self.assertIn("Evento Tkinter", self.help_at("event.widget", len("event.")).title)
        self.assertIn("funzione", self.help_at("def on_salva").title)

    def test_own_function_help_uses_signature_and_docstring_without_executing(self):
        source = "def converti(testo: str, minimo=0):\n    '''Converte il valore inserito.'''\n    raise RuntimeError('not called')\n\nconverti('12')\n"
        result = help_for_symbol(source, source.rindex("converti"))
        self.assertIn("testo: str", result.signature)
        self.assertIn("minimo=0", result.signature)
        self.assertEqual(result.body, "Converte il valore inserito.")

    def test_local_function_help_takes_precedence_over_a_builtin_with_same_name(self):
        source = "def print(dato):\n    '''Scrittura personalizzata.'''\n    pass\n\nprint(2)\n"
        result = help_for_symbol(source, source.rindex("print"))
        self.assertEqual(result.signature, "def print(dato)")
        self.assertEqual(result.body, "Scrittura personalizzata.")

    def test_incomplete_source_and_unknown_symbol_have_useful_fallbacks(self):
        for source, position in (("if ", 0), ("unknown_name()", 3), ("", 0), ("def f(:", 7)):
            result = help_for_symbol(source, position)
            self.assertTrue(result.title)
            self.assertTrue(result.body)
            self.assertTrue(result.url.startswith("https://docs.python.org/"))

    def test_unicode_before_method_does_not_break_ast_byte_offsets(self):
        source = "import tkinter as tk\ncampo = tk.Entry()\netichetta = '🙂 è'; campo.get()\n"
        result = help_for_symbol(source, source.rindex("get"))
        self.assertEqual(result.title, "Entry.get")

    def test_completions_include_own_identifiers_even_in_incomplete_file(self):
        source = self.SOURCE + "\nrisultato_personale =\n"
        words = completion_words(source)
        for word in ("on_salva", "campo", "risultato_personale", "Entry", "bind", "return"):
            self.assertIn(word, words)
        self.assertEqual(words, sorted(set(words)))
        self.assertNotIn("self.campo", words)


if __name__ == "__main__": unittest.main()
