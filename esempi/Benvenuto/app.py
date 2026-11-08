"""Applicazione Tkinter creata con TkStudio.

Il designer aggiorna solo la regione tkstudio:ui.
Scrivi le tue funzioni fuori da quella regione.
"""
import tkinter as tk
from tkinter import ttk, messagebox


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.build_ui()
        self._configure_styles()

    def _configure_styles(self):
        style = ttk.Style(self)
        if 'clam' in style.theme_names():
            style.theme_use('clam')
        style.configure('.', font=('Segoe UI', 10), background=self.cget('background'), foreground='#202b40')
        style.configure('Hero.TLabel', font=('Segoe UI', 20, 'bold'))
        style.configure('Muted.TLabel', foreground='#67748c')
        style.configure('Card.TLabelframe', background='#ffffff', bordercolor='#e0e5ef', relief='solid', borderwidth=1)
        style.configure('Card.TLabelframe.Label', background='#ffffff', foreground='#34415b', font=('Segoe UI', 10, 'bold'))
        style.configure('Card.TLabel', background='#ffffff')
        style.configure('TEntry', fieldbackground='#ffffff', padding=5)
        style.configure('TButton', padding=7)
        style.configure('Accent.TButton', background='#5267db', foreground='#ffffff', font=('Segoe UI', 10, 'bold'))
        style.map('Accent.TButton', background=[('active', '#4255c4'), ('pressed', '#3546ad')])

    # <tkstudio:ui>
    def build_ui(self):
        self.title('La mia prima app')
        self.geometry('800x560')
        self.configure(background='#f5f7fb')

        # widget:d94575d604f345469557a7034296b51d
        self.titolo = ttk.Label(self, text='La tua prossima idea comincia qui.', anchor='w', style='Hero.TLabel')
        self.titolo.place(x=40, y=36, width=660, height=34)

        # widget:2836ec2ff57349408c549c2da61d6aec
        self.descrizione = ttk.Label(self, text='Modifica questa interfaccia, scrivi il codice e premi Play.', anchor='w', style='Muted.TLabel')
        self.descrizione.place(x=40, y=78, width=680, height=30)

        # widget:b26f268016b14d29a9411737d2bec2e6
        self.profilo = ttk.LabelFrame(self, text='Il tuo primo programma', padding=0, style='Card.TLabelframe')
        self.profilo.place(x=40, y=140, width=720, height=244)

        # widget:faee11c15e8842c4b64cbd1c53d790ba
        self.etichetta_nome = ttk.Label(self.profilo, text='Come ti chiami?', anchor='w', style='Card.TLabel')
        self.etichetta_nome.place(x=24, y=38, width=160, height=30)

        # widget:05b736d11dbe40708d15ee8ba271c48a
        self.nome = ttk.Entry(self.profilo, show='')
        self.nome.place(x=24, y=78, width=420, height=34)
        self.nome.insert(0, 'Mondo')

        # widget:557ea78ea29a4401b916da9b36fea343
        self.saluta = ttk.Button(self.profilo, text='Saluta', command=self.on_saluta, style='Accent.TButton')
        self.saluta.place(x=24, y=136, width=148, height=36)

        # widget:d35cdb9a87e948dab13adc90ca07fc7f
        self.suggerimento = ttk.Label(self, text='Trascina un componente dalla libreria per aggiungerlo alla finestra.', anchor='w', style='Muted.TLabel')
        self.suggerimento.place(x=40, y=422, width=700, height=44)
    # </tkstudio:ui>

    # <tkstudio:handlers>
    def on_saluta(self):
        nome = self.nome.get().strip() or 'Mondo'
        messagebox.showinfo('Ciao!', f'Ciao, {nome}!')
    # </tkstudio:handlers>


if __name__ == '__main__':
    app = App()
    app.mainloop()
