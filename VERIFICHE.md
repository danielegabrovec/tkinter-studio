# Verifiche — Tkinter Studio 1.1.0

Verifica eseguita il **25 ottobre 2026** nella cartella del progetto.

## Esito

- **144 test superati**, zero errori e zero fallimenti.
- Nessuna eccezione Python sfuggita dagli slot Qt durante la suite.
- Prova Tkinter reale: callback Saluta funzionante e istanziazione dei **16 tipi di componente** riuscita.
- La suite delle integrazioni verifica anche binding e funzioni di lettura, testo e stato su Tkinter reale.
- Compilazione dei moduli riuscita e dipendenze senza conflitti (`pip check`).

Ambiente verificato: **Python 3.14.5**, **PyQt6 6.11.0**, **Qt runtime 6.11.2**, **Tcl/Tk 8.6.15**. Durata del controllo completo: **23,36 secondi**.

## Percorsi verificati

- Clic sul componente nel canvas → definizione e posizione evidenziate nel codice, senza modifiche al sorgente.
- Selezione del codice → menu contestuale con azioni pertinenti al tipo di componente.
- Callback nuovo collegato al comando; callback già presente aperto e conservato.
- Eventi mouse, tastiera e selezione registrati fuori dalla parte rigenerata dal designer.
- Funzioni di lettura, testo, stato e messaggi inserite senza sovrascrivere il codice esistente.
- Inserimento annullabile con una sola operazione; menu obsoleti e file in sola lettura protetti.
- Modifiche grafiche, salvataggio, riapertura, rinomina e rimozione dei collegamenti automatici dopo l’eliminazione di un widget.
- Controllo automatico/manuale di sintassi e indentazione, avvisi distinti, navigazione a riga/colonna e blocco di Play in presenza di errori.
- Aiuto locale con firma, spiegazione, esempio e documentazione ufficiale; HTML, caratteri Unicode e temi verificati.
- Conferma che analisi, aiuto e suggerimenti non eseguono il programma controllato.

## Ripetizione

Da PowerShell nella cartella del progetto:

```powershell
.\.venv\Scripts\python.exe -W error::ResourceWarning strumenti\verifica.py
```

Il risultato strutturato dell’ultima esecuzione è in `verifiche/risultati.json`.

Le catture del backend **Qt Windows nativo**, ottenute da un’istanza temporanea senza modificare i progetti dell’utente, sono:

- `verifiche/menu-integrazioni-pulsante.png`
- `verifiche/ide-aiuto-codice.png`
- `verifiche/ide-controllo-sintassi.png`
- `verifiche/ide-controllo-sintassi-chiaro.png`

Il controllo sintattico usa il compilatore dell’interprete dell’IDE e riporta il primo errore di compilazione insieme agli avvisi disponibili. Non esegue gli import del file e non verifica tutti i nomi, i tipi o gli errori che si manifestano durante l’esecuzione.
