"""
po_bot_timesfm.py - TimesFM-only trading bot with martingale + pre-launch setup.

TimesFM 3.0 is the sole decision-maker. It forecasts the next N candles with
quantile bands, and trades when the median forecast has a directional edge AND
the uncertainty band is tight enough.

Features:
  - Setup dialog before launch (base bet custom/platform, martingale, max steps)
  - Sets the stake on the PO page before each order (if custom base is enabled)
  - Reads balance before, waits for expiry, reads after to score
  - Martingale ladder: WIN resets, LOSS steps up, DRAW keeps same stake
  - Running P&L, W/L/D counters, next-stake preview
"""

import base64
import json
import sys
import time
from datetime import datetime, timedelta

import numpy as np
from selenium.webdriver.common.by import By

from driver import get_driver
from timesfm_signal import _load as _tfm_load


# ============================================================
# SETTINGS
# ============================================================
SETTINGS_FILE = 'po_bot_timesfm_settings.json'

BASE_URL = 'https://pocketoption.com'
PERIOD = 0
CANDLES = []
CURRENCY = None
CURRENCY_CHANGE = False
CURRENCY_CHANGE_DATE = datetime.now()

HORIZON_STEPS = 1
BASELINE_LOOKBACK = 8     # compare forecast to mean of last N closes (not just the last one)

# Binary options is a hit-rate game - we need direction to be right often enough
# to beat the payout, not to be precise in magnitude.
MIN_EDGE = 0.00003        # minimum |median move| / price to consider a signal (0.003%)
MAX_BAND = 0.003          # maximum quantile band width / price to accept (0.30%)
COOLDOWN_SECONDS = 3

LAST_TRADE_AT = datetime(2000, 1, 1)
TRADES = 0

# ---- Martingale (populated by the setup dialog before launch) ----
USE_CUSTOM_BASE_BET = True
BASE_BET            = 1.0
PLATFORM_BASE_BET   = None
MARTINGALE_MULT     = 2.1
MAX_STEPS           = 7
CURRENT_STEP        = 0
PENDING             = None
TOTAL_PROFIT        = 0.0
SESSION_WINS        = 0
SESSION_LOSSES      = 0
SESSION_DRAWS       = 0


# ---- Emoji ----
EMO_BUY   = '🟩💹'
EMO_SELL  = '🟥🔻'
EMO_WAIT  = '⏳'
EMO_CLOCK = '⏰'
EMO_TFM   = '🤖'
EMO_UP    = '🟢'
EMO_DOWN  = '🔴'
EMO_FLAT  = '🟡'
EMO_WIN   = '💲💱'
EMO_LOSS  = '♨️❌'
EMO_TIE   = '🟠♊️'


# ============================================================
# DRIVER (populated after the setup dialog)
# ============================================================
driver = None


def load_web_driver():
    driver.get(f'{BASE_URL}/en/cabinet/demo-quick-high-low/')


