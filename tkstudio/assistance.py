"""Assistenza Python/Tkinter locale: compilazione statica e schede contestuali.

Le coordinate pubbliche sono in caratteri Python, non in unità UTF-16 Qt.
Il controllo compila il testo ma non esegue mai il codice né i suoi import.
"""
from __future__ import annotations

import ast
import builtins
from dataclasses import dataclass
import io
import keyword
import re
import tokenize
import warnings


PYTHON_DOCS = "https://docs.python.org/3.14/"
TK_DOCS = PYTHON_DOCS + "library/tkinter.html"
TTK_DOCS = PYTHON_DOCS + "library/tkinter.ttk.html"


@dataclass(frozen=True)
class Diagnostic:
    severity: str
    message: str
    line: int
    column: int
    end_line: int | None = None
    end_column: int | None = None
    hint: str = ""
    code: str = ""


@dataclass(frozen=True)
class HelpEntry:
    title: str
    signature: str
    body: str
    example: str
    url: str


def _syntax_hint(message: str, error_type: type[BaseException]) -> str:
    if error_type is TabError or "tabs and spaces" in message:
        return "Usa spazi in modo uniforme: Tab nell’editor inserisce 4 spazi. Non mescolare tabulazioni e spazi nello stesso blocco."
    if issubclass(error_type, IndentationError):
        return "Dopo una riga che termina con ':' il corpo va indentato. Mantieni lo stesso rientro nelle righe dello stesso blocco."
    checks = [
        ("expected ':'", "Aggiungi ':' alla fine della dichiarazione o della condizione, poi indenta il corpo del blocco."),
        ("was never closed", "Chiudi la parentesi indicata. Controlla anche le righe successive e le coppie (), [] e {}."),
        ("unterminated", "Chiudi la stringa con lo stesso tipo di virgolette. Per un testo su più righe usa triple virgolette oppure '\\n'."),
        ("outside function", "Questa istruzione richiede una funzione: scrivila nel corpo di un 'def', con il rientro corretto."),
        ("outside async function", "Usa 'await' dentro una funzione dichiarata 'async def'; un normale callback Tkinter non avvia automaticamente una coroutine."),
        ("outside loop", "Usa 'break' o 'continue' soltanto dentro un ciclo 'for' o 'while'."),
        ("not properly in loop", "Usa 'continue' soltanto dentro un ciclo 'for' o 'while'."),
        ("no binding for nonlocal", "Il nome dichiarato 'nonlocal' deve esistere in una funzione esterna. Per un attributo dell’app usa invece 'self.nome'."),
        ("nonlocal declaration not allowed", "La dichiarazione 'nonlocal' è valida soltanto nelle funzioni annidate, per un nome della funzione esterna."),
        ("duplicate argument", "Ogni parametro di una funzione deve avere un nome diverso."),
        ("cannot assign", "A sinistra di '=' deve esserci una destinazione valida, per esempio un nome o 'self.nome'. Per confrontare valori usa '=='."),
        ("perhaps you forgot a comma", "Separa gli elementi o gli argomenti con una virgola. Controlla la zona evidenziata e la riga precedente."),
        ("unmatched", "Questa parentesi di chiusura non corrisponde a una parentesi aperta. Controlla l’ordine di (), [] e {}."),
        ("null bytes", "Rimuovi il carattere nullo dal testo. Incolla nuovamente la riga come normale testo Python."),
        ("__future__", "Gli import 'from __future__' vanno all’inizio del file, dopo l’eventuale docstring e prima degli altri comandi."),
    ]
    for fragment, hint in checks:
        if fragment in message:
            return hint
    return "Controlla la riga indicata e quella precedente: parentesi, virgolette, virgole, ':' e rientri devono essere completi."


def _position_for_index(source: str, index: int) -> tuple[int, int]:
    prefix = source[:max(0, index)]
    return prefix.count("\n") + 1, len(prefix.rsplit("\n", 1)[-1]) + 1


