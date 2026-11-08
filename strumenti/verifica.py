"""Verifica ripetibile dei moduli, integrazione Qt e vero runtime Tkinter."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main():
    from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR, qVersion
    failures = []
    def exception_hook(error_type, value, tb):
        failures.append("".join(traceback.format_exception(error_type, value, tb)))
        traceback.print_exception(error_type, value, tb)
    sys.excepthook = exception_hook
    begin = time.monotonic()
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    runtime = r'''
import runpy, json, tkinter as tk
from tkstudio.model import UiDocument, WIDGET_SPECS, create_widget
from tkstudio.codegen import generate_document
module = runpy.run_path('esempi/Benvenuto/app.py', run_name='tkstudio_verifica')
messages = []
module['messagebox'].showinfo = lambda *args, **kwargs: messages.append(args)
app = module['App'](); app.withdraw(); app.update_idletasks()
app.nome.delete(0, 'end'); app.nome.insert(0, 'Daniele')
app.saluta.invoke()
assert messages and 'Daniele' in str(messages), messages
app.destroy()
doc = UiDocument(width=1400, height=1400)
for i, kind in enumerate(WIDGET_SPECS):
    create_widget(doc, kind, x=10+(i%4)*340, y=10+(i//4)*300)
namespace = {'__name__': 'tkstudio_verifica'}
exec(compile(generate_document(doc), '<tutti-i-componenti>', 'exec'), namespace)
app = namespace['App'](); app.withdraw(); app.update_idletasks()
assert len(app.winfo_children()) == len(WIDGET_SPECS)
version = app.tk.call('info', 'patchlevel')
app.destroy()
print(json.dumps({'demo_callback': 'ok', 'widget_types':len(WIDGET_SPECS), 'tk':version}))
'''
    run = subprocess.run([sys.executable, "-c", runtime], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30)
    runtime_result = None
    if run.returncode == 0:
        runtime_result = json.loads(run.stdout.strip()); print("TKINTER REALE:", runtime_result)
    else:
        print(run.stdout, run.stderr); failures.append("Runtime Tkinter: " + run.stderr)
    report = {"success": result.wasSuccessful() and not failures and run.returncode == 0,
              "tests": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
              "qt_slot_exceptions": failures, "python": sys.version.split()[0], "pyqt": PYQT_VERSION_STR,
              "qt": qVersion(), "qt_build": QT_VERSION_STR, "runtime": runtime_result, "seconds": round(time.monotonic() - begin, 2)}
    destination = ROOT / "verifiche"; destination.mkdir(exist_ok=True)
    (destination / "risultati.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["success"] else 1


if __name__ == "__main__": raise SystemExit(main())
