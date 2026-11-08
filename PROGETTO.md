# Progetto editoriale e tecnico — Tkinter Studio 1.1

## Obiettivo e flusso

Un IDE desktop per costruire programmi Tkinter attraverso due strumenti collegati: composizione grafica dell’interfaccia e scrittura di Python. Il flusso principale è **crea progetto → trascina → modifica proprietà → scrivi callback → Play → salva**.

L’applicazione usa PyQt6 per mantenere il designer separato dall’interprete che esegue i programmi Tkinter. Nessun codice utente viene eseguito per mostrare il canvas o interpretare il progetto.

## Organizzazione dell’interfaccia

- **In alto:** identità del progetto, nuovo/apri/salva, tema, Play e Stop. Scorciatoie nei tooltip e nei menu.
- **A sinistra:** cartelle del progetto e libreria filtrabile per nome e categoria.
- **Al centro:** designer, codice o vista affiancata, con console sottostante.
- **A destra:** proprietà della selezione e gerarchia dei contenitori.
- **In basso:** stato delle operazioni, riga/colonna e interprete.

La selezione grafica identifica lo stesso elemento in canvas, proprietà, struttura e codice. Un singolo clic evidenzia il costruttore e la chiamata `place`; il doppio clic apre il callback o la definizione. La navigazione automatica non sottrae il focus durante la manipolazione e non sposta il layout sotto il puntatore durante un trascinamento.

Il sistema visivo usa superfici blu scuro, un accento verde acqua, bordi discreti e tipografia Segoe UI; il codice e la console hanno font monospace. Il tema chiaro conserva le stesse gerarchie e gli stessi stati. Icone vettoriali locali, focus visibile, nomi accessibili e alternative da tastiera completano l’interazione.

## Architettura e dati

- **Modello:** documento con titolo, dimensioni, sfondo e lista piatta di widget identificati stabilmente. Il riferimento al genitore costruisce la gerarchia. Validazione di tipi, nomi Python, ID, cicli e proprietà supportate.
- **Designer:** scena Qt con coordinate relative ai contenitori, selezione, 8 maniglie di ridimensionamento, snap, zoom, duplicazione profonda e cancellazione dei discendenti. Il disegno riproduce la struttura dei controlli senza creare finestre Tk nascoste.
- **Generazione:** programma Tkinter autonomo con classe `App`, metodo dichiarativo `build_ui` e funzioni utente. Il generatore sostituisce soltanto la regione gestita, aggiungendo callback mancanti senza alterare quelli esistenti.
- **Sincronizzazione:** parser AST statico dei valori letterali. Le istruzioni non rappresentabili sospendono il designer; il testo Python resta autorevole. Le rinomine dei normali attributi nella classe vengono applicate alle posizioni AST corrette, mantenendo commenti e stringhe.
- **Editor:** QPlainTextEdit, gutter, highlighting Python, autoindentazione, suggerimenti con identificatori del file, ricerca/sostituzione, navigazione e selezioni delle righe del componente. Il menu contestuale riconosce dichiarazioni e riferimenti ai widget e offre integrazioni pertinenti, applicate in un solo blocco annullabile.
- **Integrazioni:** trasformazioni AST delle sole posizioni interessate nel sorgente, mantenendo commenti, stringhe, nomi e callback dell’utente. I comandi supportati sono collegati nel costruttore; gli eventi vengono registrati da un metodo separato fuori dalla regione del designer. Selezioni ambigue o sorgente non interpretabile restano invariati.
- **Assistenza:** compilazione statica senza esecuzione, diagnostica automatica con ritardo e controllo manuale; errori/avvisi, righe evidenziate e navigazione ai problemi. L’aiuto contestuale locale fornisce spiegazioni in italiano, esempi e riferimenti alla documentazione ufficiale.
- **Esecuzione:** QProcess con output UTF-8 non bufferizzato e input separato. Il codice corrente viene eseguito da una copia temporanea nella stessa cartella dello script, senza sovrascrivere il file aperto. I traceback rimandano alla sorgente della specifica esecuzione anche dopo modifiche successive. Stop termina il processo avviato e i suoi figli su Windows.
- **Persistenza:** JSON versionato `.tkui` e Python principale adiacente. Controllo delle modifiche esterne e sostituzioni atomiche per file. Preferenze locali in QSettings e bozza recuperabile del documento principale ogni 30 secondi.

## Criteri di verifica

Il percorso principale deve essere verificato oltre ai singoli moduli: creazione di widget → Python valido → modifiche al testo → aggiornamento del canvas → conservazione dei callback → salvataggio → riapertura → esecuzione Tkinter reale.

Le regressioni coprono stringhe Unicode e quoting, tutti i 16 tipi, genitori annidati, identità e rinomine, selezione dal canvas al codice senza modifiche, undo/redo, espressioni dinamiche, conflitti esterni, output/input/errori, chiusura e riavvio dei processi, durata dei timer, cambio tema e font monospace. Le integrazioni vengono verificate anche dopo rigenerazione, salvataggio e riapertura; la diagnostica deve individuare gli errori senza eseguire istruzioni del file. Il controllo visivo usa Windows nativo alle larghezze 1120, 1280 e 1560 px.

## Confini attuali

Layout visuale `place`; schema del progetto 1; un’interfaccia principale per progetto; nessun servizio remoto. File Python esterni sono utilizzabili nell’editor e con Play, ma l’interpretazione visuale richiede la struttura dichiarativa generata da Tkinter Studio. I suggerimenti sono lessicali e non equivalgono a un language server. Salva con nome copia l’interfaccia e il Python principale, senza raccogliere automaticamente moduli e risorse aggiuntivi.

Le eventuali estensioni successive — layout `grid` e `pack`, finestre multiple, menu visuali, language server, debugger ed esportazione eseguibili — richiedono evoluzioni esplicite del modello e nuovi percorsi di verifica.