def analyze_source(source: str, filename: str = "<editor>") -> list[Diagnostic]:
    """Restituisce il primo errore di compilazione e gli eventuali SyntaxWarning.

    È il controllo sintattico di CPython in uso nell’IDE. Non controlla i nomi a
    runtime, non carica librerie e non avvia il programma.
    """
    diagnostics: list[Diagnostic] = []
    with warnings.catch_warnings(record=True) as emitted:
        warnings.simplefilter("always", SyntaxWarning)
        try:
            compile(source, filename, "exec", dont_inherit=True)
        except SyntaxError as exc:
            message = exc.msg or str(exc)
            line = max(1, exc.lineno or 1)
            column = max(1, exc.offset or 1)
            if "\x00" in source and exc.lineno is None:
                line, column = _position_for_index(source, source.index("\x00"))
            end_line = max(line, exc.end_lineno or line)
            end_column = exc.end_offset if exc.end_offset and exc.end_offset > 0 else column + 1
            if end_line == line: end_column = max(column + 1, end_column)
            kind = type(exc).__name__
            prefix = "Indentazione non valida" if isinstance(exc, IndentationError) else "Errore di sintassi"
            diagnostics.append(Diagnostic("error", f"{prefix}: {message}", line, column, end_line, end_column,
                                          _syntax_hint(message, type(exc)), kind))
        except (ValueError, UnicodeError) as exc:
            diagnostics.append(Diagnostic("error", f"Testo Python non valido: {exc}", 1, 1, 1, 2,
                                          "Controlla i caratteri incollati nel file e salvalo come testo UTF-8.", type(exc).__name__))
        except (RecursionError, MemoryError, OverflowError) as exc:
            diagnostics.append(Diagnostic("error", "Il testo è troppo complesso per il controllo sintattico.", 1, 1, 1, 2,
                                          "Riduci la profondità delle espressioni o dividi il codice in funzioni e moduli.", type(exc).__name__))
    for item in emitted:
        if not issubclass(item.category, SyntaxWarning): continue
        message = str(item.message)
        if '"is"' in message or "'is'" in message:
            hint = "Per confrontare il valore di due oggetti usa '=='. 'is' confronta l’identità degli oggetti, per esempio 'valore is None'."
        elif "escape" in message:
            hint = "Controlla le barre inverse nella stringa. Per un percorso usa una stringa raw, per esempio r'C:\\dati', oppure raddoppia '\\\\'."
        else: hint = "Il codice può compilare, ma questa espressione è sospetta: controlla il significato del comando."
        diagnostics.append(Diagnostic("warning", f"Avviso Python: {message}", max(1, item.lineno or 1), 1,
                                      max(1, item.lineno or 1), None, hint, item.category.__name__))
    return sorted(diagnostics, key=lambda item: (item.line, item.column, item.severity != "error"))


def _help(title, signature, body, example="", url=TK_DOCS):
    return HelpEntry(title, signature, body, example, url)