# ============================================================
# SETUP DIALOG
# ============================================================
def run_setup_dialog():
    """Simple pre-launch config: base bet (custom or platform), martingale, max steps."""
    import customtkinter as ctk
    import json as _json

    saved = {}
    try:
        with open(SETTINGS_FILE) as f:
            saved = _json.load(f)
    except Exception:
        pass

    ctk.set_appearance_mode('dark')
    ctk.set_default_color_theme('dark-blue')

    root = ctk.CTk()
    root.title('TimesFM Bot - Settings')
    root.geometry('480x460')
    root.resizable(False, False)
    root.configure(fg_color='#0f1117')

    result = {'started': False}

    ctk.CTkLabel(root, text='TimesFM Bot Settings',
                 font=('TkDefaultFont', 20, 'bold'),
                 text_color='#e8eaf0').pack(pady=(24, 4))
    ctk.CTkLabel(root, text='Configure before launch',
                 font=('TkDefaultFont', 11),
                 text_color='#8b90a3').pack(pady=(0, 20))

    body = ctk.CTkFrame(root, fg_color='transparent')
    body.pack(fill='x', padx=32)
    body.grid_columnconfigure(0, weight=1)
    body.grid_columnconfigure(1, weight=0)

    # --- Base bet mode: radio buttons (visible in every customtkinter theme) ---
    ctk.CTkLabel(body, text='Base bet source',
                 font=('TkDefaultFont', 11, 'bold'),
                 text_color='#8b90a3', anchor='w').grid(
        row=0, column=0, columnspan=2, sticky='w', pady=(0, 6))

    mode_var = ctk.StringVar(
        value='custom' if saved.get('use_custom_base_bet', True) else 'platform')

    ctk.CTkRadioButton(body, text='Custom amount',
                       variable=mode_var, value='custom',
                       font=('TkDefaultFont', 12),
                       text_color='#e8eaf0',
                       radiobutton_width=20, radiobutton_height=20,
                       border_width_checked=6,
                       fg_color='#3d7eff', hover_color='#5a91ff').grid(
        row=1, column=0, columnspan=2, sticky='w', pady=2)

    ctk.CTkRadioButton(body, text='Use platform value',
                       variable=mode_var, value='platform',
                       font=('TkDefaultFont', 12),
                       text_color='#e8eaf0',
                       radiobutton_width=20, radiobutton_height=20,
                       border_width_checked=6,
                       fg_color='#3d7eff', hover_color='#5a91ff').grid(
        row=2, column=0, columnspan=2, sticky='w', pady=2)

    # --- Values ---
    base_bet_var = ctk.StringVar(value=str(saved.get('base_bet', 1.0)))
    mult_var     = ctk.StringVar(value=str(saved.get('martingale_mult', 2.1)))
    steps_var    = ctk.StringVar(value=str(saved.get('max_steps', 7)))

    ctk.CTkLabel(body, text='Base bet $',
                 font=('TkDefaultFont', 12),
                 text_color='#e8eaf0', anchor='w').grid(
        row=3, column=0, sticky='w', pady=(16, 4))
    base_entry = ctk.CTkEntry(body, textvariable=base_bet_var, width=140,
                              height=34, justify='right', corner_radius=8)
    base_entry.grid(row=3, column=1, sticky='e', pady=(16, 4))

    ctk.CTkLabel(body, text='Martingale x',
                 font=('TkDefaultFont', 12),
                 text_color='#e8eaf0', anchor='w').grid(
        row=4, column=0, sticky='w', pady=4)
    ctk.CTkEntry(body, textvariable=mult_var, width=140,
                 height=34, justify='right', corner_radius=8).grid(
        row=4, column=1, sticky='e', pady=4)

    ctk.CTkLabel(body, text='Max steps',
                 font=('TkDefaultFont', 12),
                 text_color='#e8eaf0', anchor='w').grid(
        row=5, column=0, sticky='w', pady=4)
    ctk.CTkEntry(body, textvariable=steps_var, width=140,
                 height=34, justify='right', corner_radius=8).grid(
        row=5, column=1, sticky='e', pady=4)

    err_var = ctk.StringVar(value='')
    ctk.CTkLabel(body, textvariable=err_var, font=('TkDefaultFont', 11),
                 text_color='#ff6b81', anchor='w', wraplength=420).grid(
        row=6, column=0, columnspan=2, sticky='w', pady=(14, 0))

    def toggle_base_entry(*args):
        try:
            base_entry.configure(
                state='normal' if mode_var.get() == 'custom' else 'disabled')
        except Exception:
            pass

    mode_var.trace_add('write', toggle_base_entry)
    toggle_base_entry()

    def on_start():
        try:
            base  = float(base_bet_var.get())
            mult  = float(mult_var.get())
            steps = int(float(steps_var.get()))
            if base < 0.01:
                raise ValueError('base bet must be > 0')
            if mult <= 1:
                raise ValueError('martingale multiplier must be > 1')
            if steps < 1:
                raise ValueError('max steps must be >= 1')
        except Exception as e:
            err_var.set(f'Warning: {e}')
            return

        try:
            with open(SETTINGS_FILE, 'w') as f:
                _json.dump({
                    'use_custom_base_bet': mode_var.get() == 'custom',
                    'base_bet': base,
                    'martingale_mult': mult,
                    'max_steps': steps,
                }, f, indent=2)
        except Exception:
            pass

        result.update({
            'started': True,
            'use_custom_base_bet': mode_var.get() == 'custom',
            'base_bet': base,
            'martingale_mult': mult,
            'max_steps': steps,
        })
        root.destroy()

    btns = ctk.CTkFrame(root, fg_color='transparent')
    btns.pack(fill='x', padx=32, pady=(28, 0))
    ctk.CTkButton(btns, text='START', command=on_start,
                  fg_color='#3d7eff', hover_color='#5a91ff',
                  corner_radius=10, width=140, height=44,
                  font=('TkDefaultFont', 13, 'bold')).pack(side='right')
    ctk.CTkButton(btns, text='Cancel',
                  command=lambda: (result.update({'started': False}), root.destroy()),
                  fg_color='#252a3c', hover_color='#333a52',
                  text_color='#8b90a3', corner_radius=10,
                  width=100, height=44,
                  font=('TkDefaultFont', 12)).pack(side='right', padx=(0, 10))

    root.mainloop()
    return result

