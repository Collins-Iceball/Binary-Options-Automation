"""
startup.py - Launcher + live dashboard for Binary Options Automation.

Author: Collins_Obi
Repo: https://github.com/Collins-Iceball/Binary-Options-Automation

Layout:
  header -> controls -> metrics -> session strip -> equity chart -> log

Parses the bot's stdout to keep the dashboard live. Works with both
pocketoption_bot.py and closeoption_gui.py output formats.
"""

import os
import re
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from tkinter import messagebox

import customtkinter as ctk

try:
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    HAS_MPL = True
except ImportError:
    HAS_MPL = False


BOT_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_PY = os.path.join(BOT_DIR, '.venv', 'bin', 'python3')


PLATFORMS = {
    'pocketoption': {
        'label':       'Pocket Option',
        'subtitle':    'pocketoption.com',
        'accent':      '#3d7eff',
        'script':      'pocketoption_bot.py',
        'profile_dir': 'Trading Bot Profile',
    },
    'closeoption': {
        'label':       'CloseOption',
        'subtitle':    'closeoption.com',
        'accent':      '#f4c95d',
        'script':      'closeoption_gui.py',
        'profile_dir': 'CloseOption Profile',
    },
}


# ---------------------------------------------------------------
# Palette
# ---------------------------------------------------------------
BG         = '#0f1117'
CARD_BG    = '#171b26'
CARD_SEL   = '#1f2435'
CARD_HOV   = '#1c2130'
CHART_BG   = '#0a0c14'
FG         = '#e8eaf0'
FG_DIM     = '#8b90a3'
FG_FAINT   = '#565c72'
GO_HOVER   = '#5a91ff'
STOP_BG    = '#252a3c'
STOP_HOVER = '#333a52'
BORDER     = '#232838'
LOG_BG     = '#0a0c14'
GREEN      = '#52dba0'
RED        = '#ff6b81'
YELLOW     = '#f4c95d'


ctk.set_appearance_mode('dark')
ctk.set_default_color_theme('dark-blue')


class PlatformCard(ctk.CTkFrame):
    def __init__(self, parent, key, cfg, variable, on_select):
        super().__init__(parent, corner_radius=14, border_width=2,
                         border_color=BORDER, fg_color=CARD_BG)
        self.key = key
        self.cfg = cfg
        self.var = variable
        self.on_select = on_select

        inner = ctk.CTkFrame(self, fg_color='transparent')
        inner.pack(fill='both', expand=True, padx=16, pady=12)

        row = ctk.CTkFrame(inner, fg_color='transparent')
        row.pack(fill='x', anchor='w')
        ctk.CTkLabel(row, text='●', text_color=cfg['accent'],
                     font=('TkDefaultFont', 16, 'bold')).pack(side='left')
        ctk.CTkLabel(row, text=cfg['label'], text_color=FG,
                     font=('TkDefaultFont', 14, 'bold')).pack(side='left', padx=(8, 0))
        ctk.CTkLabel(inner, text=cfg['subtitle'], text_color=FG_DIM,
                     font=('TkDefaultFont', 10), anchor='w').pack(fill='x', pady=(2, 0))

        self._bind_all(self)
        self._refresh()

    def _bind_all(self, w):
        try:
            w.bind('<Button-1>', self._click, add='+')
            w.bind('<Enter>', self._enter, add='+')
            w.bind('<Leave>', self._leave, add='+')
        except Exception:
            pass
        try:
            for c in w.winfo_children():
                self._bind_all(c)
        except Exception:
            pass

    def _click(self, _e=None):
        self.var.set(self.key)
        self.on_select()

    def _enter(self, _e=None):
        if not self._is_sel():
            self.configure(fg_color=CARD_HOV, border_color=BORDER)

    def _leave(self, _e=None):
        self._refresh()

    def _is_sel(self):
        return self.var.get() == self.key

    def _refresh(self):
        if self._is_sel():
            self.configure(fg_color=CARD_SEL, border_color=self.cfg['accent'])
        else:
            self.configure(fg_color=CARD_BG, border_color=BORDER)