_WIDGET_HELP: dict[str, tuple[str, str, str]] = {
    "Tk": ("Finestra principale", "tk.Tk()", "Crea la finestra principale e il relativo interprete Tcl/Tk. Avvia il ciclo degli eventi con mainloop()."),
    "Toplevel": ("Finestra aggiuntiva", "tk.Toplevel(parent)", "Apre un’altra finestra nello stesso programma. In genere usa un solo Tk e aggiungi le altre finestre con Toplevel."),
    "Button": ("Pulsante", "ttk.Button(parent, text='Salva', command=self.on_salva)", "Richiama una funzione quando viene attivato. In command passa il riferimento alla funzione, senza parentesi: self.on_salva."),
    "Label": ("Etichetta", "ttk.Label(parent, text='Titolo')", "Mostra un testo o un’immagine. Cambia il testo con configure(text='...'); per gli stili ttk puoi usare ttk.Style."),
    "Entry": ("Campo di testo", "ttk.Entry(parent)", "Contiene una sola riga modificabile. get() legge il contenuto; delete(0, 'end') lo svuota e insert(0, testo) lo inserisce."),
    "Frame": ("Contenitore", "ttk.Frame(parent, padding=8)", "Raggruppa altri componenti. Specifica questo frame come parent dei suoi figli; il layout dei figli è relativo al contenitore."),
    "LabelFrame": ("Gruppo con titolo", "ttk.LabelFrame(parent, text='Dati')", "È un contenitore con un titolo. I componenti al suo interno usano il gruppo come parent."),
    "Checkbutton": ("Casella di spunta", "ttk.Checkbutton(parent, text='Accetto', variable=self.scelta, command=self.on_scelta)", "Rappresenta un’opzione selezionabile. Collega una BooleanVar o IntVar e leggila con get(); conserva la variabile come attributo dell’app."),
    "Radiobutton": ("Scelta singola", "ttk.Radiobutton(parent, text='A', variable=self.scelta, value='a')", "Più radiobutton condividono la stessa variabile e hanno value diversi. La variabile contiene il valore della scelta attiva."),
    "Combobox": ("Elenco a discesa", "ttk.Combobox(parent, values=['Uno', 'Due'], state='readonly')", "Offre una scelta da un elenco. get() legge il testo, set(testo) lo imposta; l’evento <<ComboboxSelected>> segnala una selezione dell’utente."),
    "Spinbox": ("Selettore numerico", "ttk.Spinbox(parent, from_=0, to=100, increment=1)", "Offre un campo con frecce per cambiare il valore. get() restituisce testo: converti esplicitamente in int o float quando serve."),
    "Text": ("Area di testo", "tk.Text(parent, wrap='word')", "Gestisce testo su più righe. Gli indici sono 'riga.colonna', con riga da 1 e colonna da 0. get('1.0', 'end-1c') legge il testo senza la nuova riga finale aggiunta da Tk."),
    "Listbox": ("Elenco", "tk.Listbox(parent)", "Mostra una lista di elementi. insert('end', testo) aggiunge un elemento; curselection() restituisce gli indici selezionati e get(indice) ne legge il testo."),
    "Canvas": ("Area di disegno", "tk.Canvas(parent, background='white')", "Ospita forme, immagini e testo disegnati. I metodi create_rectangle, create_line e create_text restituiscono l’identificativo dell’elemento."),
    "Treeview": ("Tabella e albero", "ttk.Treeview(parent, columns=('nome', 'valore'), show='headings')", "Visualizza righe e gerarchie. heading() imposta le intestazioni; insert('', 'end', values=(...)) aggiunge una riga; selection() restituisce gli ID selezionati."),
    "Scale": ("Cursore", "ttk.Scale(parent, from_=0, to=100, command=self.on_valore)", "Permette di regolare un valore. Il callback di command riceve il valore come argomento; get() legge il valore corrente."),
    "Progressbar": ("Barra di avanzamento", "ttk.Progressbar(parent, maximum=100, value=0)", "Mostra un avanzamento numerico. configure(value=50) cambia il valore; start() e stop() controllano l’animazione, utile con mode='indeterminate'."),
    "Separator": ("Separatore", "ttk.Separator(parent, orient='horizontal')", "È una linea che separa gruppi di controlli. Dimensioni e posizione sono assegnate dal gestore di layout."),
    "Notebook": ("Pagine a schede", "ttk.Notebook(parent)", "Raggruppa frame in schede. add(frame, text='Titolo') aggiunge una pagina; <<NotebookTabChanged>> segnala un cambio della scheda selezionata."),
    "StringVar": ("Variabile di testo Tkinter", "tk.StringVar(master=parent, value='')", "Collega un valore a uno o più widget con textvariable o variable. Usa get() e set(); conserva un riferimento alla variabile per mantenerla attiva."),
    "BooleanVar": ("Variabile booleana Tkinter", "tk.BooleanVar(master=parent, value=False)", "Collega un valore vero/falso a un controllo, per esempio un checkbutton. Usa get() e set() e conserva la variabile come attributo."),
    "IntVar": ("Variabile intera Tkinter", "tk.IntVar(master=parent, value=0)", "Collega un numero intero a un controllo Tkinter. get() legge il valore e set(numero) lo aggiorna."),
    "DoubleVar": ("Variabile numerica Tkinter", "tk.DoubleVar(master=parent, value=0.0)", "Collega un valore decimale a un controllo Tkinter. get() restituisce il numero e set(numero) lo aggiorna."),
    "Style": ("Stili ttk", "ttk.Style(parent)", "Configura l’aspetto dei componenti ttk. configure('Nome.TButton', ...) definisce uno stile; map(...) può variare l’aspetto negli stati active e disabled."),
}