# ============================================================
# BET + BALANCE HELPERS
# ============================================================
def current_bet_amount():
    """Stake for the next trade based on martingale step."""
    base = BASE_BET if USE_CUSTOM_BASE_BET else (PLATFORM_BASE_BET or BASE_BET)
    if CURRENT_STEP <= 0:
        amt = base
    else:
        amt = base * (MARTINGALE_MULT ** CURRENT_STEP)
    amt = round(amt, 2)
    if amt < 1:
        amt = 1.0
    return amt


def set_bet_amount(amount):
    """Inject the stake into PO's bet field and verify it landed."""
    try:
        js = f"""
        var input = document.querySelector('#put-call-buttons-chart-1 input[type="text"]');
        if(!input) input = document.querySelector('.block--bet-amount input');
        if(input) {{
            var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
            setter.call(input, '{amount}');
            input.dispatchEvent(new Event('input', {{bubbles: true}}));
            input.dispatchEvent(new Event('change', {{bubbles: true}}));
            return true;
        }}
        return false;
        """
        ok = driver.execute_script(js)
        if not ok:
            print('⚠️  could not find bet field')
            return False
        time.sleep(0.15)
        val = driver.execute_script(
            "var i=document.querySelector('#put-call-buttons-chart-1 input[type=text]');"
            "return i ? i.value : null;")
        try:
            if abs(float(val) - float(amount)) < 0.01:
                return True
            print(f'⚠️  amount shows {val} after setting {amount}')
            return False
        except Exception:
            return False
    except Exception as e:
        print(f'⚠️  set_bet_amount failed: {e}')
        return False


def read_platform_bet():
    """Read the current bet amount shown on the PO page."""
    try:
        val = driver.execute_script(
            "var i=document.querySelector('#put-call-buttons-chart-1 input[type=text]');"
            "return i ? i.value : null;")
        if val:
            return float(str(val).replace(',', ''))
    except Exception:
        pass
    return None


def read_balance():
    """Read the PO balance. Returns float or None."""
    try:
        el = driver.find_element(By.CSS_SELECTOR, '.balance-info-block__balance')
        text = el.text.replace(',', '').replace('$', '').replace('€', '').replace('£', '').strip()
        return float(text)
    except Exception:
        pass
    try:
        js = r"""
        let header = document.querySelector('header') || document.body;
        let text = header.innerText;
        let match = text.match(/([$€£])?\s*([\d,]+\.?\d*)/);
        if(match) return match[2].replace(',', '');
        return null;
        """
        val = driver.execute_script(js)
        if val:
            return float(val)
    except Exception:
        pass
    return None


