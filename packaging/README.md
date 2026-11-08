# Installer Windows

Script Inno Setup riproducibile. I pacchetti si pubblicano nelle GitHub Releases e non nella cronologia Git. Richiede Inno Setup 6 o successivo; non eseguire l'installer per ricompilare il progetto.

Gli installer sono per l'utente corrente, non richiedono privilegi amministrativi e non rimuovono i dati applicativi nelle cartelle personali. Non sono firmati Authenticode.

Per Tkinter Studio esegui `python packaging/build-windows.py --iscc <ISCC.exe>` dall’ambiente Python 3.14 con requirements.txt installato. Il builder copia un runtime completo locale, incluse Tcl/Tk e PyQt6, e non usa PyInstaller perché Play deve avviare un vero interprete Python. Nessun pacchetto viene scaricato dal builder.