_COMMON_HELP: dict[str, HelpEntry] = {
    "command": _help("Collega un’azione", "command=self.on_click", "Passa il riferimento alla funzione senza parentesi, per richiamarla solo all’attivazione del controllo. Per Button il metodo può avere solo self; per Scale il callback riceve anche il valore. Gli eventi collegati con bind ricevono invece un oggetto event.", "def on_click(self):\n    print('Pulsante premuto')\n\n# Nel costruttore del pulsante:\ncommand=self.on_click"),
    "bind": _help("Collega un evento", "widget.bind('<Return>', self.on_invio, add='+')", "Associa un evento a un callback che riceve un oggetto event. add='+' conserva gli altri binding esistenti. Una funzione può restituire 'break' per fermare la propagazione dell’evento.", "def on_invio(self, event):\n    print(event.widget)\n\nself.nome.bind('<Return>', self.on_invio, add='+')", TK_DOCS + "#bindings-and-events"),
    "configure": _help("Modifica le proprietà", "widget.configure(text='Nuovo testo')", "Imposta proprietà supportate dal componente. configure() senza argomenti descrive le opzioni; cget('nome') legge una proprietà. Per i widget ttk molte scelte grafiche si impostano con ttk.Style.", "self.etichetta_nome.configure(text='Nome completo')"),
    "config": _help("Modifica le proprietà", "widget.config(text='Nuovo testo')", "config è un alias di configure: imposta le opzioni supportate dal componente.", "self.etichetta_nome.config(text='Nome completo')"),
    "place": _help("Posizione in pixel", "widget.place(x=20, y=20, width=160, height=32)", "Posiziona il controllo nel suo contenitore. Il designer di Tkinter Studio usa place con coordinate e dimensioni in pixel; le coordinate dei figli sono relative al contenitore.", "self.nome.place(x=24, y=78, width=420, height=34)"),
    "grid": _help("Layout a griglia", "widget.grid(row=0, column=0, sticky='ew', padx=8, pady=8)", "Dispone i controlli in righe e colonne. Non combinare grid e pack per i figli dello stesso contenitore. Il designer attuale di Tkinter Studio usa place: un layout grid scritto a mano resta utilizzabile come codice.", "self.nome.grid(row=0, column=1, sticky='ew')\nself.columnconfigure(1, weight=1)"),
    "pack": _help("Layout per lati", "widget.pack(side='top', fill='x', padx=8, pady=8)", "Dispone i controlli uno dopo l’altro lungo i bordi del contenitore. Non usare pack e grid per i figli dello stesso contenitore. Il designer attuale di Tkinter Studio usa place.", "self.nome.pack(fill='x', padx=8, pady=8)"),
    "after": _help("Esegui più tardi", "widget.after(500, self.aggiorna)", "Pianifica la chiamata di una funzione dopo un intervallo in millisecondi. Passa il riferimento alla funzione senza parentesi; evita time.sleep() nel thread dell’interfaccia, perché blocca gli eventi.", "def aggiorna(self):\n    self.etichetta_nome.configure(text='Aggiornato')\n\nself.after(500, self.aggiorna)"),
    "mainloop": _help("Ciclo degli eventi", "app.mainloop()", "Avvia l’elaborazione degli eventi Tkinter. Il programma resta attivo finché le finestre vengono chiuse; le azioni si scrivono nei callback, senza un ciclo while che blocchi la finestra.", "app = App()\napp.mainloop()"),
    "destroy": _help("Chiudi un componente", "widget.destroy()", "Distrugge il componente e i suoi figli. self.destroy() nella classe App chiude la finestra principale.", "def on_chiudi(self):\n    self.destroy()"),
    "geometry": _help("Dimensioni della finestra", "self.geometry('800x560')", "Imposta larghezza e altezza della finestra. Tk accetta anche una posizione; il designer gestisce il formato larghezza×altezza senza posizione.", "self.geometry('800x560')"),
    "title": _help("Titolo della finestra", "self.title('La mia applicazione')", "Modifica il titolo mostrato nella barra della finestra. Nel blocco visuale usa un testo letterale per mantenerlo modificabile dal designer.", "self.title('Rubrica')"),
    "text": _help("Testo del componente", "text='Salva'", "Definisce il testo mostrato dai componenti che supportano questa opzione, per esempio Label e Button. Per il contenuto di Entry e Text usa i metodi insert/get oppure una variabile quando supportata.", "self.titolo.configure(text='Nuovo titolo')"),
    "state": _help("Stato del componente", "widget.configure(state='disabled')", "Disabilita o riattiva un controllo quando l’opzione è supportata. Entry e Combobox possono offrire anche readonly. Lo stato disabled impedisce normalmente l’interazione dell’utente.", "self.saluta.configure(state='disabled')\nself.saluta.configure(state='normal')"),
    "showinfo": _help("Messaggio informativo", "messagebox.showinfo('Titolo', 'Messaggio', parent=self)", "Mostra un messaggio modale. Importa messagebox da tkinter e indica parent per associarlo alla finestra corretta.", "from tkinter import messagebox\n\nmessagebox.showinfo('Salvato', 'Operazione completata.', parent=self)", PYTHON_DOCS + "library/tkinter.messagebox.html"),
    "showerror": _help("Messaggio di errore", "messagebox.showerror('Errore', 'Descrizione', parent=self)", "Mostra un errore dell’applicazione con un dialogo modale. Usa un testo che spieghi come correggere il problema.", "messagebox.showerror('Dati non validi', 'Inserisci un nome.', parent=self)", PYTHON_DOCS + "library/tkinter.messagebox.html"),
}