# ============================================================
# TRADE PLACEMENT
# ============================================================
def do_action(signal):
    global LAST_TRADE_AT, TRADES, PENDING
    if datetime.now() < LAST_TRADE_AT + timedelta(seconds=COOLDOWN_SECONDS):
        return
    if PENDING is not None:
        return

    amount = current_bet_amount()

    # Only push the amount onto the page if the user wants a custom base bet.
    # Otherwise, respect whatever's already there and just use it for scoring.
    if USE_CUSTOM_BASE_BET:
        if not set_bet_amount(amount):
            print(f'❌ aborting trade - could not set amount')
            return
    else:
        platform_amt = read_platform_bet()
        if platform_amt is not None:
            amount = round(platform_amt * (MARTINGALE_MULT ** CURRENT_STEP), 2)
            if CURRENT_STEP > 0:
                # In martingale step we DO need to override on the page even in
                # platform mode, otherwise the ladder never actually escalates.
                if not set_bet_amount(amount):
                    print(f'❌ aborting trade - could not set martingale amount')
                    return

    balance_before = read_balance()
    if balance_before is None:
        print(f'❌ aborting trade - could not read balance')
        return

    try:
        last_price = CANDLES[-1][2]
        emo = EMO_BUY if signal == 'call' else EMO_SELL
        expiry = PERIOD if PERIOD > 0 else 10
        print(f'{EMO_CLOCK} {datetime.now().strftime("%H:%M:%S")} '
              f'{emo} {signal.upper()} on {CURRENCY} @ {last_price}  '
              f'|  stake ${amount}  |  step {CURRENT_STEP}  |  expiry {expiry}s')
        driver.find_element(by=By.CLASS_NAME, value=f'btn-{signal}').click()
        LAST_TRADE_AT = datetime.now()
        TRADES += 1
        PENDING = {
            'balance_before': balance_before,
            'amount': amount,
            'resolves_at': datetime.now() + timedelta(seconds=expiry + 2),
            'direction': signal,
        }
    except Exception as e:
        print(f'❌ order failed: {e}')
        PENDING = None


# ============================================================
# SCORING
# ============================================================
def score_pending_trade():
    """If a trade is open and past its expiry, read the settled balance and
    update martingale state."""
    global PENDING, CURRENT_STEP, TOTAL_PROFIT
    global SESSION_WINS, SESSION_LOSSES, SESSION_DRAWS

    if PENDING is None:
        return
    if datetime.now() < PENDING['resolves_at']:
        return

    bal_after = read_balance()
    if bal_after is None or bal_after <= 0:
        return

    delta = bal_after - PENDING['balance_before']
    bet   = PENDING['amount']

    tol = max(bet * 0.1, 0.02)
    if abs(delta + bet) <= tol:
        outcome = 'LOSS'
    elif delta > tol:
        outcome = 'WIN'
    else:
        outcome = 'DRAW'

    TOTAL_PROFIT += delta

    if outcome == 'WIN':
        SESSION_WINS += 1
        CURRENT_STEP = 0
        emo = EMO_WIN
    elif outcome == 'LOSS':
        SESSION_LOSSES += 1
        CURRENT_STEP += 1
        if CURRENT_STEP >= MAX_STEPS:
            print(f'   ⚠️  max martingale steps ({MAX_STEPS}) reached - resetting to base')
            CURRENT_STEP = 0
        emo = EMO_LOSS
    else:
        SESSION_DRAWS += 1
        emo = EMO_TIE

    next_bet = current_bet_amount()
    pnl_emo  = '🤑🤑' if TOTAL_PROFIT > 0 else '😞😞'
    print(f'   {emo} {outcome}  |  delta {delta:+.2f}  |  '
          f'run P/L {TOTAL_PROFIT:+.2f} {pnl_emo}  |  '
          f'next ${next_bet} (step {CURRENT_STEP})  |  '
          f'W{SESSION_WINS} L{SESSION_LOSSES} D{SESSION_DRAWS}')

    PENDING = None


