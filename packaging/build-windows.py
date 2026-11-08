"""Distribuzione Windows con Python completo: Play usa un interprete reale, non un EXE congelato.

Non installa pacchetti o SDK. Eseguire dall'ambiente Python 3.14 del progetto:
python packaging/build-windows.py --iscc <percorso/ISCC.exe>
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import site
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]

def ignore_runtime(directory,names):
    return [name for name in names if name in {'site-packages','__pycache__','test','tests'} or name.endswith(('.pyc','.pyo'))]

def build(python_base:Path,packages:Path,compiler:Path,output:Path):
    version='1.1.0'
    payload=ROOT/'dist'/'TkinterStudio'
    if payload.exists():raise SystemExit('Payload già esistente: usa una nuova copia di lavoro, nessuna cancellazione automatica.')
    runtime=payload/'python';runtime.mkdir(parents=True)
    for folder in ['Lib','DLLs','tcl']:
        shutil.copytree(python_base/folder,runtime/folder,ignore=ignore_runtime)
    for name in ['python.exe','pythonw.exe','python3.dll','python314.dll','vcruntime140.dll','vcruntime140_1.dll','LICENSE.txt']:
        shutil.copy2(python_base/name,runtime/name)
    target=runtime/'Lib/site-packages';target.mkdir()
    copied=[]
    for entry in packages.iterdir():
        if entry.name.lower().startswith('pyqt6'):
            if entry.is_dir():shutil.copytree(entry,target/entry.name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
            else:shutil.copy2(entry,target/entry.name)
            copied.append(entry.name)
    if not (target/'PyQt6/QtWidgets.pyd').exists():raise SystemExit('PyQt6 incompleto nel runtime.')
    for folder in ['tkstudio','esempi','LICENZE']:
        shutil.copytree(ROOT/folder,payload/folder,ignore=shutil.ignore_patterns('__pycache__','*.pyc','_tkstudio_run_*'))
    for name in ['main.py','README.md','LICENSE','COPYRIGHT.md','THIRD_PARTY.md','requirements.txt']:
        shutil.copy2(ROOT/name,payload/name)
    launcher=payload/'Avvia Tkinter Studio.cmd'
    launcher.write_text('@echo off\r\ncd /d "%~dp0"\r\nstart "" "%~dp0python\\pythonw.exe" "%~dp0main.py"\r\n',encoding='utf-8')
    output.mkdir(parents=True,exist_ok=True)
    source=ROOT/'packaging/windows.iss'
    subprocess.run([str(compiler),'/Qp',f'/DAppVersion={version}',f'/DPayloadDir={payload}',f'/DReleaseDir={output}',str(source)],check=True)
    portable=output/f'TkinterStudio-{version}-Windows-x64-portabile.zip'
    with zipfile.ZipFile(portable,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for path in payload.rglob('*'):
            if path.is_file():archive.write(path,'TkinterStudio/'+path.relative_to(payload).as_posix())
    manifest={'version':version,'python':subprocess.check_output([str(runtime/'python.exe'),'--version'],text=True).strip(),'packages':copied,'payload':str(payload),'files':{path.relative_to(payload).as_posix():hashlib.file_digest(path.open('rb'),'sha256').hexdigest() for path in payload.rglob('*') if path.is_file()}}
    (output/'TkinterStudio-payload-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps({'payload':str(payload),'portable':str(portable),'files':len(manifest['files'])}))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--python-base',type=Path,default=Path(sys.base_prefix));parser.add_argument('--site-packages',type=Path);parser.add_argument('--iscc',type=Path,required=True);parser.add_argument('--output',type=Path,default=ROOT/'dist')
    args=parser.parse_args();packages=args.site_packages or next((Path(p) for p in site.getsitepackages() if (Path(p)/'PyQt6').exists()),None)
    if packages is None:raise SystemExit('PyQt6 non trovato: prepara l’ambiente requirements.txt.')
    build(args.python_base.resolve(),packages.resolve(),args.iscc.resolve(),args.output.resolve())
