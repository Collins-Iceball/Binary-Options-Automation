# Binary Options Automation

**Author:** Collins_Obi  
**Repository:** [Collins-Iceball/Binary-Options-Automation](https://github.com/Collins-Iceball/Binary-Options-Automation)

Automated binary-options trading stack for **Pocket Option** and **CloseOption**, with a CustomTkinter launcher dashboard, strategy config GUIs, Quick Trade mode, martingale controls, take-profit / stop-loss, and historical backtesting.

This project started from a public Pocket Option bot base and has been **heavily rewritten and extended** by Collins_Obi (GUI launcher, CloseOption adapter, Quick Trade, balance settlement, session handling, and operational tooling).

---

## Features

- Unified launcher dashboard (`startup.py`) — pick platform, launch, live balance / P/L / sessions / equity curve
- Pocket Option bot (`pocketoption_bot.py`) — Normal + Quick Trade modes, strategy GUI, TP/SL, martingale
- CloseOption bot (`closeoption_gui.py` + `closeoption_bot.py`) — separate broker adapter and settings
- Strategies: moving-average cross, PSAR, Vortex, Marubozu, CCI, Bollinger Bands, optional RSI / Supertrend filters
- Quick Trade: MA direction lock per session, configurable expiry, sessions target, auto-continue
- Backtest helpers (`test_on_historical_data.py`) using `data_1m` / `data_5m`
- Legacy / experimental scripts: `po_bot.py`, `po_bot_indicators.py`, `po_bot_ml.py`

---

## Requirements

- Linux (primary), macOS also workable; Windows not the main target for this fork
- Python 3.10+ (project venv currently uses your local Python)
- Google Chrome
- [.NET 6+](https://dotnet.microsoft.com/en-us/download/dotnet/6.0) — required by `stock-indicators`

---

## Setup

```bash
cd "/path/to/Binary-Options-Automation"   # or pocket_option_trading_bot

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# .NET runtime for stock-indicators
export DOTNET_ROOT=$HOME/.dotnet
export PATH=$PATH:$DOTNET_ROOT:$DOTNET_ROOT/tools
```

See `run.md` for Chrome profile lock cleanup and troubleshooting notes.

---

## Run

**Recommended (launcher + dashboard):**

```bash
source .venv/bin/activate
python3 -u startup.py
```

From the launcher you can start:

| Platform       | What runs              |
|----------------|------------------------|
| Pocket Option  | `pocketoption_bot.py`  |
| CloseOption    | `closeoption_gui.py`   |

**Direct (without launcher):**

```bash
python3 -u pocketoption_bot.py
python3 -u closeoption_gui.py
```

**Other scripts:**

```bash
python3 po_bot_indicators.py          # indicator experiments
python3 po_bot_ml.py                  # ML experiment (needs scikit-learn)
python3 test_on_historical_data.py    # offline backtest
```

---

## Settings

- Pocket Option: `settings.txt` (written by the bot GUI)
- CloseOption: `closeoption_settings.txt` (written by `closeoption_gui.py`)

---

## Project layout (main)

```
startup.py              # Launcher + live dashboard
pocketoption_bot.py     # Pocket Option bot + config GUI
closeoption_gui.py      # CloseOption config GUI
closeoption_bot.py      # CloseOption trading engine
driver.py / utils.py    # Shared helpers (legacy scripts)
requirements.txt
run.md                  # Ops / Chrome / venv notes
data_1m/ data_5m/       # Sample historical candles
```

---

## Disclaimer

Trading involves risk of loss. This software is for education and automation research. Use demo accounts first. Automating third-party broker sites may violate their terms of service — you are responsible for how you use it.

---

## License / credit

Maintained by **Collins_Obi** · [github.com/Collins-Iceball/Binary-Options-Automation](https://github.com/Collins-Iceball/Binary-Options-Automation)