# ============================================================
# TIMESFM ANALYSIS
# ============================================================
def analyze(candles):
    """Run TimesFM on the last N candles and convert the forecast into a signal."""
    if len(candles) < 64:
        return None

    closes = np.array([float(c[2]) for c in candles], dtype=np.float32)
    last_price = float(closes[-1])

    forecaster = _tfm_load()
    try:
        t0 = time.time()
        out = forecaster.predict(context=closes, horizon=HORIZON_STEPS)
        infer_ms = int((time.time() - t0) * 1000)
    except Exception as e:
        print(f'{EMO_TFM} inference failed: {e}')
        return None

    median = np.asarray(out.forecast).flatten()
    median_last = float(median[-1]) if median.size else last_price

    quantiles = None
    for attr in ('quantiles', 'forecast_quantiles', 'quantile_forecast'):
        q = getattr(out, attr, None)
        if q is not None:
            quantiles = np.asarray(q)
            break

    if quantiles is not None and quantiles.ndim == 2:
        step = quantiles[min(HORIZON_STEPS - 1, quantiles.shape[0] - 1)]
        p_low  = float(np.min(step))
        p_mid  = float(np.median(step))
        p_high = float(np.max(step))
        band   = p_high - p_low
    else:
        recent = closes[-20:]
        band   = float(np.std(recent)) * 2
        p_low  = median_last - band / 2
        p_mid  = median_last
        p_high = median_last + band / 2

    # ---- Detrend the forecast ----
    # TimesFM has a mean-reversion bias: it forecasts toward the context mean,
    # so in a downtrend it always predicts slightly UP (and vice versa). If we
    # compare the forecast to just the LAST close, that bias shows up as a
    # persistent directional signal. Two corrections:
    #
    #   1. Compare the forecast to a BASELINE (mean of last N closes), not the
    #      very last close. This cancels the "last candle is unusually low" effect.
    #   2. Subtract the recent DRIFT (mean per-candle return), which cancels
    #      the model's tendency to forecast in the direction of the mean.
    baseline = float(np.mean(closes[-BASELINE_LOOKBACK:]))
    recent_returns = np.diff(closes[-BASELINE_LOOKBACK - 1:]) / closes[-BASELINE_LOOKBACK - 1:-1]
    recent_drift = float(np.mean(recent_returns)) if recent_returns.size else 0.0

    # Detrended edge: forecast vs baseline, minus what price would naturally do.
    edge     = ((p_mid - baseline) / baseline) - recent_drift
    band_pct = band / baseline
    upside   = (p_high - baseline) / baseline
    downside = (baseline - p_low) / baseline
    recent_vol = float(np.std(np.diff(closes[-30:]) / closes[-30:-1])) if len(closes) >= 30 else 0.0

    analysis = {
        'last': last_price, 'baseline': baseline,
        'p_low': p_low, 'p_mid': p_mid, 'p_high': p_high,
        'edge': edge, 'band_pct': band_pct,
        'upside': upside, 'downside': downside,
        'recent_drift': recent_drift, 'recent_vol': recent_vol,
        'infer_ms': infer_ms,
    }

    direction = None
    if edge > MIN_EDGE and band_pct < MAX_BAND:
        direction = 'call'
    elif edge < -MIN_EDGE and band_pct < MAX_BAND:
        direction = 'put'

    analysis['direction'] = direction
    return analysis


def print_analysis(a):
    arrow = EMO_UP if a['edge'] > 0 else (EMO_DOWN if a['edge'] < 0 else EMO_FLAT)
    drift_arrow = '↗' if a.get('recent_drift', 0) > 0 else '↘'
    print(f'{EMO_TFM} TimesFM ({a["infer_ms"]} ms)  price={a["last"]:.5f}  '
          f'baseline={a["baseline"]:.5f}  forecast={a["p_mid"]:.5f}  {arrow} '
          f'edge={a["edge"]*100:+.4f}%  band={a["band_pct"]*100:.4f}%  '
          f'drift {drift_arrow}{a["recent_drift"]*100:+.4f}%')
    if a['direction']:
        return
    if abs(a['edge']) <= MIN_EDGE:
        print(f'   ⏸  edge too small (|{a["edge"]*100:.4f}%| < {MIN_EDGE*100:.4f}%)')
    elif a['band_pct'] >= MAX_BAND:
        print(f'   ⏸  band too wide ({a["band_pct"]*100:.4f}% >= {MAX_BAND*100:.4f}%) - not confident')