class Launcher:
    def __init__(self):
        self.root = ctk.CTk()
        self.root.title('Binary Options Automation — Collins_Obi')
        self.root.geometry('1300x920')
        self.root.minsize(1100, 760)
        self.root.configure(fg_color=BG)

        self.proc = None
        self.reader_thread = None
        self.selected = ctk.StringVar(value='pocketoption')
        self.cards = {}

        # ---- dashboard state ----
        self.initial_deposit = None
        self.balance = None
        self.run_pnl = 0.0
        self.sessions_won = 0
        self.sessions_busted = 0
        self.current_step = 0
        self.next_stake = None
        self.chip_widgets = []
        self.equity_points = []

        # ---- live vars ----
        self.balance_var = ctk.StringVar(value='—')
        self.balance_sub = ctk.StringVar(value='waiting for bot...')
        self.pnl_var = ctk.StringVar(value='—')
        self.pnl_sub = ctk.StringVar(value='')
        self.sessions_var = ctk.StringVar(value='0 / 0')
        self.sessions_sub = ctk.StringVar(value='Step — · Next —')

        self._build()
        self.root.protocol('WM_DELETE_WINDOW', self._on_close)

    # ==================================================
    # Build
    # ==================================================
    def _build(self):
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(7, weight=1)

        self._build_header()
        self._build_controls()
        self._build_metrics()
        self._build_strip()
        self._build_chart()
        self._build_input_bar()
        self._build_log()

    def _build_header(self):
        header = ctk.CTkFrame(self.root, fg_color='transparent')
        header.grid(row=0, column=0, sticky='ew', padx=28, pady=(22, 4))

        ctk.CTkLabel(header, text='Binary Options', text_color=FG,
                     font=('TkDefaultFont', 24, 'bold')).pack(side='left')
        ctk.CTkLabel(header, text='  Automation', text_color='#3d7eff',
                     font=('TkDefaultFont', 24, 'bold')).pack(side='left')
        ctk.CTkLabel(header, text='  · Collins_Obi', text_color=FG_DIM,
                     font=('TkDefaultFont', 12)).pack(side='left', padx=(8, 0), pady=(10, 0))

        self.pill = ctk.CTkLabel(
            header, text='  ● IDLE  ',
            fg_color='#222736', text_color=FG_DIM,
            corner_radius=20, font=('TkDefaultFont', 11, 'bold'),
            padx=14, pady=6)
        self.pill.pack(side='right', pady=(8, 0))

    def _build_controls(self):
        row = ctk.CTkFrame(self.root, fg_color='transparent')
        row.grid(row=1, column=0, sticky='ew', padx=28, pady=(6, 14))

        cards_row = ctk.CTkFrame(row, fg_color='transparent')
        cards_row.pack(side='left', fill='x', expand=True)

        keys = list(PLATFORMS.keys())
        for i, key in enumerate(keys):
            cfg = PLATFORMS[key]
            card = PlatformCard(cards_row, key, cfg, self.selected, self._on_select)
            pad = (0, 12) if i < len(keys) - 1 else (0, 0)
            card.pack(side='left', padx=pad)
            self.cards[key] = card

        btns = ctk.CTkFrame(row, fg_color='transparent')
        btns.pack(side='right', padx=(20, 0))

        self.go_btn = ctk.CTkButton(
            btns, text='▶   GO', command=self.go,
            fg_color='#3d7eff', hover_color=GO_HOVER,
            text_color='white', corner_radius=12,
            font=('TkDefaultFont', 13, 'bold'),
            width=130, height=48)
        self.go_btn.pack(side='left')

        self.stop_btn = ctk.CTkButton(
            btns, text='■   STOP', command=self.stop,
            fg_color=STOP_BG, hover_color=STOP_HOVER,
            text_color=FG_DIM, corner_radius=12,
            font=('TkDefaultFont', 13, 'bold'),
            width=130, height=48, state='disabled')
        self.stop_btn.pack(side='left', padx=(10, 0))

    def _metric_card(self, parent, title, big_var, sub_var):
        card = ctk.CTkFrame(parent, fg_color=CARD_BG, corner_radius=14,
                            border_width=1, border_color=BORDER)
        inner = ctk.CTkFrame(card, fg_color='transparent')
        inner.pack(fill='both', expand=True, padx=20, pady=16)
        ctk.CTkLabel(inner, text=title, text_color=FG_DIM,
                     font=('TkDefaultFont', 11, 'bold'),
                     anchor='w').pack(fill='x')
        ctk.CTkLabel(inner, textvariable=big_var, text_color=FG,
                     font=('TkDefaultFont', 26, 'bold'),
                     anchor='w').pack(fill='x', pady=(6, 2))
        ctk.CTkLabel(inner, textvariable=sub_var, text_color=FG_DIM,
                     font=('TkDefaultFont', 11),
                     anchor='w').pack(fill='x')
        return card

    def _build_metrics(self):
        row = ctk.CTkFrame(self.root, fg_color='transparent')
        row.grid(row=2, column=0, sticky='ew', padx=28, pady=(0, 10))
        row.grid_columnconfigure((0, 1, 2), weight=1)

        c1 = self._metric_card(row, 'BALANCE', self.balance_var, self.balance_sub)
        c1.grid(row=0, column=0, sticky='nsew', padx=(0, 10))

        c2 = self._metric_card(row, 'RUN P/L', self.pnl_var, self.pnl_sub)
        c2.grid(row=0, column=1, sticky='nsew', padx=(0, 10))

        c3 = self._metric_card(row, 'SESSIONS', self.sessions_var, self.sessions_sub)
        c3.grid(row=0, column=2, sticky='nsew')

        # keep refs for recolouring big numbers
        self._pnl_widget = c2.winfo_children()[0].winfo_children()[1]
        self._bal_widget = c1.winfo_children()[0].winfo_children()[1]

    def _build_strip(self):
        wrap = ctk.CTkFrame(self.root, fg_color=CARD_BG, corner_radius=14,
                            border_width=1, border_color=BORDER)
        wrap.grid(row=3, column=0, sticky='ew', padx=28, pady=(0, 10))

        head = ctk.CTkFrame(wrap, fg_color='transparent')
        head.pack(fill='x', padx=16, pady=(10, 2))
        ctk.CTkLabel(head, text='SESSION HISTORY', text_color=FG_DIM,
                     font=('TkDefaultFont', 10, 'bold'), anchor='w').pack(side='left')
        self.strip_count = ctk.CTkLabel(head, text='', text_color=FG_FAINT,
                                        font=('TkDefaultFont', 10), anchor='e')
        self.strip_count.pack(side='right')

        self.strip_inner = ctk.CTkFrame(wrap, fg_color='transparent', height=28)
        self.strip_inner.pack(fill='x', padx=16, pady=(2, 12))
        self.strip_inner.pack_propagate(False)

        # empty placeholder
        self.strip_placeholder = ctk.CTkLabel(
            self.strip_inner, text='no sessions yet',
            text_color=FG_FAINT, font=('TkDefaultFont', 10), anchor='w')
        self.strip_placeholder.pack(side='left')

    def _build_chart(self):
        wrap = ctk.CTkFrame(self.root, fg_color=CARD_BG, corner_radius=14,
                            border_width=1, border_color=BORDER)
        wrap.grid(row=4, column=0, sticky='ew', padx=28, pady=(0, 10))

        head = ctk.CTkFrame(wrap, fg_color='transparent')
        head.pack(fill='x', padx=16, pady=(10, 0))
        ctk.CTkLabel(head, text='EQUITY CURVE', text_color=FG_DIM,
                     font=('TkDefaultFont', 10, 'bold'), anchor='w').pack(side='left')
        self.chart_meta = ctk.CTkLabel(head, text='', text_color=FG_FAINT,
                                       font=('TkDefaultFont', 10), anchor='e')
        self.chart_meta.pack(side='right')

        chart_body = ctk.CTkFrame(wrap, fg_color='transparent', height=200)
        chart_body.pack(fill='x', padx=12, pady=(4, 12))
        chart_body.pack_propagate(False)

        if HAS_MPL:
            self.fig = Figure(figsize=(10, 2.2), dpi=90, facecolor=CHART_BG)
            self.ax = self.fig.add_subplot(111)
            self.ax.set_facecolor(CHART_BG)
            self._style_axes()
            self.canvas = FigureCanvasTkAgg(self.fig, master=chart_body)
            self.canvas.get_tk_widget().pack(fill='both', expand=True)
            self._redraw_chart()
        else:
            ctk.CTkLabel(chart_body,
                         text='matplotlib not installed\n'
                              'run:  pip install matplotlib',
                         text_color=FG_FAINT,
                         font=('TkDefaultFont', 12)).pack(expand=True)

    def _style_axes(self):
        self.ax.tick_params(colors=FG_DIM, labelsize=8)
        for s in self.ax.spines.values():
            s.set_color(BORDER)
        self.ax.grid(True, color='#1c2130', linestyle='-', linewidth=0.5)
        self.ax.set_ylabel('Balance', color=FG_DIM, fontsize=9)

    def _redraw_chart(self):
        if not HAS_MPL:
            return
        self.ax.clear()
        self.ax.set_facecolor(CHART_BG)
        self._style_axes()

        if len(self.equity_points) >= 2:
            xs = list(range(len(self.equity_points)))
            ys = list(self.equity_points)
            pnl = ys[-1] - ys[0]
            color = GREEN if pnl >= 0 else RED
            self.ax.plot(xs, ys, color=color, linewidth=2)
            self.ax.fill_between(xs, ys, min(ys) - (max(ys) - min(ys) + 1) * 0.02,
                                 color=color, alpha=0.08)
            if self.initial_deposit:
                self.ax.axhline(self.initial_deposit, color=FG_FAINT,
                                linestyle='--', linewidth=0.8)
            self.chart_meta.configure(
                text=f'{len(ys)} points  ·  last {ys[-1]:.2f}  ·  {pnl:+.2f}')
        else:
            self.ax.text(0.5, 0.5, 'waiting for data...',
                         color=FG_FAINT, ha='center', va='center',
                         transform=self.ax.transAxes, fontsize=11)
            self.chart_meta.configure(text='')

        self.fig.tight_layout()
        self.canvas.draw_idle()

    def _build_input_bar(self):
        bar = ctk.CTkFrame(self.root, fg_color=CARD_BG, corner_radius=14,
                          border_width=1, border_color=BORDER)
        bar.grid(row=5, column=0, sticky='ew', padx=28, pady=(0, 10))

        inner = ctk.CTkFrame(bar, fg_color='transparent')
        inner.pack(fill='x', padx=16, pady=10)

        ctk.CTkLabel(inner, text='SEND TO BOT', text_color=FG_DIM,
                     font=('TkDefaultFont', 10, 'bold')).pack(side='left', padx=(0, 12))

        self.input_var = ctk.StringVar(value='')
        self.input_entry = ctk.CTkEntry(
            inner, textvariable=self.input_var, width=300, height=34,
            corner_radius=8, fg_color='#252a3c', border_width=0,
            placeholder_text='type and press Enter (e.g.  y,  n,  a)')
        self.input_entry.pack(side='left')
        self.input_entry.bind('<Return>', lambda e: self._send_input())

        self.send_btn = ctk.CTkButton(
            inner, text='Send', command=self._send_input,
            width=80, height=34, corner_radius=8,
            fg_color='#3d7eff', hover_color='#5a91ff',
            font=('TkDefaultFont', 11, 'bold'))
        self.send_btn.pack(side='left', padx=(8, 16))

        # quick buttons for the common answers
        for label, val in (('Y', 'y'), ('N', 'n'), ('A', 'a')):
            color = '#123a2c' if label == 'Y' else ('#3d3416' if label == 'A' else '#3d1720')
            txt_color = GREEN if label == 'Y' else (YELLOW if label == 'A' else RED)
            ctk.CTkButton(
                inner, text=label, width=44, height=34,
                corner_radius=8, fg_color=color, hover_color=color,
                text_color=txt_color,
                font=('TkDefaultFont', 13, 'bold'),
                command=lambda v=val: self._send_quick(v),
            ).pack(side='left', padx=2)

        self.input_hint = ctk.CTkLabel(inner, text='', text_color=YELLOW,
                                       font=('TkDefaultFont', 10, 'bold'))
        self.input_hint.pack(side='left', padx=(16, 0))

    def _send_input(self):
        if not self.proc or not self.proc.stdin:
            return
        text = self.input_var.get().strip()
        if not text:
            return
        try:
            self.proc.stdin.write(text + '\n')
            self.proc.stdin.flush()
            self.log(f'→ (sent) {text}\n', 'info')
        except Exception as e:
            self.log(f'(send failed: {e})\n', 'error')
        self.input_var.set('')
        self.input_hint.configure(text='')

    def _send_quick(self, value):
        self.input_var.set(value)
        self._send_input()

    def _build_log(self):
        wrap = ctk.CTkFrame(self.root, fg_color=CARD_BG, corner_radius=14,
                            border_width=1, border_color=BORDER)
        wrap.grid(row=7, column=0, sticky='nsew', padx=28, pady=(0, 24))
        wrap.grid_rowconfigure(1, weight=1)
        wrap.grid_columnconfigure(0, weight=1)

        head = ctk.CTkFrame(wrap, fg_color='transparent')
        head.grid(row=0, column=0, columnspan=2, sticky='ew', padx=16, pady=(10, 0))
        ctk.CTkLabel(head, text='LOG', text_color=FG_DIM,
                     font=('TkDefaultFont', 10, 'bold')).pack(side='left')

        self.log_box = ctk.CTkTextbox(
            wrap, corner_radius=10, fg_color=LOG_BG,
            text_color=FG, border_width=0,
            font=ctk.CTkFont(family='Noto Sans Mono', size=11),
            wrap='word',
            scrollbar_button_color='#232838',
            scrollbar_button_hover_color='#333a52')
        self.log_box.grid(row=1, column=0, sticky='nsew', padx=10, pady=(4, 10))
        self._log = self.log_box._textbox
        self._log.tag_config('default', foreground=FG)
        self._log.tag_config('dim',     foreground=FG_DIM)
        self._log.tag_config('error',   foreground=RED)
        self._log.tag_config('win',     foreground=GREEN)
        self._log.tag_config('loss',    foreground=RED)
        self._log.tag_config('info',    foreground='#3d7eff')
        self._log.tag_config('warn',    foreground=YELLOW)

    # ==================================================
    # Stream parsing
    # ==================================================
    def _on_line(self, line):
        tag = self._classify(line)
        self.log(line, tag)
        try:
            self._parse_metrics(line)
        except Exception:
            pass
        # Highlight the input bar when the bot is asking for input.
        low = line.lower()
        if 'do you want to continue' in low or 'press enter' in low \
           or 'press t to terminate' in low or 'y/n/a' in low:
            self.input_hint.configure(text='⬅ bot is waiting for input')
            try:
                self.input_entry.focus_set()
            except Exception:
                pass

    @staticmethod
    def _classify(line):
        low = line.lower()
        if 'error' in low or 'traceback' in low or 'fatal' in low:
            return 'error'
        if 'insufficient' in low or 'warning' in low or 'timed out' in low:
            return 'warn'
        if 'win' in low and ('result' in low or 'session' in low):
            return 'win'
        if 'loss' in low and ('result' in low or 'session' in low or 'cap' in low):
            return 'loss'
        if 'launching' in low or 'ready' in low or 'mode:' in low:
            return 'info'
        return 'default'

    def _parse_metrics(self, line):
        changed = False

        # Initial deposit
        m = re.search(r'Initial deposit:\s*([\d.]+)', line)
        if m:
            self.initial_deposit = float(m.group(1))
            self.balance = self.initial_deposit
            self.run_pnl = 0.0
            self.equity_points = [self.initial_deposit]
            self._update_balance()
            self._update_pnl()
            self._redraw_chart()
            changed = True

        # Balance + Run P/L (CloseOption)
        m = re.search(r'Balance:\s*([\d.]+)\s*\|\s*Run P/L:\s*([+\-]?[\d.]+)', line)
        if m:
            new_bal = float(m.group(1))
            self.run_pnl = float(m.group(2))
            # Only push a new chart point when the balance actually moved.
            # DRAWs print a Balance line but don't change the money, and pushing
            # those points makes the whole loss-side of the curve look flat -
            # visually indistinguishable from the surrounding losses.
            changed_balance = (self.balance is None
                               or abs(new_bal - self.balance) > 0.005)
            self.balance = new_bal
            self._update_balance()
            self._update_pnl()
            if changed_balance:
                self.equity_points.append(self.balance)
                self._redraw_chart()
            changed = True

        # Trade result line (both bots)
        m = re.search(r'\b(WIN|LOSS|DRAW)\b\s*\(delta\s*([+\-]?[\d.]+),\s*step\s*(\d+)\)', line)
        if m:
            self.current_step = int(m.group(3))
            self._update_sessions()
            changed = True

        # Session close WIN (both bots)
        m = re.search(r'session\s+(\d+)/(\d+)\s+closed on\s+\S+\s+WIN', line)
        if m:
            self.sessions_won += 1
            self._push_chip('WIN')
            self._update_sessions()
            changed = True

        # Martingale cap reached (both bots)
        if 'martingale cap' in line and 'reached' in line:
            self.sessions_busted += 1
            self._push_chip('BUST')
            self._update_sessions()
            changed = True

        # Total profit so far (PO only - exact phrase). CO prints 'Total: +X'
        # which used to also match, adding a duplicate chart point on every
        # session close.
        m = re.search(r'Total profit (?:so far|this run):\s*([+\-]?[\d.]+)', line)
        if m:
            try:
                self.run_pnl = float(m.group(1))
                if self.initial_deposit is not None:
                    new_bal = self.initial_deposit + self.run_pnl
                    changed_balance = (self.balance is None
                                       or abs(new_bal - self.balance) > 0.005)
                    self.balance = new_bal
                    if changed_balance:
                        self.equity_points.append(self.balance)
                        self._redraw_chart()
                self._update_balance()
                self._update_pnl()
                changed = True
            except Exception:
                pass

        # Next stake from "stake $X"
        m = re.search(r'stake\s*\$([\d.]+)', line)
        if m:
            self.next_stake = float(m.group(1))
            self._update_sessions()

        return changed

    # ==================================================
    # Dashboard updates
    # ==================================================
    def _update_balance(self):
        if self.balance is None:
            self.balance_var.set('—')
            self.balance_sub.set('waiting for bot...')
            return
        self.balance_var.set(f'${self.balance:,.2f}')
        if self.initial_deposit:
            self.balance_sub.set(f'start: ${self.initial_deposit:,.2f}')
        else:
            self.balance_sub.set('')

    def _update_pnl(self):
        if self.balance is None:
            self.pnl_var.set('—')
            self.pnl_sub.set('')
            return
        sign = '+' if self.run_pnl >= 0 else ''
        self.pnl_var.set(f'{sign}${self.run_pnl:,.2f}')
        self.pnl_sub.set('🤑🤑' if self.run_pnl > 0 else '😞😞')
        try:
            self._pnl_widget.configure(
                text_color=GREEN if self.run_pnl >= 0 else RED)
        except Exception:
            pass

    def _update_sessions(self):
        total = self.sessions_won + self.sessions_busted
        if total == 0:
            self.sessions_var.set('0 / 0')
        else:
            self.sessions_var.set(f'{self.sessions_won} / {total}')
        parts = []
        parts.append(f'step {self.current_step}')
        if self.next_stake is not None:
            parts.append(f'next ${self.next_stake:.0f}')
        self.sessions_sub.set(' · '.join(parts))

    def _push_chip(self, outcome):
        try:
            self.strip_placeholder.pack_forget()
        except Exception:
            pass
        color = GREEN if outcome == 'WIN' else RED
        chip = ctk.CTkFrame(self.strip_inner, fg_color=color,
                            corner_radius=4, width=20, height=20)
        chip.pack(side='left', padx=2, pady=4)
        chip.pack_propagate(False)
        self.chip_widgets.append(chip)

        # cap at 40 so strip stays readable
        if len(self.chip_widgets) > 40:
            old = self.chip_widgets.pop(0)
            try:
                old.destroy()
            except Exception:
                pass

        self.strip_count.configure(
            text=f'{self.sessions_won}W · {self.sessions_busted}L')

    def _reset_dashboard(self):
        self.initial_deposit = None
        self.balance = None
        self.run_pnl = 0.0
        self.sessions_won = 0
        self.sessions_busted = 0
        self.current_step = 0
        self.next_stake = None
        self.equity_points = []
        for w in self.chip_widgets:
            try:
                w.destroy()
            except Exception:
                pass
        self.chip_widgets = []
        try:
            self.strip_placeholder.pack(side='left')
        except Exception:
            pass
        self.balance_var.set('—')
        self.balance_sub.set('waiting for bot...')
        self.pnl_var.set('—')
        self.pnl_sub.set('')
        self.sessions_var.set('0 / 0')
        self.sessions_sub.set('step — · next —')
        self.strip_count.configure(text='')
        self._redraw_chart()

    # ==================================================
    # Log / status
    # ==================================================
    def log(self, text, tag='default'):
        self._log.insert('end', text, tag)
        self._log.see('end')

    def _set_pill(self, state):
        styles = {
            'idle':     ('  ● IDLE  ',     '#222736', FG_DIM),
            'running':  ('  ● RUNNING  ',  '#123a2c', GREEN),
            'stopping': ('  ● STOPPING  ', '#3d3416', YELLOW),
            'error':    ('  ● ERROR  ',    '#3d1720', RED),
        }
        text, bg, fg = styles.get(state, styles['idle'])
        self.pill.configure(text=text, fg_color=bg, text_color=fg)

    def _on_select(self):
        for c in self.cards.values():
            c._refresh()

    # ==================================================
    # Pre-flight
    # ==================================================
    def _cleanup(self, profile_dir):
        self.log(f'\n── Cleanup · {profile_dir} ──\n', 'info')
        try:
            r = subprocess.run(['pgrep', '-f', profile_dir],
                               capture_output=True, text=True, timeout=3)
            pids = [p for p in r.stdout.split('\n') if p.strip()]
            if pids:
                for pid in pids:
                    try:
                        os.kill(int(pid), signal.SIGKILL)
                        self.log(f'  killed stale pid {pid}\n', 'dim')
                    except Exception:
                        pass
            else:
                self.log('  no stale processes\n', 'dim')
        except Exception as e:
            self.log(f'  pgrep failed: {e}\n', 'dim')

        try:
            subprocess.run(['pkill', '-9', '-f', 'chromedriver'],
                           check=False, timeout=3)
            self.log('  cleared stray chromedrivers\n', 'dim')
        except Exception:
            pass

        time.sleep(0.4)

        profile_path = os.path.expanduser(f'~/.config/google-chrome/{profile_dir}')
        for name in ('SingletonLock', 'SingletonSocket', 'SingletonCookie', 'lockfile'):
            p = os.path.join(profile_path, name)
            try:
                if os.path.islink(p) or os.path.isfile(p):
                    os.remove(p)
                    self.log(f'  removed {name}\n', 'dim')
            except Exception:
                pass

    # ==================================================
    # Run / stop
    # ==================================================
    def go(self):
        if self.proc:
            messagebox.showinfo('Already running',
                                'Stop the current bot before starting another.')
            return

        key = self.selected.get()
        cfg = PLATFORMS.get(key)
        if not cfg:
            return

        script_path = os.path.join(BOT_DIR, cfg['script'])
        if not os.path.isfile(script_path):
            messagebox.showerror('Missing script', f'Not found:\n{script_path}')
            self._set_pill('error')
            return
        if not os.path.isfile(VENV_PY):
            messagebox.showerror(
                'Missing virtualenv',
                f'venv python not found at:\n{VENV_PY}')
            self._set_pill('error')
            return

        self.log_box.delete('1.0', 'end')
        self._reset_dashboard()
        self.log(f'{datetime.now().strftime("%H:%M:%S")}  launching {cfg["label"]}\n', 'info')

        self._set_pill('running')
        self._cleanup(cfg['profile_dir'])

        env = os.environ.copy()
        dotnet = os.path.expanduser('~/.dotnet')
        env['DOTNET_ROOT'] = dotnet
        env['PATH'] = f"{dotnet}:{dotnet}/tools:{env.get('PATH', '')}"
        env['PYTHONUNBUFFERED'] = '1'

        try:
            self.proc = subprocess.Popen(
                [VENV_PY, '-u', script_path],
                cwd=BOT_DIR,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
                preexec_fn=os.setsid if os.name != 'nt' else None,
            )
        except Exception as e:
            messagebox.showerror('Launch failed', str(e))
            self.proc = None
            self._set_pill('error')
            return

        self.go_btn.configure(state='disabled', fg_color='#232838',
                              text_color=FG_FAINT)
        self.stop_btn.configure(state='normal', text_color=FG)

        self.reader_thread = threading.Thread(target=self._reader, daemon=True)
        self.reader_thread.start()

    def _reader(self):
        try:
            for line in self.proc.stdout:
                self.root.after(0, self._on_line, line)
        except Exception:
            pass
        self.root.after(0, self._on_exit)

    def _on_exit(self):
        self.go_btn.configure(state='normal', fg_color='#3d7eff', text_color='white')
        self.stop_btn.configure(state='disabled', text_color=FG_DIM)
        self.log(f'\n{datetime.now().strftime("%H:%M:%S")}  bot exited\n', 'dim')
        self._set_pill('idle')
        self.input_hint.configure(text='')
        self.proc = None

    def stop(self):
        if not self.proc:
            return
        proc = self.proc
        self._set_pill('stopping')
        try:
            if os.name != 'nt':
                try:
                    pgid = os.getpgid(proc.pid)
                except ProcessLookupError:
                    self.proc = None
                    return
                os.killpg(pgid, signal.SIGINT)

                def force_kill():
                    if proc.poll() is None:
                        try:
                            os.killpg(pgid, signal.SIGKILL)
                            self.log('(force-killed after 3s)\n', 'warn')
                        except Exception:
                            pass
                self.root.after(3000, force_kill)
            else:
                proc.send_signal(signal.CTRL_BREAK_EVENT)
        except Exception as e:
            self.log(f'(stop failed: {e})\n', 'error')

    def _on_close(self):
        if self.proc:
            try:
                if os.name != 'nt':
                    os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
                else:
                    self.proc.kill()
            except Exception:
                pass
        self.root.destroy()


def main():
    app = Launcher()
    app.root.mainloop()


if __name__ == '__main__':
    main()