_PYTHON_HELP: dict[str, HelpEntry] = {
    "def": _help("Definisci una funzione", "def nome(parametro):", "Definisce una funzione. Il corpo deve essere indentato. In una classe il primo parametro di un normale metodo è self; i callback di bind aggiungono event.", "def on_salva(self):\n    print('Salvataggio richiesto')", PYTHON_DOCS + "tutorial/controlflow.html#defining-functions"),
    "class": _help("Definisci una classe", "class App(tk.Tk):", "Raggruppa dati e metodi. self indica l’istanza corrente; super().__init__() inizializza la classe di base.", "class App(tk.Tk):\n    def __init__(self):\n        super().__init__()", PYTHON_DOCS + "tutorial/classes.html"),
    "self": _help("L’istanza corrente", "self.nome", "self è il nome convenzionale dell’istanza nei metodi. Un attributo come self.nome può essere usato anche negli altri metodi della stessa istanza.", "def on_saluta(self):\n    nome = self.nome.get()\n    print(nome)", PYTHON_DOCS + "tutorial/classes.html#instance-objects"),
    "if": _help("Condizione", "if condizione:", "Esegue un blocco quando la condizione è vera. Usa elif per altri casi e else per il caso rimanente; ogni blocco va indentato.", "if nome.strip():\n    print(nome)\nelse:\n    print('Inserisci un nome')", PYTHON_DOCS + "tutorial/controlflow.html#if-statements"),
    "for": _help("Ciclo su una sequenza", "for elemento in sequenza:", "Ripete il corpo per ogni elemento. Nei callback evita operazioni lunghe nel thread della finestra; puoi dividere gli aggiornamenti con after().", "for elemento in ['Uno', 'Due']:\n    print(elemento)", PYTHON_DOCS + "tutorial/controlflow.html#for-statements"),
    "while": _help("Ciclo condizionale", "while condizione:", "Ripete un blocco finché la condizione è vera. Un ciclo lungo dentro un callback blocca l’interfaccia Tkinter: usa after per aggiornamenti periodici.", "while elementi:\n    elemento = elementi.pop()\n    print(elemento)", PYTHON_DOCS + "reference/compound_stmts.html#the-while-statement"),
    "return": _help("Restituisci un risultato", "return valore", "Termina la funzione corrente e restituisce un risultato. return senza valore restituisce None. È valido soltanto nel corpo di una funzione.", "def leggi_nome(self):\n    return self.nome.get().strip()", PYTHON_DOCS + "reference/simple_stmts.html#the-return-statement"),
    "try": _help("Gestisci un errore", "try: ... except ValueError: ...", "Intercetta gli errori previsti e presenta un messaggio utile. Cattura un tipo specifico di eccezione, lasciando visibili gli altri problemi.", "try:\n    eta = int(testo)\nexcept ValueError:\n    print('Inserisci un numero intero')", PYTHON_DOCS + "tutorial/errors.html#handling-exceptions"),
    "except": _help("Gestisci un’eccezione", "except ValueError as errore:", "Fa parte di un blocco try. Il corpo viene eseguito quando si verifica un’eccezione del tipo indicato.", "try:\n    numero = int(testo)\nexcept ValueError as errore:\n    print(errore)", PYTHON_DOCS + "tutorial/errors.html#handling-exceptions"),
    "with": _help("Gestisci una risorsa", "with open('dati.txt', encoding='utf-8') as file:", "Usa una risorsa in un blocco che ne gestisce automaticamente l’uscita. Con open, il file viene chiuso anche se si verifica un errore.", "with open('dati.txt', encoding='utf-8') as file:\n    testo = file.read()", PYTHON_DOCS + "tutorial/inputoutput.html#reading-and-writing-files"),
    "lambda": _help("Piccola funzione senza nome", "lambda: funzione(argomento)", "Crea una funzione definita da una sola espressione. Per azioni articolate usa un normale def. Il designer visuale gestisce callback nominati; una lambda nel blocco UI sospende la sincronizzazione.", "azione = lambda: print('Ciao')", PYTHON_DOCS + "tutorial/controlflow.html#lambda-expressions"),
    "import": _help("Importa un modulo", "import tkinter as tk", "Rende disponibile un modulo. 'as' ne sceglie il nome nel file; il controllo sintattico non importa né verifica la presenza del modulo.", "import tkinter as tk\nfrom tkinter import ttk, messagebox", PYTHON_DOCS + "tutorial/modules.html"),
    "print": _help("Scrivi nella console", "print(*valori, sep=' ', end='\\n')", "Scrive i valori sull’output del programma. Con Play il risultato appare nella console dell’IDE.", "print('Nome:', self.nome.get())", PYTHON_DOCS + "library/functions.html#print"),
    "input": _help("Leggi dalla console", "input('Domanda: ')", "Legge una riga e restituisce una stringa. Durante Play puoi rispondere dal campo della console. Per un’interfaccia grafica usa normalmente un Entry: input() chiamato nel thread Tkinter attende e blocca gli eventi della finestra.", "nome = input('Nome: ')\nprint('Ciao', nome)", PYTHON_DOCS + "library/functions.html#input"),
    "len": _help("Numero di elementi", "len(oggetto)", "Restituisce il numero di elementi di una sequenza o collezione, per esempio i caratteri di una stringa o gli elementi di una lista.", "caratteri = len(self.nome.get())", PYTHON_DOCS + "library/functions.html#len"),
    "str": _help("Converti in testo", "str(valore)", "Produce una stringa che rappresenta il valore. Utile per mostrare numeri nelle etichette o nei campi.", "self.titolo.configure(text=str(42))", PYTHON_DOCS + "library/functions.html#func-str"),
    "int": _help("Converti in numero intero", "int(testo)", "Converte un valore compatibile in un intero. Un testo non numerico genera ValueError: gestiscilo se il testo arriva dall’utente.", "try:\n    numero = int(self.numero.get())\nexcept ValueError:\n    print('Inserisci un intero')", PYTHON_DOCS + "library/functions.html#int"),
    "float": _help("Converti in numero decimale", "float(testo)", "Converte un valore compatibile in un numero decimale. Nel testo numerico Python usa il punto come separatore; un testo non valido genera ValueError.", "valore = float('12.5')", PYTHON_DOCS + "library/functions.html#float"),
    "range": _help("Sequenza di interi", "range(inizio, fine, passo)", "Produce interi da inizio fino a prima di fine. Con un solo argomento parte da zero; è spesso usato nei cicli for.", "for numero in range(3):\n    print(numero)", PYTHON_DOCS + "library/functions.html#func-range"),
    "super": _help("Accedi alla classe di base", "super().__init__()", "Permette di richiamare l’implementazione della classe di base. In App, super().__init__() inizializza la finestra Tk prima di creare i componenti.", "def __init__(self):\n    super().__init__()\n    self.build_ui()", PYTHON_DOCS + "library/functions.html#super"),
}