# ============================================================
# SOCKET READER
# ============================================================
def websocket_log():
    global CURRENCY, CURRENCY_CHANGE, CURRENCY_CHANGE_DATE, PERIOD, CANDLES

    score_pending_trade()

    try:
        symbol_el = driver.find_element(by=By.CLASS_NAME, value='current-symbol')
        symbol = symbol_el.text
        if symbol != CURRENCY:
            CURRENCY = symbol
            CURRENCY_CHANGE = True
            CURRENCY_CHANGE_DATE = datetime.now()
            print(f'{EMO_CLOCK} {datetime.now().strftime("%H:%M:%S")} switching to {symbol}')
    except Exception:
        pass

    if CURRENCY_CHANGE and CURRENCY_CHANGE_DATE < datetime.now() - timedelta(seconds=5):
        driver.refresh()
        CURRENCY_CHANGE = False
        CANDLES = []
        PERIOD = 0

    try:
        entries = driver.get_log('performance')
    except Exception:
        return

    for wsData in entries:
        message = json.loads(wsData['message'])['message']
        response = message.get('params', {}).get('response', {})
        if response.get('opcode', 0) != 2 or CURRENCY_CHANGE:
            continue
        try:
            payload = base64.b64decode(response['payloadData']).decode('utf-8')
            data = json.loads(payload)
        except Exception:
            continue

        if 'asset' in data and 'candles' in data:
            PERIOD = data['period']
            CANDLES = list(reversed(data['candles']))
            CANDLES.append([CANDLES[-1][0] + PERIOD, CANDLES[-1][1], CANDLES[-1][2],
                            CANDLES[-1][3], CANDLES[-1][4]])
            for tstamp, value in data['history']:
                tstamp = int(float(tstamp))
                CANDLES[-1][2] = value
                if value > CANDLES[-1][3]:
                    CANDLES[-1][3] = value
                elif value < CANDLES[-1][4]:
                    CANDLES[-1][4] = value
                if tstamp % PERIOD == 0 and tstamp not in [c[0] for c in CANDLES]:
                    CANDLES.append([tstamp, value, value, value, value])
            print(f'📊 got {len(CANDLES)} candles for {data["asset"]}  (period {PERIOD}s)')

        try:
            current_value = data[0][2]
            CANDLES[-1][2] = current_value
            if current_value > CANDLES[-1][3]:
                CANDLES[-1][3] = current_value
            elif current_value < CANDLES[-1][4]:
                CANDLES[-1][4] = current_value
            tstamp = int(float(data[0][1]))
            if tstamp % PERIOD == 0 and tstamp not in [c[0] for c in CANDLES]:
                if PENDING is not None:
                    print(f'   ⏸ trade open, waiting for settlement...')
                else:
                    try:
                        a = analyze(CANDLES)
                        if a:
                            print_analysis(a)
                            if a['direction']:
                                do_action(a['direction'])
                            else:
                                print(f'{EMO_WAIT} no trade - waiting for stronger signal')
                    except Exception as e:
                        print(f'❌ analyze failed: {e}')
                CANDLES.append([tstamp, current_value, current_value,
                                current_value, current_value])
        except Exception:
            pass


# ============================================================
# MAIN
# ============================================================
if __name__ == '__main__':
    # 1. Setup dialog
    print('opening setup dialog...')
    cfg = run_setup_dialog()
    if not cfg.get('started'):
        print('cancelled - exiting.')
        sys.exit(0)

    g = globals()
    g['USE_CUSTOM_BASE_BET'] = cfg['use_custom_base_bet']
    g['BASE_BET'] = cfg['base_bet']
    g['MARTINGALE_MULT'] = cfg['martingale_mult']
    g['MAX_STEPS'] = cfg['max_steps']

    base_str = f'${cfg["base_bet"]:.2f}' if cfg['use_custom_base_bet'] else 'platform value'
    print(f'⚙️  settings: base bet = {base_str}  |  '
          f'martingale x{cfg["martingale_mult"]}  |  '
          f'max steps {cfg["max_steps"]}')

    # 2. Load TimesFM
    print(f'{EMO_TFM} loading TimesFM 3.0...')
    _tfm_load()
    print(f'{EMO_TFM} ready.')

    # 3. Launch Chrome
    g['driver'] = get_driver()
    load_web_driver()

    # 4. Wait for the page, read platform bet if needed
    time.sleep(4)
    if not cfg['use_custom_base_bet']:
        pb = read_platform_bet()
        if pb is not None:
            g['PLATFORM_BASE_BET'] = pb
            print(f'⚙️  platform base bet detected: ${pb:.2f}')
        else:
            print(f'⚠️  could not read platform bet - falling back to ${BASE_BET:.2f}')

    print(f'{EMO_WAIT} waiting for chart data... (log in to PO, open the demo trade room)')
    while True:
        websocket_log()
        time.sleep(0.25)
