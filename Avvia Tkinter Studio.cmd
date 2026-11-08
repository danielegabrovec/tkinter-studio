@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Prima esegui Configura.cmd per installare l'ambiente.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -c "import PyQt6.QtWidgets, tkinter" >nul 2>&1
if errorlevel 1 (
    echo Ambiente incompleto. Esegui Configura.cmd.
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "main.py" %*
