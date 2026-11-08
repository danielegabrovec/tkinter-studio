@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    py -3.14 -m venv .venv
    if errorlevel 1 (
        echo Serve Python 3.14 a 64 bit con Tcl/Tk. L'installazione non e' riuscita.
        pause
        exit /b 1
    )
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Installazione delle dipendenze non riuscita.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -c "from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR; import tkinter; print('PyQt', PYQT_VERSION_STR, '- Qt', QT_VERSION_STR, '- Tk', tkinter.TkVersion)"
echo.
echo Ambiente pronto. Apri Avvia Tkinter Studio.cmd.
pause
