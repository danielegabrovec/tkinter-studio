# Tkinter Studio

IDE desktop in **PyQt6** per disegnare finestre **Tkinter/ttk**, modificare Python e provare il programma con Play. L’interfaccia è in italiano, con temi chiaro e scuro, pannelli ridimensionabili e comandi da tastiera.

## Avvio

In questa cartella l’ambiente Python è già configurato. Fai doppio clic su **Avvia Tkinter Studio.cmd**.

Per avviare dal terminale PowerShell aperto in questa cartella:

```powershell
.\.venv\Scripts\python.exe main.py
```

Se trasferisci la cartella su un altro computer, installa Python 3.14 a 64 bit con Tcl/Tk e avvia **Configura.cmd**. Non trasferire l’ambiente `.venv`: ricrealo. Le versioni delle dipendenze sono fissate in `requirements.txt`.

## Il primo programma

1. All’avvio trovi l’esempio **Benvenuto**. Premi **Play** o **F5**: si apre una vera finestra Tkinter. Il pulsante **Saluta** legge il nome e mostra un messaggio.
2. Per partire da zero scegli **File → Nuovo progetto**, inserisci nome e cartella, quindi scegli **Finestra vuota**.
3. Trascina un componente dalla libreria sul canvas. Puoi anche aggiungerlo con un doppio clic. Per inserirlo in un gruppo, trascinalo dentro un contenitore.
4. Fai clic su una label o su qualsiasi altro componente: a destra compaiono le proprietà e nell’editor vengono evidenziate la sua creazione e la sua posizione. Se il codice è nascosto, la vista affiancata si apre dopo il gesto senza interrompere il trascinamento.
5. Trascina per spostare, usa le maniglie per ridimensionare. Cambia testo, nome, posizione, dimensioni e proprietà dal pannello. **Altre proprietà** permette di aggiungere opzioni come stile, font o colori, quando supportate dal componente.
6. Fai doppio clic su un pulsante per aprire il suo callback. Scrivi il codice della funzione; le modifiche grafiche successive lo conservano.
7. Premi **Play** per provare il codice corrente, anche prima di salvarlo. **Stop** o **Maiusc+F5** interrompe il processo avviato dall’IDE. Puoi rispondere a `input()` dal campo della console.
8. Premi **Ctrl+S** per salvare il progetto visuale e il Python principale. I file aperti nelle altre schede si salvano singolarmente.

**F1** apre la guida anche dall’applicazione.

## Integrazioni con il tasto destro

Seleziona il codice di un componente, oppure posiziona il cursore sulla sua definizione o su un suo utilizzo, e fai **clic destro**. Il menu propone azioni compatibili con il controllo selezionato. Il pulsante **Integra** nella barra dell’editor apre lo stesso menu.

- **Pulsanti e controlli con un comando:** crea e collega un callback, oppure apri quello esistente.
- **Componenti grafici:** aggiungi eventi di clic, doppio clic, ingresso e uscita del mouse.
- **Campi di testo:** gestisci Invio e crea una funzione che legge il contenuto.
- **Elenchi e tabelle:** gestisci la selezione.
- **Testi e controlli compatibili:** crea funzioni per cambiare il testo, abilitare/disabilitare il componente o mostrare un messaggio.
- **Codice generico:** inserisci una nuova funzione Python.

I nomi dei componenti e dei callback vengono adattati al codice selezionato. Un’azione non sostituisce una funzione già scritta: la apre o ne aggiunge una distinta. L’intero inserimento si annulla con **Ctrl+Z**. Se la selezione comprende più componenti, scegli prima quello su cui vuoi intervenire.

Gli eventi aggiunti automaticamente sono collocati fuori da `build_ui`, collegati all’inizializzazione e conservati nelle modifiche successive del designer. Le funzioni di esempio per lettura, modifica e messaggi sono pronte da richiamare o personalizzare: non vengono eseguite durante l’inserimento.

## Aiuto e controllo della sintassi

L’editor controlla automaticamente il codice Python dopo una breve pausa nella scrittura. La barra mostra il risultato; gli errori hanno riga, colonna, evidenziazione e un suggerimento. Fai clic su un problema per raggiungerlo. Premi **F8**, usa **Controlla** oppure **Esegui → Controlla sintassi del codice** per controllare immediatamente.

Il controllo usa il compilatore Python senza eseguire il programma: rileva errori di sintassi, indentazione e istruzioni non ammesse nel contesto, per esempio `return` fuori da una funzione. Gli eventuali avvisi sono distinti dagli errori. Play non avvia un file con errori di sintassi. Questo controllo non garantisce l’assenza di errori che emergono durante l’esecuzione, né sostituisce un controllo completo dei tipi.