def _attribute(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name): return node.id
    if isinstance(node, ast.Attribute):
        prefix = _attribute(node.value)
        return f"{prefix}.{node.attr}" if prefix else None
    return None


def _aliases_and_widgets(tree: ast.AST | None):
    aliases = {"tk": "tk", "ttk": "ttk", "tkinter": "tk", "messagebox": "messagebox"}
    widgets: dict[str, str] = {}
    if tree is None: return aliases, widgets
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                if item.name in ("tkinter", "tkinter.ttk", "tkinter.messagebox"):
                    aliases[item.asname or item.name.split(".")[0]] = {"tkinter": "tk", "tkinter.ttk": "ttk", "tkinter.messagebox": "messagebox"}[item.name]
        elif isinstance(node, ast.ImportFrom) and node.module in ("tkinter", "tkinter.ttk", "tkinter.messagebox"):
            prefix = {"tkinter": "tk", "tkinter.ttk": "ttk", "tkinter.messagebox": "messagebox"}[node.module]
            for item in node.names:
                aliases[item.asname or item.name] = item.name if item.name in ("ttk", "messagebox") else prefix + "." + item.name
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Call):
            kind = _canonical(_attribute(node.value.func), aliases)
            if kind and kind.split(".")[-1] in _WIDGET_HELP and kind.split(".")[0] in ("tk", "ttk"):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    name = _attribute(target)
                    if name: widgets[name] = kind
    return aliases, widgets


def _canonical(name, aliases):
    if not name: return None
    if name.startswith("tkinter.ttk."): return "ttk." + name[len("tkinter.ttk."):]
    if name.startswith("tkinter.messagebox."): return "messagebox." + name[len("tkinter.messagebox."):]
    head, separator, tail = name.partition(".")
    return aliases.get(head, head) + (separator + tail if separator else "")


def _node_offset(source_lines, line_offsets, line, byte_column):
    before = line_offsets[line - 1] if 0 < line <= len(line_offsets) else 0
    text = source_lines[line - 1] if 0 < line <= len(source_lines) else ""
    return before + len(text.encode("utf-8", errors="replace")[:byte_column].decode("utf-8", errors="ignore"))


def _word_at(source: str, position: int):
    if not source: return "", max(0, position)
    position = max(0, min(len(source), position))
    point = position
    if point == len(source) or not (source[point].isalnum() or source[point] == "_"):
        if point > 0 and (source[point - 1].isalnum() or source[point - 1] == "_"): point -= 1
    for match in re.finditer(r"[^\W\d]\w*", source, re.UNICODE):
        if match.start() <= point < match.end(): return match.group(), match.start()
    return "", point


def _widget_entry(kind: str) -> HelpEntry:
    short = kind.rsplit(".", 1)[-1]
    title, signature, body = _WIDGET_HELP[short]
    if kind.startswith("tk.") and signature.startswith("ttk."): signature = "tk." + signature[4:]
    url = (TTK_DOCS if kind.startswith("ttk.") else TK_DOCS) + "#tkinter." + ("ttk." if kind.startswith("ttk.") else "") + short
    return _help(f"{title} · {kind}", signature, body, "", url)


