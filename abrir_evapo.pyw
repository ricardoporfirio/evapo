"""Inicializa o aplicativo na pasta do projeto, sem console no Windows."""

import os
import sys
from pathlib import Path

projeto = Path(__file__).resolve().parent
os.chdir(projeto)
sys.path.insert(0, str(projeto / "src"))
try:
    from evapo.interface.sistema import main

    main()
except Exception:
    import traceback
    import tkinter as tk
    from tkinter import messagebox

    log = projeto / "erro_sistema.log"
    log.write_text(traceback.format_exc(), encoding="utf-8")
    janela = tk.Tk()
    janela.withdraw()
    messagebox.showerror(
        "Evapo", f"Não foi possível abrir o sistema. Detalhes em:\n{log}"
    )
    janela.destroy()