Il controllo usa la versione Python che esegue l’IDE. Se selezioni un interprete differente per Play, le versioni possono accettare sintassi diverse. Riferimento tecnico: [compile nella documentazione Python](https://docs.python.org/3.14/library/functions.html#compile).

Con **Ctrl+I**, **Aiuto codice** o l’apposita voce nel menu contestuale trovi spiegazioni in italiano per la parola, il componente o il metodo al cursore, con firma, esempio e collegamento alla documentazione ufficiale. L’aiuto essenziale è disponibile senza connessione. **Ctrl+Spazio** propone anche i nomi definiti nel file, oltre alle parole Python e Tkinter.

## Designer e codice collegati

Il file Python è un programma completo, leggibile ed eseguibile fuori dall’IDE; richiede soltanto la libreria standard, con Tcl/Tk installato.

```python
class App(tk.Tk):
    # <tkstudio:ui>
    def build_ui(self):
        # Componenti e coordinate gestiti dal designer.
        ...
    # </tkstudio:ui>

    def on_pulsante_1(self, *args):
        # Scrivi qui la logica del tuo programma.
        ...
```

Puoi modificare anche dal codice i valori letterali nel metodo `build_ui`: testi, geometrie, proprietà, nomi e contenitori. Il designer si aggiorna dopo una breve pausa. La selezione dal canvas porta alla definizione del componente **senza spostare il focus** dall’area grafica. La selezione non modifica né rigenera il codice.

Scrivi funzioni, condizioni, cicli e comportamento applicativo **fuori dalla regione `tkstudio:ui`**. Se inserisci nella regione espressioni o istruzioni che il designer non sa rappresentare, l’IDE conserva il testo e sospende le modifiche grafiche. Puoi continuare a scrivere ed eseguire Python; il designer riprende quando il metodo torna compatibile.

Rinominando dal pannello un componente, i normali riferimenti `self.nome` nella classe `App` vengono aggiornati anche nei callback. I riferimenti dinamici costruiti con stringhe, per esempio `getattr(self, 'nome')`, vanno aggiornati manualmente.

## Cosa contiene il progetto

| File | Contenuto |
| --- | --- |
| `progetto.tkui` | Struttura visuale versionata, contenitori, proprietà e geometrie |
| `app.py` | Programma Tkinter e funzioni scritte dall’utente |
| Altri file e cartelle | Moduli Python, dati e risorse del tuo programma |

**Salva progetto con nome** salva una copia dell’interfaccia e del Python principale nella cartella scelta. Gli eventuali moduli e le risorse aggiuntive vanno copiati insieme quando trasferisci un progetto completo. **Esporta codice Python** esporta la scheda corrente.

Puoi aprire cartelle e modificare altri file Python nelle schede dell’editor. Play esegue la scheda Python attiva; nella vista solo designer esegue il Python principale. I programmi esterni possono essere modificati ed eseguiti, ma non vengono convertiti automaticamente in un progetto visuale.

Il salvataggio verifica se un file è cambiato sul disco prima di sostituirlo e usa scritture atomiche per ciascun file. Una bozza del progetto principale viene conservata ogni 30 secondi nella cartella dati locale dell’app e può essere recuperata dopo una chiusura anomala. Le altre schede restano protette dagli avvisi di modifiche non salvate.

## Componenti disponibili

Etichetta, pulsante, campo di testo, casella di spunta, scelta singola, elenco a discesa, selettore numerico, contenitore, gruppo con titolo, separatore, area di testo, elenco, tabella/albero, canvas, cursore e barra di avanzamento.

Il canvas è un’anteprima schematica. **Play mostra l’aspetto Tkinter reale**. Il layout visuale usa `place` con coordinate in pixel, snap opzionale a 8 px e contenitori annidati. La versione attuale non include un designer `grid`/`pack`, l’importazione visuale di Python arbitrario, un debugger con breakpoint, la progettazione dei menu o l’assemblaggio automatico di eseguibili.

## Scorciatoie

| Comando | Tasti |
| --- | --- |
| Nuovo / apri / salva | Ctrl+N / Ctrl+O / Ctrl+S |
| Designer / affiancati / codice | Ctrl+1 / Ctrl+2 / Ctrl+3 |
| Adatta canvas | Ctrl+0 |
| Play / Stop | F5 / Maiusc+F5 |
| Annulla / ripeti | Ctrl+Z / Ctrl+Maiusc+Z |
| Duplica / elimina nel canvas | Ctrl+D / Canc |
| Sposta un componente | Frecce, 1 px; Maiusc+frecce, 10 px |
| Cerca / sostituisci / vai alla riga | Ctrl+F / Ctrl+H / Ctrl+G |
| Suggerimenti Python | Ctrl+Spazio |
| Aiuto sul codice al cursore | Ctrl+I |
| Controlla sintassi | F8 |
| Guida | F1 |

## Sviluppo e verifiche

```powershell
.\.venv\Scripts\python.exe -W error::ResourceWarning -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q tkstudio main.py esempi
.\.venv\Scripts\python.exe -W error::ResourceWarning strumenti\verifica.py
```

I test Qt usano il backend offscreen; le verifiche visive sono state eseguite anche con il backend Windows nativo. Su Windows il backend offscreen può non enumerare i font: questo non riguarda l’applicazione avviata normalmente. Le evidenze visive sono in `verifiche` e la descrizione dell’architettura è in `PROGETTO.md`.

La dipendenza PyQt6 distribuita da PyPI è GPLv3; per una distribuzione proprietaria dell’IDE occorre valutare la licenza commerciale di Riverbank. Il Python Tkinter generato non importa PyQt6. Fonti tecniche: [installazione PyQt6](https://www.riverbankcomputing.com/software/pyqt/download), [licenze PyQt](https://www.riverbankcomputing.com/software/pyqt/intro), [Graphics View Qt](https://doc.qt.io/qt-6/graphicsview.html), [Tkinter Python](https://docs.python.org/3/library/tkinter.html).

## Download e licenza

[Installer e pacchetti Windows](https://github.com/danielegabrovec/tkinter-studio/releases/latest).

Codice originale: GNU GPL-3.0-only; vedere [LICENSE](LICENSE), [COPYRIGHT.md](COPYRIGHT.md) e [componenti di terzi](THIRD_PARTY.md). Gli installer non sono firmati digitalmente.

L’installer include Python 3.14, Tcl/Tk e PyQt6: sul PC destinatario non è richiesta un’installazione Python separata. Per la copia portabile usa Avvia Tkinter Studio.cmd. Per lo sviluppo dai sorgenti continua a usare il venv descritto sopra.