def _method_entry(kind: str, method: str) -> HelpEntry | None:
    short = kind.rsplit(".", 1)[-1]
    prefix = f"{short}.{method}"
    if method == "get":
        if short == "Text": return _help(prefix, "widget.get('1.0', 'end-1c')", "Legge il testo tra due indici. '1.0' è l’inizio; 'end-1c' esclude la nuova riga finale aggiunta dal widget Text.", "testo = self.testo.get('1.0', 'end-1c')")
        if short == "Listbox": return _help(prefix, "widget.get(indice)", "Legge il testo dell’elemento all’indice indicato. curselection() restituisce una tupla con gli indici selezionati; verifica che non sia vuota.", "indici = self.lista.curselection()\nif indici:\n    testo = self.lista.get(indici[0])")
        if short in ("Entry", "Combobox", "Spinbox", "StringVar", "BooleanVar", "IntVar", "DoubleVar", "Scale"):
            return _help(prefix, "widget.get()", "Legge il valore corrente. Entry, Combobox e Spinbox restituiscono una stringa; le variabili numeriche o booleane e Scale hanno il proprio tipo di valore.", "valore = self.nome.get()")
    if method == "set" and short in ("Combobox", "Scale", "StringVar", "BooleanVar", "IntVar", "DoubleVar"):
        return _help(prefix, "widget.set(valore)", "Imposta il valore del componente o della variabile. Per un Entry normale usa invece delete/insert oppure una textvariable.", "self.elenco.set('Prima scelta')")
    if method == "insert":
        if short == "Text": return _help(prefix, "widget.insert('1.0', testo)", "Inserisce testo prima dell’indice dato. Usa '1.0' per l’inizio oppure 'end' per aggiungerlo in fondo.", "self.testo.insert('end', 'Nuova riga\\n')")
        if short in ("Entry", "Spinbox", "Combobox"): return _help(prefix, "widget.insert(0, testo)", "Inserisce testo prima del carattere indicato. Per sostituire l’intero contenuto, svuota prima il campo; un componente disabled o readonly può impedire questa modifica.", "self.nome.delete(0, 'end')\nself.nome.insert(0, 'Nuovo nome')")
        if short == "Listbox": return _help(prefix, "widget.insert('end', testo)", "Aggiunge un elemento in fondo all’elenco. L’indice numerico inserisce prima di quella posizione.", "self.lista.insert('end', 'Nuovo elemento')")
        if short == "Treeview": return _help(prefix, "widget.insert('', 'end', values=('Nome', 'Valore'))", "Aggiunge una riga. Il primo argomento è l’ID del genitore: '' indica il livello principale. Il risultato è l’ID della nuova riga.", "riga_id = self.tabella.insert('', 'end', values=('Ada', 42))", TTK_DOCS + "#tkinter.ttk.Treeview.insert")
    if method == "delete":
        if short == "Text": return _help(prefix, "widget.delete('1.0', 'end')", "Rimuove il testo nell’intervallo indicato. Gli indici di Text sono riga.colonna, a partire da '1.0'.", "self.testo.delete('1.0', 'end')")
        if short in ("Entry", "Spinbox", "Combobox"): return _help(prefix, "widget.delete(0, 'end')", "Rimuove i caratteri dal primo indice fino a prima dell’ultimo. Con questi argomenti svuota il campo, se lo stato permette la modifica.", "self.nome.delete(0, 'end')")
        if short == "Listbox": return _help(prefix, "widget.delete(primo, ultimo)", "Elimina gli elementi dall’indice primo all’indice ultimo, entrambi inclusi. delete(0, 'end') svuota l’elenco.", "self.lista.delete(0, 'end')")
    if method in ("selection", "curselection") and short in ("Treeview", "Listbox"):
        signature = "widget.selection()" if short == "Treeview" else "widget.curselection()"
        return _help(prefix, signature, "Restituisce una tupla con gli elementi selezionati: ID per Treeview, indici per Listbox. Può essere vuota: controllala prima di leggere il primo elemento.", "selezionati = " + signature.replace("widget", "self.tabella" if short == "Treeview" else "self.lista"), TTK_DOCS if short == "Treeview" else TK_DOCS)
    if method == "state" and kind.startswith("ttk."):
        return _help(prefix, "widget.state(['disabled'])", "Modifica i flag di stato del widget ttk. '!disabled' rimuove il flag disabled; state() senza argomenti restituisce i flag attivi.", "self.saluta.state(['disabled'])\nself.saluta.state(['!disabled'])", TTK_DOCS + "#tkinter.ttk.Widget.state")
    if method in _COMMON_HELP: return _COMMON_HELP[method]
    return None


