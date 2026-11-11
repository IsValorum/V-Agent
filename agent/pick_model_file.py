"""Native file picker, opened only by the user's Browse button."""
import json
from pathlib import Path
import sys
import tkinter as tk
from tkinter import filedialog

if hasattr(sys.stdout,'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
kind = sys.argv[1] if len(sys.argv)>1 else 'model'
root=tk.Tk();root.withdraw();root.attributes('-topmost',True)
try:
    # Start in Downloads, where models usually land; Windows remembers the last folder afterwards.
    folder=Path.home()/'Downloads'
    path=filedialog.askdirectory(parent=root,title='Elegir carpeta del plugin',mustexist=True) if kind=='plugin' else filedialog.askdirectory(parent=root,title='Elegir proyecto',mustexist=True) if kind=='project' else filedialog.askopenfilename(parent=root,title='Elegir cabeza MTP o draft' if kind=='draft' else 'Elegir plantilla' if kind=='template' else 'Añadir modelo',initialdir=str(folder if folder.exists() else Path.home()),
        filetypes=[('Plantilla Jinja','*.jinja *.jinja2')] if kind=='template' else [('Codificador Strata','strata-vision.exe')] if kind=='encoder' else [('Motor ejecutable','*.exe')] if kind=='engine' else [('Modelo GGUF','*.gguf')])
    print(json.dumps({'path':path,'cancelled':not bool(path)},ensure_ascii=False))
finally:root.destroy()