def help_for_symbol(source: str, position: int) -> HelpEntry:
    """Descrive il simbolo al cursore, senza importare moduli del programma."""
    word, point = _word_at(source, position)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError, UnicodeError): tree = None
    aliases, widgets = _aliases_and_widgets(tree)
    target = None
    if tree is not None:
        lines = source.splitlines(keepends=True)
        offsets = []; total = 0
        for line in lines:
            offsets.append(total); total += len(line)
        candidates = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.Name, ast.Attribute)):
                start = _node_offset(lines, offsets, node.lineno, node.col_offset)
                end = _node_offset(lines, offsets, node.end_lineno, node.end_col_offset)
                if start <= point < end: candidates.append((end - start, node))
        if candidates: target = min(candidates, key=lambda pair: pair[0])[1]
    name = _attribute(target) if target is not None else word
    canonical = _canonical(name, aliases) or word
    if name in widgets: return _widget_entry(widgets[name])
    if isinstance(target, ast.Attribute):
        receiver = _attribute(target.value)
        if receiver in widgets:
            result = _method_entry(widgets[receiver], target.attr)
            if result: return result
        if receiver in ("event", "evento") and target.attr in ("widget", "x", "y", "x_root", "y_root", "keysym", "char", "num", "delta"):
            fields = {"widget": "Il componente che ha ricevuto l’evento.", "x": "Coordinata orizzontale del puntatore, relativa al componente.", "y": "Coordinata verticale del puntatore, relativa al componente.", "x_root": "Coordinata orizzontale del puntatore sullo schermo.", "y_root": "Coordinata verticale del puntatore sullo schermo.", "keysym": "Nome simbolico del tasto, per esempio 'Return' o 'Escape'.", "char": "Carattere prodotto dal tasto, quando disponibile.", "num": "Numero del pulsante del mouse, quando disponibile.", "delta": "Variazione della rotella del mouse, negli eventi che la forniscono."}
            return _help(f"Evento Tkinter · {target.attr}", f"event.{target.attr}", fields[target.attr] + " Il callback registrato con bind riceve event come argomento.", "def on_evento(self, event):\n    print(event.widget)", TK_DOCS + "#bindings-and-events")
    short = canonical.rsplit(".", 1)[-1]
    if short in _WIDGET_HELP and canonical.startswith(("tk.", "ttk.")): return _widget_entry(canonical)
    if tree is not None:
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == word:
                signature = ("async def " if isinstance(node, ast.AsyncFunctionDef) else "def ") + word + "(" + ast.unparse(node.args) + ")"
                body = ast.get_docstring(node) or f"Funzione definita in questo file alla riga {node.lineno}. I parametri compaiono nella firma; scrivi una docstring nel corpo per descriverne lo scopo."
                return _help(f"Funzione del progetto · {word}", signature, body[:2000], "", PYTHON_DOCS + "tutorial/controlflow.html#defining-functions")
    if word in _COMMON_HELP: return _COMMON_HELP[word]
    if word in _PYTHON_HELP: return _PYTHON_HELP[word]
    if keyword.iskeyword(word) or word in ("match", "case"):
        return _help(f"Parola chiave Python · {word}", word, "È una parola riservata del linguaggio: non usarla come nome di variabile o di componente. La documentazione descrive la sintassi e i contesti in cui può essere usata.", "", PYTHON_DOCS + "reference/lexical_analysis.html#keywords")
    if word in dir(builtins):
        symbol = getattr(builtins, word)
        if isinstance(symbol, type) and issubclass(symbol, BaseException):
            return _help(f"Eccezione Python · {word}", word, "È un tipo di eccezione incorporato di Python. Puoi intercettarlo in un blocco except quando prevedi questo errore; la scheda ufficiale ne descrive il significato.", "", PYTHON_DOCS + "library/exceptions.html#" + word)
        if word in ("None", "True", "False", "NotImplemented", "Ellipsis"):
            return _help(f"Costante Python · {word}", word, "È una costante incorporata di Python. None rappresenta l’assenza di un valore; True e False sono i valori booleani. Non riassegnare i nomi delle costanti.", "", PYTHON_DOCS + "library/constants.html")
        return _help(f"Python · {word}", word, "È un nome incorporato di Python, disponibile senza import. Consulta la documentazione ufficiale per argomenti, risultato ed eccezioni.", "", PYTHON_DOCS + "library/functions.html")
    return _help("Aiuto sul codice" if not word else f"Simbolo · {word}", word,
                 "Seleziona un componente, un’opzione o una funzione Python per consultarne la scheda. Per un nome definito nel tuo programma controlla la dichiarazione e i parametri; Ctrl+Spazio mostra i suggerimenti disponibili. Il controllo della sintassi non esegue il codice e non verifica gli errori che possono verificarsi durante Play.",
                 "def on_click(self):\n    print('Scrivi qui la tua azione')", PYTHON_DOCS + "tutorial/")


def completion_words(source: str) -> list[str]:
    """Parole singole adatte al completamento WordUnderCursor dell’editor."""
    words = set(keyword.kwlist) | set(dir(builtins)) | set(_WIDGET_HELP) | set(_COMMON_HELP)
    words.update(("self", "tk", "ttk", "event", "get", "set", "insert", "delete", "selection", "curselection"))
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.NAME: words.add(token.string)
    except (tokenize.TokenError, IndentationError, SyntaxError, UnicodeError): pass
    return sorted(word for word in words if word.isidentifier())[:4000]
