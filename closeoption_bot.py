"""
closeoption_bot.py - CloseOption adapter (option A: separate file).

Author: Collins_Obi
Repo: https://github.com/Collins-Iceball/Binary-Options-Automation

Reuses strategy logic from pocketoption_bot.py but has its own broker layer:
  - Market data: Socket.IO text frames  42["priceData", {...}]
    (Pocket Option sends raw binary JSON in WebSocket opcode-2 frames.)
  - CloseOption does NOT send candle history. We build candles from ticks,
    so the bot needs a warmup period before it will trade.
  - Orders placed by clicking button.Buy / button.Sell.

Known unknowns (worth a 2nd recon pass):
  - Expiry selector (input.curTime is only a hidden mirror of it)
  - Whether /trade/setOrder can be POSTed directly (faster than clicking)
  - Whether an HTTP endpoint serves historical candles (removes warmup)
"""

import asyncio
import json
import os
import platform
import random
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from stock_indicators import indicators, Match, Quote


# ============================================================
# SETTINGS  (loaded from closeoption_settings.txt; GUI writes that file)
# ============================================================
SETTINGS_PATH = 'closeoption_settings.txt'

# Defaults - anything missing from the settings file falls back to these.
_DEFAULTS = {
    'URL':                  'https://www.closeoption.com/trade/room/demo',
    'CANDLE_PERIOD':        10,
    'BET_AMOUNT':           1,
    'MARTINGALE_MULT':      3.0,
    'MAX_MARTINGALE_STEPS': 5,
    'MIN_PAYOUT':           20,
    'EXPIRY_SECONDS':       30,
    'VICE_VERSA':           False,
    'STRATEGY':             1,
    'FAST_MA':              3,
    'FAST_MA_TYPE':         'SMA',
    'SLOW_MA':              8,
    'SLOW_MA_TYPE':         'SMA',
    'VORTEX_PERIOD':        14,
    'MARUBOZU_MIN_BODY':    95,
    'CCI_PERIOD':           20,
    'BB_PERIOD':            20,
    'RSI_ENABLED':          False,
    'RSI_PERIOD':           14,
    'RSI_UPPER':            70,
    'RSI_CALL_SIGN':        '>',
    'SUPERTREND_ENABLED':   False,
    'SUPERTREND_PERIOD':    10,
    'TAKE_PROFIT_ENABLED':  False,
    'TAKE_PROFIT':          100,
    'STOP_LOSS_ENABLED':    False,
    'STOP_LOSS':            50,
    'SOCKET_DEBUG':         False,
    'SMART_FILTERS_ENABLED': True,
    'TREND_FILTER_ENABLED': True,
    'TREND_LOOKBACK':       3,
    'PRICE_ACTION_FILTER':  True,
    'ONE_TRADE_PER_CANDLE': True,
    'LOSS_COOLDOWN_SECONDS': 90,
    'TRADING_MODE':         'normal',
    'QT_FAST_MA':           5,
    'QT_SLOW_MA':           10,
    'QT_MA_TYPE':           'SMA',
    'QT_TRADE_AMOUNT':      1,
    'QT_MARTINGALE':        2.1,
    'QT_MAX_STEPS':         7,
    'QT_SESSIONS':          10,
    'QT_TAKE_PROFIT_ENABLED': False,
    'QT_TAKE_PROFIT':       100,
    'QT_MIN_PAYOUT':        20,
    'QT_EXPIRY_SECONDS':    30,
    'QT_AUTO_CONTINUE':     False,
}


def _coerce(value, like):
    try:
        if isinstance(like, bool):
            return value.strip().lower() in ('true', '1', 'yes', 'y', 'on')
        if isinstance(like, int):
            return int(float(value))
        if isinstance(like, float):
            return float(value)
        return value
    except Exception:
        return like


def load_settings():
    global URL, CANDLE_PERIOD, BET_AMOUNT, MARTINGALE_MULT, MAX_MARTINGALE_STEPS, \
        MIN_PAYOUT, EXPIRY_SECONDS, VICE_VERSA, \
        STRATEGY, FAST_MA, FAST_MA_TYPE, SLOW_MA, SLOW_MA_TYPE, \
        VORTEX_PERIOD, MARUBOZU_MIN_BODY, CCI_PERIOD, BB_PERIOD, \
        RSI_ENABLED, RSI_PERIOD, RSI_UPPER, RSI_CALL_SIGN, \
        SUPERTREND_ENABLED, SUPERTREND_PERIOD, \
        TAKE_PROFIT_ENABLED, TAKE_PROFIT, STOP_LOSS_ENABLED, STOP_LOSS, \
        SOCKET_DEBUG, \
        SMART_FILTERS_ENABLED, TREND_FILTER_ENABLED, TREND_LOOKBACK, \
        PRICE_ACTION_FILTER, ONE_TRADE_PER_CANDLE, LOSS_COOLDOWN_SECONDS, \
        TRADING_MODE, QT_FAST_MA, QT_SLOW_MA, QT_MA_TYPE, QT_TRADE_AMOUNT, \
        QT_MARTINGALE, QT_MAX_STEPS, QT_SESSIONS, QT_TAKE_PROFIT_ENABLED, \
        QT_TAKE_PROFIT, QT_MIN_PAYOUT, QT_EXPIRY_SECONDS, QT_AUTO_CONTINUE
    values = dict(_DEFAULTS)
    try:
        with open(SETTINGS_PATH, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' not in line:
                    continue
                key, raw = line.split('=', 1)
                key = key.strip()
                if key in values:
                    values[key] = _coerce(raw, values[key])
    except FileNotFoundError:
        print(f'[settings] {SETTINGS_PATH} not found, using defaults.')

    URL                 = values['URL']
    CANDLE_PERIOD       = int(values['CANDLE_PERIOD'])
    BET_AMOUNT          = int(values['BET_AMOUNT'])
    MARTINGALE_MULT     = float(values['MARTINGALE_MULT'])
    MAX_MARTINGALE_STEPS = int(values['MAX_MARTINGALE_STEPS'])
    MIN_PAYOUT          = int(values['MIN_PAYOUT'])
    EXPIRY_SECONDS      = int(values['EXPIRY_SECONDS'])
    VICE_VERSA          = bool(values['VICE_VERSA'])
    STRATEGY            = int(values['STRATEGY'])
    FAST_MA             = int(values['FAST_MA'])
    FAST_MA_TYPE        = str(values['FAST_MA_TYPE'])
    SLOW_MA             = int(values['SLOW_MA'])
    SLOW_MA_TYPE        = str(values['SLOW_MA_TYPE'])
    VORTEX_PERIOD       = int(values['VORTEX_PERIOD'])
    MARUBOZU_MIN_BODY   = int(values['MARUBOZU_MIN_BODY'])
    CCI_PERIOD          = int(values['CCI_PERIOD'])
    BB_PERIOD           = int(values['BB_PERIOD'])
    RSI_ENABLED         = bool(values['RSI_ENABLED'])
    RSI_PERIOD          = int(values['RSI_PERIOD'])
    RSI_UPPER           = int(values['RSI_UPPER'])
    RSI_CALL_SIGN       = str(values['RSI_CALL_SIGN'])
    SUPERTREND_ENABLED  = bool(values['SUPERTREND_ENABLED'])
    SUPERTREND_PERIOD   = int(values['SUPERTREND_PERIOD'])
    TAKE_PROFIT_ENABLED = bool(values['TAKE_PROFIT_ENABLED'])
    TAKE_PROFIT         = float(values['TAKE_PROFIT'])
    STOP_LOSS_ENABLED   = bool(values['STOP_LOSS_ENABLED'])
    STOP_LOSS           = float(values['STOP_LOSS'])
    SOCKET_DEBUG        = bool(values['SOCKET_DEBUG'])
    SMART_FILTERS_ENABLED = bool(values['SMART_FILTERS_ENABLED'])
    TREND_FILTER_ENABLED = bool(values['TREND_FILTER_ENABLED'])
    TREND_LOOKBACK      = int(values['TREND_LOOKBACK'])
    PRICE_ACTION_FILTER = bool(values['PRICE_ACTION_FILTER'])
    ONE_TRADE_PER_CANDLE = bool(values['ONE_TRADE_PER_CANDLE'])
    LOSS_COOLDOWN_SECONDS = int(values['LOSS_COOLDOWN_SECONDS'])
    TRADING_MODE        = str(values['TRADING_MODE'])
    QT_FAST_MA          = int(values['QT_FAST_MA'])
    QT_SLOW_MA          = int(values['QT_SLOW_MA'])
    QT_MA_TYPE          = str(values['QT_MA_TYPE'])
    QT_TRADE_AMOUNT     = int(values['QT_TRADE_AMOUNT'])
    QT_MARTINGALE       = float(values['QT_MARTINGALE'])
    QT_MAX_STEPS        = int(values['QT_MAX_STEPS'])
    QT_SESSIONS         = int(values['QT_SESSIONS'])
    QT_TAKE_PROFIT_ENABLED = bool(values['QT_TAKE_PROFIT_ENABLED'])
    QT_TAKE_PROFIT      = float(values['QT_TAKE_PROFIT'])
    QT_MIN_PAYOUT       = int(values['QT_MIN_PAYOUT'])
    QT_EXPIRY_SECONDS   = int(values['QT_EXPIRY_SECONDS'])
    QT_AUTO_CONTINUE    = bool(values['QT_AUTO_CONTINUE'])


# Call once at import time so constants exist even before main() runs.
load_settings()


# ============================================================
# STATE
# ============================================================
CANDLES          = {}             # asset -> [[ts, o, h, l, c], ...]
TRADING_ALLOWED  = True
INITIAL_DEPOSIT  = None
MARTINGALE_STEP  = 0
LAST_TRADE_AT    = datetime(2000, 1, 1)
NORMAL_LOSS_COOLDOWN_UNTIL = datetime(2000, 1, 1)
NORMAL_TRADED_CANDLE_TS = {}
_FILTER_SKIP_LOG_AT = {}
_LOG_SEEN        = 0
_WS_VERBOSE      = False          # set True to re-enable [ws]/[sniff] diagnostics
_SNIFF_SEEN      = set()
_WS_URLS         = {}             # websocket URL -> frames received
_WS_METHODS      = {}             # CDP method -> count
_SNIFF_OPCODES   = {}

# Quick Trade settings (populated by load_settings)
TRADING_MODE            = 'normal'
QT_FAST_MA              = 5
QT_SLOW_MA              = 10
QT_MA_TYPE              = 'SMA'
QT_TRADE_AMOUNT         = 1
QT_MARTINGALE           = 2.1
QT_MAX_STEPS            = 7
QT_SESSIONS             = 10
QT_TAKE_PROFIT_ENABLED  = False
QT_TAKE_PROFIT          = 100
QT_MIN_PAYOUT           = 20
QT_EXPIRY_SECONDS       = 30
QT_AUTO_CONTINUE        = False

# Quick Trade runtime state
QT_SESSION_COUNT        = 0
QT_SESSION_ACTIVE       = False
QT_DIRECTION            = None
QT_STEP                 = 0
QT_BASE_AMOUNT          = None
QT_LAST_ACTION_ENDS_AT  = datetime(2000, 1, 1)
QT_TRADE_BALANCE_BEFORE = 0.0
QT_TRADE_BET_AMOUNT     = 0.0
QT_AMOUNT_SET           = True
QT_TP_HIT               = False
QT_SESSION_START_BALANCE = None
QT_TOTAL_PROFIT         = 0.0
QT_RUN_FINISHED         = False
QT_PREV_TRADE_ID        = 0
QT_LAST_HEARTBEAT       = datetime(2000, 1, 1)              # how many perf-log entries we've consumed


# ---- Colourful output (display only - never used in any comparison) ----
EMO_BUY      = '🟩💹'
EMO_SELL     = '🟥🔻'
EMO_DRAW     = '🟠♊️'
EMO_LOSS     = '♨️❌'
EMO_WIN      = '💲💱'
EMO_CLOCK    = '⏰'
EMO_PROFIT   = '🤑🤑'
EMO_LOSS_RUN = '😞😞'


def dir_emo(action):
    """Emoji for a trade direction. Accepts call/put/buy/sell in any case."""
    a = str(action or '').strip().lower()
    if a in ('call', 'buy'):
        return EMO_BUY
    if a in ('put', 'sell'):
        return EMO_SELL
    return ''


def outcome_emo(outcome):
    o = str(outcome or '').strip().upper()
    return {'WIN': EMO_WIN, 'LOSS': EMO_LOSS, 'DRAW': EMO_DRAW}.get(o, '')


def total_emo(total):
    """Run-total emoji: 🤑🤑 when positive, 😞😞 at zero or negative."""
    try:
        return EMO_PROFIT if float(total) > 0 else EMO_LOSS_RUN
    except Exception:
        return EMO_LOSS_RUN


def log(*args):
    print(f'{EMO_CLOCK} ' + datetime.now().strftime('[%H:%M:%S]'), *args)


_FIRST_RESULT_LOGGED = False


def parse_trade_result(text, classes=''):
    """Parse a #closedTrades li into WIN / LOSS / DRAW / None.
    Tries class names first (usually cleaner), then the visible text."""
    c = (classes or '').lower()
    if 'draw' in c or 'tie' in c:
        return 'DRAW'
    if 'loss' in c or 'lose' in c:
        return 'LOSS'
    if 'win' in c or 'won' in c:
        return 'WIN'
    t = (text or '').lower()
    if 'draw' in t or 'tie' in t:
        return 'DRAW'
    if 'loss' in t or 'lose' in t:
        return 'LOSS'
    if 'win' in t or 'won' in t:
        return 'WIN'
    return None


def read_latest_closed_trade(driver):
    """Newest entry in #closedTrades as {id, text, classes, result}, or None.
    Uses textContent (not innerText) because the history panel is CSS-hidden
    by default and innerText returns '' for hidden elements."""
    try:
        data = driver.execute_script(
            """
            var ul = document.querySelector('#closedTrades');
            if (!ul) return null;
            var items = ul.querySelectorAll('li[data-id]');
            if (!items.length) return null;
            var maxId = -1, newest = null;
            for (var i = 0; i < items.length; i++) {
                var id = parseInt(items[i].getAttribute('data-id') || '0', 10);
                if (id > maxId) { maxId = id; newest = items[i]; }
            }
            if (!newest) return null;
            return {
                id: maxId,
                text: (newest.textContent || '').trim(),
                classes: (newest.className || '').toString(),
                opentime: newest.getAttribute('data-opentime') || ''
            };
            """
        )
    except Exception:
        return None
    if not data:
        return None
    text = data.get('text', '')
    # Extract "Amount $ X.XX" and "Payback $ Y.YY" from the entry text.
    amount = None
    payback = None
    m = re.search(r'Amount\s*\$\s*([\d,]+(?:\.\d+)?)', text, re.IGNORECASE)
    if m:
        try:
            amount = float(m.group(1).replace(',', ''))
        except Exception:
            amount = None
    m = re.search(r'Payback\s*\$\s*([\d,]+(?:\.\d+)?)', text, re.IGNORECASE)
    if m:
        try:
            payback = float(m.group(1).replace(',', ''))
        except Exception:
            payback = None
    return {
        'id': data.get('id', 0),
        'text': text,
        'classes': data.get('classes', ''),
        'result': parse_trade_result(text, data.get('classes', '')),
        'amount': amount,
        'payback': payback,
    }


async def wait_for_trade_result(driver, prev_max_id, timeout=8.0, poll=0.4):
    """Poll #closedTrades for a new entry with data-id > prev_max_id.
    Returns the parsed dict, or None if nothing new shows up in time."""
    waited = 0.0
    while waited < timeout:
        latest = read_latest_closed_trade(driver)
        if latest and latest['id'] > prev_max_id:
            return latest
        await asyncio.sleep(poll)
        waited += poll
    return None


def parse_expiry(text):
    """Parse '30s', '5m', '1h', '1mo' etc. into seconds. None if unrecognized."""
    text = (text or '').strip().lower().replace(' ', '')
    if not text:
        return None
    m = re.match(r'^(\d+)(mo|s|m|h|d|w)$', text)
    if not m:
        return None
    n = int(m.group(1))
    u = m.group(2)
    if u == 'mo': return n * 30 * 86400
    if u == 's':  return n
    if u == 'm':  return n * 60
    if u == 'h':  return n * 3600
    if u == 'd':  return n * 86400
    if u == 'w':  return n * 7 * 86400
    return None


# ============================================================
# STRATEGY FUNCTIONS  (shared logic with pocketoption_bot.py - keep in sync)
# ============================================================
def candles_to_quotes(candles, estimate_ohlc=False):
    base_date = datetime(2000, 1, 1)
    quotes = []
    for i, c in enumerate(candles):
        close = c[2]
        open_ = c[1] if isinstance(c[1], (int, float)) else close
        high = c[3] if len(c) > 3 and isinstance(c[3], (int, float)) else None
        low = c[4] if len(c) > 4 and isinstance(c[4], (int, float)) else None
        if high is None or low is None:
            if estimate_ohlc:
                prev_close = candles[i - 1][2] if i > 0 else close
                next_close = candles[i + 1][2] if i < len(candles) - 1 else close
                high = max(close, prev_close, next_close)
                low = min(close, prev_close, next_close)
            else:
                high = close
                low = close
        quotes.append(Quote(base_date + timedelta(minutes=i), open_, high, low, close))
    return quotes


def get_ma_last_two(quotes, ma_type, period):
    if ma_type == 'EMA':
        results = indicators.get_ema(quotes, period)
        values = [r.ema for r in results if r.ema is not None]
    elif ma_type == 'WMA':
        results = indicators.get_wma(quotes, period)
        values = [r.wma for r in results if r.wma is not None]
    else:
        results = indicators.get_sma(quotes, period)
        values = [r.sma for r in results if r.sma is not None]
    if len(values) < 2:
        raise ValueError('Not enough data points to calculate MA.')
    return values[-2], values[-1]


async def moving_averages_cross(candles):
    if FAST_MA >= SLOW_MA:
        return None
    try:
        quotes = candles_to_quotes(candles)
        fast_prev, fast_curr = get_ma_last_two(quotes, FAST_MA_TYPE, FAST_MA)
        slow_prev, slow_curr = get_ma_last_two(quotes, SLOW_MA_TYPE, SLOW_MA)
        if fast_prev < slow_prev and fast_curr > slow_curr:
            return 'call'
        if fast_prev > slow_prev and fast_curr < slow_curr:
            return 'put'
    except Exception as e:
        log('MA error:', e)
    return None


def get_rsi_lower(rsi_upper):
    return 100 - rsi_upper


def get_rsi_put_sign(call_sign):
    return '<' if call_sign == '>' else '>'


async def rsi_strategy(candles, action):
    try:
        quotes = candles_to_quotes(candles)
        results = indicators.get_rsi(quotes, RSI_PERIOD)
        values = [r.rsi for r in results if r.rsi is not None]
        if not values:
            return None
        rsi_lower = get_rsi_lower(RSI_UPPER)
        put_sign = get_rsi_put_sign(RSI_CALL_SIGN)
        if action == 'call':
            if (RSI_CALL_SIGN == '>' and values[-1] > RSI_UPPER) or \
               (RSI_CALL_SIGN == '<' and values[-1] < RSI_UPPER):
                return 'call'
        elif action == 'put':
            if (put_sign == '>' and values[-1] > rsi_lower) or \
               (put_sign == '<' and values[-1] < rsi_lower):
                return 'put'
    except Exception:
        pass
    return None


async def supertrend_strategy(candles, action):
    try:
        quotes = candles_to_quotes(candles)
        results = indicators.get_super_trend(quotes, SUPERTREND_PERIOD)
        last = next((r for r in reversed(results)
                     if r.upper_band is not None or r.lower_band is not None), None)
        if last is None:
            return None
        if action == 'call' and last.lower_band is not None:
            return 'call'
        if action == 'put' and last.upper_band is not None:
            return 'put'
    except Exception:
        pass
    return None


async def psar_strategy(candles):
    try:
        quotes = candles_to_quotes(candles)
        results = indicators.get_parabolic_sar(quotes)
        last = results[-1] if results else None
        if last is None or not last.is_reversal:
            return None
        close = candles[-1][2]
        if last.sar < close:
            return 'call'
        if last.sar > close:
            return 'put'
    except Exception:
        pass
    return None


async def vortex_strategy(candles):
    try:
        quotes = candles_to_quotes(candles, estimate_ohlc=True)
        results = indicators.get_vortex(quotes, VORTEX_PERIOD)
        valid = [r for r in results if r.pvi is not None and r.nvi is not None]
        if len(valid) < 2:
            return None
        prev, curr = valid[-2], valid[-1]
        if prev.pvi <= prev.nvi and curr.pvi > curr.nvi:
            return 'call'
        if prev.pvi >= prev.nvi and curr.pvi < curr.nvi:
            return 'put'
    except Exception:
        pass
    return None


async def marubozu_strategy(candles):
    try:
        quotes = candles_to_quotes(candles, estimate_ohlc=True)
        results = indicators.get_marubozu(quotes, min_body_percent=MARUBOZU_MIN_BODY)
        if results[-1].match.value > 0:
            return 'call'
        if results[-1].match.value < 0:
            return 'put'
    except Exception:
        pass
    return None


async def cci_strategy(candles):
    try:
        quotes = candles_to_quotes(candles, estimate_ohlc=True)
        results = indicators.get_cci(quotes, lookback_periods=CCI_PERIOD)
        valid = [r for r in results if r.cci is not None]
        if len(valid) < 2:
            return None
        prev, curr = valid[-2], valid[-1]
        if prev.cci <= 100 and curr.cci > 100:
            return 'call'
        if prev.cci >= -100 and curr.cci < -100:
            return 'put'
    except Exception:
        pass
    return None


async def bollinger_bands_strategy(candles):
    try:
        quotes = candles_to_quotes(candles, estimate_ohlc=True)
        results = indicators.get_bollinger_bands(quotes, lookback_periods=BB_PERIOD)
        valid = [r for r in results if r.percent_b is not None]
        if len(valid) < 2:
            return None
        prev, curr = valid[-2], valid[-1]
        if prev.percent_b >= 0 and curr.percent_b < 0:
            return 'call'
        if prev.percent_b <= 1 and curr.percent_b > 1:
            return 'put'
    except Exception:
        pass
    return None


async def get_price_action(candles, action):
    if len(candles) < 3:
        return None
    if action == 'call':
        if candles[-1][2] > candles[-3][2]:
            return action
    elif action == 'put':
        if candles[-1][2] < candles[-3][2]:
            return action
    return None


def trend_agrees(candles, action, lookback=3):
    need = lookback + 1
    if len(candles) < need:
        return False
    closes = [c[2] for c in candles[-need:]]
    if action == 'call':
        return all(closes[i] < closes[i + 1] for i in range(lookback))
    if action == 'put':
        return all(closes[i] > closes[i + 1] for i in range(lookback))
    return False


def _log_filter_skip(asset, reason):
    key = f'{asset}:{reason}'
    now = datetime.now()
    last = _FILTER_SKIP_LOG_AT.get(key)
    if last and now - last < timedelta(seconds=30):
        return
    _FILTER_SKIP_LOG_AT[key] = now
    log(f'Smart filter skip {asset or "?"}: {reason}')


async def apply_normal_smart_filters(candles, action, asset=None):
    if not SMART_FILTERS_ENABLED:
        return action
    if not action:
        return None
    if TREND_FILTER_ENABLED:
        lookback = max(2, int(TREND_LOOKBACK))
        if not trend_agrees(candles, action, lookback):
            _log_filter_skip(asset, f'trend (need {lookback} agreeing closes)')
            return None
    if PRICE_ACTION_FILTER:
        if not await get_price_action(candles, action):
            _log_filter_skip(asset, 'price-action confluence')
            return None
    return action


def note_normal_trade_outcome(outcome):
    global NORMAL_LOSS_COOLDOWN_UNTIL
    if not SMART_FILTERS_ENABLED:
        return
    if outcome != 'LOSS':
        return
    secs = max(0, int(LOSS_COOLDOWN_SECONDS))
    if secs <= 0:
        return
    NORMAL_LOSS_COOLDOWN_UNTIL = datetime.now() + timedelta(seconds=secs)
    log(f'Smart filter: loss cooldown {secs}s before next Normal trade')


async def check_strategies(candles):
    if STRATEGY == 6:
        action = await bollinger_bands_strategy(candles)
    elif STRATEGY == 5:
        action = await cci_strategy(candles)
    elif STRATEGY == 4:
        action = await marubozu_strategy(candles)
    elif STRATEGY == 3:
        action = await vortex_strategy(candles)
    elif STRATEGY == 2:
        action = await psar_strategy(candles)
    else:
        action = await moving_averages_cross(candles)
    if not action:
        return None
    if RSI_ENABLED:
        action = await rsi_strategy(candles, action)
        if not action:
            return None
    if SUPERTREND_ENABLED:
        action = await supertrend_strategy(candles, action)
        if not action:
            return None
    return action


def min_candles_needed():
    need = SLOW_MA + 2
    if STRATEGY == 3:   need = max(need, VORTEX_PERIOD + 2)
    if STRATEGY == 5:   need = max(need, CCI_PERIOD + 2)
    if STRATEGY == 6:   need = max(need, BB_PERIOD + 2)
    if STRATEGY == 2:   need = max(need, 22)
    if RSI_ENABLED:         need = max(need, RSI_PERIOD + 2)
    if SUPERTREND_ENABLED:  need = max(need, SUPERTREND_PERIOD + 2)
    if SMART_FILTERS_ENABLED and TREND_FILTER_ENABLED:
        need = max(need, int(TREND_LOOKBACK) + 2)
    if SMART_FILTERS_ENABLED and PRICE_ACTION_FILTER:
        need = max(need, 3)
    return need


# ============================================================
# DRIVER
# ============================================================
def _profile_path():
    username = os.environ.get('USER', os.environ.get('USERNAME'))
    os_platform = platform.platform().lower()
    if 'windows' in os_platform:
        return fr'C:\Users\{username}\AppData\Local\Google\Chrome\CloseOption Profile'
    if 'macos' in os_platform:
        return fr'/Users/{username}/Library/Application Support/Google/Chrome/CloseOption Profile'
    return '~/.config/google-chrome/CloseOption Profile'


def _kill_stale_chrome(profile_path):
    """SIGKILL any process still holding our Chrome profile."""
    try:
        expanded = os.path.expanduser(profile_path)
        out = subprocess.run(['pgrep', '-f', expanded],
                             capture_output=True, text=True, timeout=3)
        pids = [p.strip() for p in out.stdout.split('\n') if p.strip()]
        if not pids:
            return 0
        for pid in pids:
            try:
                os.kill(int(pid), signal.SIGKILL)
            except Exception:
                pass
        log(f'Killed {len(pids)} stale Chrome process(es) holding the profile.')
        return len(pids)
    except FileNotFoundError:
        return 0
    except Exception as e:
        log(f'Stale-chrome cleanup: {e}')
        return 0


def _clean_profile_locks(profile_path):
    """Remove Chrome Singleton* lock files left over from a crashed run."""
    expanded = os.path.expanduser(profile_path)
    if not os.path.isdir(expanded):
        return
    for name in ('SingletonLock', 'SingletonSocket', 'SingletonCookie', 'lockfile'):
        p = os.path.join(expanded, name)
        try:
            if os.path.islink(p) or os.path.isfile(p):
                os.remove(p)
        except Exception:
            pass


async def _launch_chrome(options, user_driver, timeout=90):
    """Run uc.Chrome in a worker thread with a hard timeout."""
    def _sync():
        if user_driver and os.path.exists(user_driver):
            return uc.Chrome(options=options, version_main=153,
                             browser_executable_path='/usr/bin/google-chrome',
                             driver_executable_path=user_driver)
        return uc.Chrome(options=options, version_main=153,
                         browser_executable_path='/usr/bin/google-chrome')
    try:
        return await asyncio.wait_for(asyncio.to_thread(_sync), timeout=timeout)
    except asyncio.TimeoutError:
        log(f'Chrome launch timed out after {timeout}s. Killing stragglers.')
        _kill_stale_chrome(_profile_path())
        raise


async def get_driver():
    profile = _profile_path()

    # Pre-flight: kill zombies and clear locks from any prior crashed run.
    _kill_stale_chrome(profile)
    await asyncio.sleep(0.5)
    _clean_profile_locks(profile)

    options = uc.ChromeOptions()
    options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
    options.set_capability('pageLoadStrategy', 'none')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--no-first-run')
    options.add_argument('--no-default-browser-check')
    options.add_argument('--disable-features=Translate,BackForwardCache')
    options.add_argument('--disable-background-networking')
    options.add_argument('--disable-sync')
    options.add_argument(fr'--user-data-dir={os.path.expanduser(profile)}')

    user_driver = os.path.expanduser('~/.local/share/undetected_chromedriver/chromedriver')

    for attempt in (1, 2):
        try:
            driver = await _launch_chrome(options, user_driver, timeout=90)
            try:
                driver.set_page_load_timeout(30)
                driver.set_script_timeout(20)
            except Exception:
                pass
            return driver
        except Exception as e:
            log(f'Chrome launch attempt {attempt} failed: {e}')
            _kill_stale_chrome(profile)
            _clean_profile_locks(profile)
            await asyncio.sleep(2)
    raise RuntimeError('Could not launch Chrome after 2 attempts. '
                       'Check for zombie processes or a corrupted profile.')


# ============================================================
# DOM LAYER  (all selectors verified against recon dump)
# ============================================================
async def get_balance(driver):
    """Reads the Demo/Real balance from .Balance .BBB. Returns float or None."""
    try:
        text = driver.execute_script(
            "var e=document.querySelector('.Balance .BBB'); return e ? e.innerText : null;")
        if not text:
            return None
        m = re.search(r'([\d,]+\.?\d*)', text.replace(' ', ''))
        if m:
            return float(m.group(1).replace(',', ''))
    except Exception:
        pass
    return None


async def read_selected_pair(driver):
    """The asset currently shown on the chart, e.g. 'EUR/USD:AFX'."""
    try:
        return driver.execute_script(
            "var e=document.querySelector('input[name=\"selectedPair\"]'); return e ? e.value : null;")
    except Exception:
        return None


async def read_payout(driver):
    """Current payout % shown next to the Profit box. Returns int or None."""
    try:
        text = driver.find_element(By.CSS_SELECTOR, '.profitBx .Right .Text').text
        return int(re.sub(r'\D', '', text) or 0)
    except Exception:
        return None


async def read_ui_expiry(driver):
    """Parse the expiry shown in the UI's hidden input.curTime field.
    Returns seconds, or None if unreadable."""
    try:
        text = driver.execute_script(
            "var e=document.querySelector('input.curTime'); return e ? e.value : null;")
        if not text:
            return None
        m = re.match(r'^(\d+)\s*(\w+)', text.strip().lower())
        if not m:
            return None
        n = int(m.group(1))
        unit = m.group(2)
        if unit.startswith('sec'):   return n
        if unit.startswith('min'):   return n * 60
        if unit.startswith('hour'):  return n * 3600
        if unit.startswith('day'):   return n * 86400
        if unit.startswith('week'):  return n * 7 * 86400
        if unit.startswith('month'): return n * 30 * 86400
    except Exception:
        pass
    return None


async def set_amount(driver, amount):
    """Write the bet amount into .tradeSize input.Text and verify it landed."""
    try:
        js = f"""
        var input = document.querySelector('.tradeSize input.Text');
        if (!input) return false;
        var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        setter.call(input, '{amount}');
        input.dispatchEvent(new Event('input', {{bubbles: true}}));
        input.dispatchEvent(new Event('change', {{bubbles: true}}));
        return true;
        """
        ok = driver.execute_script(js)
        if not ok:
            return False
        await asyncio.sleep(0.3)
        current = driver.execute_script(
            "var i=document.querySelector('.tradeSize input.Text'); return i ? i.value : null;")
        try:
            return abs(float(current) - float(amount)) < 0.01
        except Exception:
            return False
    except Exception as e:
        log('set_amount failed:', e)
        return False


async def place_order(driver, direction):
    """direction is 'call' (Buy button) or 'put' (Sell button)."""
    cls = 'Buy' if direction == 'call' else 'Sell'
    try:
        btn = driver.find_element(By.CSS_SELECTOR, f'#mainBtns button.{cls}')
        btn.click()
        return True
    except Exception as e:
        log(f'place_order ({direction}) failed:', e)
        return False


async def switch_to_asset(driver, asset_name):
    """Click the asset label whose data-name matches. asset_name like 'EUR/USD:AFX'."""
    try:
        js = f"""
        var labels = document.querySelectorAll('label.assest');
        for (var i = 0; i < labels.length; i++) {{
            var nameEl = labels[i].querySelector('[data-name]');
            if (nameEl && nameEl.getAttribute('data-name') === {json.dumps(asset_name)}) {{
                labels[i].click();
                return true;
            }}
        }}
        return false;
        """
        return bool(driver.execute_script(js))
    except Exception:
        return False


# ============================================================
# SOCKET.IO  ->  CANDLES
# ============================================================
def _update_candle(asset, price):
    """Called for every tick. Builds a fixed-period candle for `asset`."""
    now = time.time()
    ts = int(now // CANDLE_PERIOD) * CANDLE_PERIOD
    candles = CANDLES.setdefault(asset, [])
    if not candles or candles[-1][0] != ts:
        candles.append([ts, price, price, price, price])
        if len(candles) > 500:
            candles.pop(0)
    else:
        c = candles[-1]
        c[2] = price
        if price > c[3]: c[3] = price
        if price < c[4]: c[4] = price


async def poll_socket(driver):
    """Drain Chrome perf logs, find  42["priceData", {...}]  frames, update candles."""
    global _LOG_SEEN, _SNIFF_SEEN, _SNIFF_OPCODES, _WS_URLS, _WS_METHODS
    try:
        entries = driver.get_log('performance')
    except Exception:
        return
    # Only process entries newer than the last batch we've seen.
    new_entries = entries[_LOG_SEEN:]
    _LOG_SEEN = len(entries)
    for e in new_entries:
        try:
            msg = json.loads(e['message'])['message']
        except Exception:
            continue
        method = msg.get('method', '')
        _WS_METHODS[method] = _WS_METHODS.get(method, 0) + 1

        if method == 'Network.webSocketCreated':
            url = msg.get('params', {}).get('url', '')
            if url not in _WS_URLS:
                _WS_URLS[url] = 0
                if _WS_VERBOSE:
                    log(f'[ws] created: {url}')
            continue

        if method == 'Network.webSocketFrameError':
            err = msg.get('params', {}).get('errorMessage', '?')
            if _WS_VERBOSE:
                log(f'[ws] frame error: {err}')
            continue

        if method != 'Network.webSocketFrameReceived':
            continue

        resp = msg.get('params', {}).get('response', {})
        opcode = resp.get('opcode', 0)
        _SNIFF_OPCODES[opcode] = _SNIFF_OPCODES.get(opcode, 0) + 1

        request_id = msg.get('params', {}).get('requestId', '?')
        _WS_URLS[request_id] = _WS_URLS.get(request_id, 0) + 1

        if opcode == 2:
            raw = resp.get('payloadData', '') or ''
            try:
                preview = base64.b64decode(raw)[:80].decode('utf-8', errors='replace')
            except Exception:
                preview = '<binary undecodable>'
            key = f'op2:{preview[:30]}'
        else:
            preview = resp.get('payloadData', '')[:120]
            key = f'op{opcode}:{preview[:30]}'
        if key not in _SNIFF_SEEN and len(_SNIFF_SEEN) < 20:
            _SNIFF_SEEN.add(key)
            if _WS_VERBOSE:
                log(f'[sniff] {key[:50]} | {preview!r}')

        if opcode != 1:
            continue
        text = resp.get('payloadData', '')
        if not text.startswith('42'):
            continue
        try:
            payload = json.loads(text[2:])
        except Exception:
            continue
        if not isinstance(payload, list) or len(payload) < 2:
            continue
        event, data = payload[0], payload[1]
        if event != 'priceData':
            if SOCKET_DEBUG:
                log('socket event:', event, '->', str(data)[:200])
            continue
        prices = data.get('price') if isinstance(data, dict) else None
        if not prices:
            continue
        for asset, q in prices.items():
            mp = q.get('mainPrice') if isinstance(q, dict) else None
            if mp is None:
                continue
            _update_candle(asset, float(mp))


# ============================================================
# TRADING LOGIC
# ============================================================
async def check_deposit(driver):
    global INITIAL_DEPOSIT, TRADING_ALLOWED
    bal = await get_balance(driver)
    # A real account never reads exactly 0 mid-session. 0 here means the page
    # rendered .Balance .BBB but the value hasn't arrived from the socket yet.
    if bal is None or bal <= 0:
        return
    if INITIAL_DEPOSIT is None:
        INITIAL_DEPOSIT = bal
        log(f'Initial deposit: {INITIAL_DEPOSIT:.2f}')
        return


async def wait_and_settle(driver, expiry_seconds):
    """Sleep the FULL expiry + settlement buffer, then read balance once.

    CloseOption deducts the stake from displayed balance the instant the order
    is placed. A 'poll until balance changes' loop therefore returns immediately,
    right after the stake is removed, and every trade - win or lose - gets
    scored as LOSS. We must let the trade actually expire before reading.

    Keeps draining socket logs during the wait so other assets' candles keep
    building while this trade is open.
    """
    end = time.time() + expiry_seconds + 2.0
    while time.time() < end:
        await poll_socket(driver)
        await asyncio.sleep(0.5)
    return await get_balance(driver)


async def score_result(before, after, bet):
    """WIN / LOSS / DRAW from balance delta, same approach as the PO bot."""
    delta = after - before
    tolerance = max(bet * 0.02, 0.02)
    if abs(delta + bet) <= tolerance:
        return 'LOSS', delta
    if delta > tolerance:
        return 'WIN', delta
    return 'DRAW', delta


async def try_trade(driver):
    """Look for a signal on the selected pair and place one trade."""
    global MARTINGALE_STEP, LAST_TRADE_AT, NORMAL_TRADED_CANDLE_TS

    # Cooldown so we don't fire two trades within one expiry.
    if datetime.now() < LAST_TRADE_AT + timedelta(seconds=EXPIRY_SECONDS + 2):
        return
    if SMART_FILTERS_ENABLED and datetime.now() < NORMAL_LOSS_COOLDOWN_UNTIL:
        return

    asset = await read_selected_pair(driver)
    if not asset:
        return
    candles = CANDLES.get(asset)
    if not candles or len(candles) < min_candles_needed():
        return  # still warming up

    # Only use candles that are fully closed - the last one is still forming.
    closed = candles[:-1]
    if len(closed) < min_candles_needed():
        return
    if SMART_FILTERS_ENABLED:
        lookback = max(2, int(TREND_LOOKBACK))
        if len(closed) < lookback + 1:
            return
    current_ts = closed[-1][0] if closed else None
    if (SMART_FILTERS_ENABLED and ONE_TRADE_PER_CANDLE
            and current_ts and NORMAL_TRADED_CANDLE_TS.get(asset) == current_ts):
        return
    action = await check_strategies(closed)
    if not action:
        return
    action = await apply_normal_smart_filters(closed, action, asset=asset)
    if not action:
        return
    if VICE_VERSA:
        action = 'call' if action == 'put' else 'put'

    payout = await read_payout(driver)
    if payout is None or payout < MIN_PAYOUT:
        log(f'Skipping {asset}: payout {payout}% < {MIN_PAYOUT}%')
        return

    # Whole-dollar martingale: 1, 3, 9, 27, ...
    amount = int(BET_AMOUNT * (MARTINGALE_MULT ** MARTINGALE_STEP))
    if amount < 1:
        amount = 1

    # Refuse to fire a stake the account can't cover.
    if not await _check_affordable(driver, amount):
        return

    if not await set_amount(driver, amount):
        log('Could not set amount, skipping trade.')
        return

    # Which expiry will really fire: UI first, fall back to configured value.
    ui_expiry = await read_ui_expiry(driver)
    if ui_expiry:
        expiry = ui_expiry
        if ui_expiry != EXPIRY_SECONDS:
            log(f'NOTE: UI expiry ({ui_expiry}s) != configured ({EXPIRY_SECONDS}s); using UI value.')
    else:
        expiry = EXPIRY_SECONDS

    # Snapshot the newest id in #closedTrades before we place the order,
    # so we can detect the new entry once this trade settles.
    latest_before = read_latest_closed_trade(driver)
    prev_max_id = latest_before['id'] if latest_before else 0

    bal_before = await get_balance(driver)
    if bal_before is None:
        log('Could not read balance, skipping trade.')
        return

    log(f'{dir_emo(action)} → {action.upper()} {asset} | stake ${amount} | step {MARTINGALE_STEP} | '
        f'payout {payout}% | expiry {expiry}s')
    if not await place_order(driver, action):
        return
    LAST_TRADE_AT = datetime.now()
    if current_ts:
        NORMAL_TRADED_CANDLE_TS[asset] = current_ts

    # Sleep the full expiry (+ small buffer); keeps draining socket logs
    # meanwhile so other assets' candles keep building.
    bal_after = await wait_and_settle(driver, expiry)

    # Read the real result from CloseOption's own trade history panel.
    latest = await wait_for_trade_result(driver, prev_max_id)
    if latest and latest['result']:
        outcome = latest['result']
        delta = (bal_after - bal_before) if (bal_after is not None) else 0.0
        # Prefer the DOM's own Amount/Payback numbers over balance delta.
        if latest.get('amount') is not None and latest.get('payback') is not None:
            delta = latest['payback'] - latest['amount']
        if not _FIRST_RESULT_LOGGED:
            log(f'[dom] first parsed entry: id={latest["id"]} classes={latest["classes"]!r} '
                f'text={latest["text"][:120]!r}')
            globals()['_FIRST_RESULT_LOGGED'] = True
        log(f'← {outcome_emo(outcome)} {outcome} | delta {delta:+.2f}')
        note_normal_trade_outcome(outcome)
        if INITIAL_DEPOSIT and bal_after:
            pnl = bal_after - INITIAL_DEPOSIT
            log(f'  Balance: {bal_after:.2f} | Run P/L: {pnl:+.2f} {total_emo(pnl)}')
    else:
        # Fallback: balance-delta scoring. Less reliable (stake removal reads
        # as a loss if settlement lags), so only used when the DOM read fails.
        if bal_after is None:
            log('Could not read balance after trade and no DOM entry found; skipping scoring.')
            return
        outcome, delta = await score_result(bal_before, bal_after, amount)
        log(f'← {outcome_emo(outcome)} {outcome} (balance fallback) | delta {delta:+.2f}')
        note_normal_trade_outcome(outcome)

    if outcome == 'WIN':
        MARTINGALE_STEP = 0
    elif outcome == 'LOSS':
        MARTINGALE_STEP += 1
        if MARTINGALE_STEP >= MAX_MARTINGALE_STEPS:
            log(f'Max martingale steps reached ({MAX_MARTINGALE_STEPS}); resetting.')
            MARTINGALE_STEP = 0
    # DRAW -> keep step the same


# ============================================================
# QUICK TRADE MODE
# ============================================================
def _save_setting(key, value):
    """Rewrite one key in closeoption_settings.txt without touching the others."""
    try:
        lines = []
        found = False
        try:
            with open(SETTINGS_PATH) as f:
                for line in f:
                    if '=' in line and line.split('=', 1)[0].strip() == key:
                        lines.append(f'{key}={value}\n')
                        found = True
                    else:
                        lines.append(line)
        except FileNotFoundError:
            pass
        if not found:
            lines.append(f'{key}={value}\n')
        with open(SETTINGS_PATH, 'w') as f:
            f.writelines(lines)
    except Exception as e:
        log(f'Could not save {key}: {e}')


async def driver_alive(driver):
    try:
        await asyncio.wait_for(asyncio.to_thread(lambda: driver.current_url), timeout=8)
        return True
    except asyncio.TimeoutError:
        log('Chrome health check timed out - session is unresponsive.')
        return False
    except Exception as e:
        log(f'Chrome session appears to be dead: {e}')
        return False


def countdown_with_terminate(seconds, terminate_key='t'):
    """Live countdown. If stdin is dead (EOF, DEVNULL, closed pipe) we must
    still tick once per second - otherwise select() returns immediately on
    every iteration and the countdown blasts through 30 seconds in a flash."""
    import select
    stdin_dead = False
    for remaining in range(seconds, 0, -1):
        print(f'\r{EMO_CLOCK} Auto-continuing in {remaining:2d}s... press T to terminate: ', end='', flush=True)
        if stdin_dead:
            time.sleep(1)
            continue
        try:
            ready, _, _ = select.select([sys.stdin], [], [], 1.0)
            if not ready:
                continue
            line = sys.stdin.readline()
            if line == '':
                # EOF. Pipe closed. Stop trying to read from it - otherwise
                # every iteration returns instantly and the countdown is fake.
                stdin_dead = True
                continue
            if line.strip().lower() == terminate_key:
                print()
                return True
        except Exception:
            stdin_dead = True
            try:
                time.sleep(1)
            except Exception:
                pass
    print()
    return False


def qt_check_take_profit(balance_now=None):
    global QT_TP_HIT
    if not QT_TAKE_PROFIT_ENABLED:
        return
    if INITIAL_DEPOSIT is None:
        return
    try:
        tp = float(QT_TAKE_PROFIT)
    except Exception:
        return
    if balance_now is None or balance_now <= 0:
        return
    if balance_now > INITIAL_DEPOSIT + tp:
        log(f'Quick Trade: take profit reached. Initial: {INITIAL_DEPOSIT}, current: {balance_now} ({balance_now - INITIAL_DEPOSIT:+.2f})')
        QT_TP_HIT = True


async def has_open_trade(driver):
    """True if any trade is still open in the DOM. Prevents the bot from firing
    a second position while the previous one hasn't settled yet - the bot's own
    timer can drift short of the real expiry, especially on short expiries."""
    try:
        return bool(driver.execute_script(
            "var ul = document.querySelector('#currentTrades');"
            "return ul ? ul.querySelectorAll('li').length > 0 : false;"))
    except Exception:
        return False


async def _check_affordable(driver, stake):
    """Return True if `stake` can be covered by the current balance.
    If not, log the shortfall and flag the bot to stop. Unreadable balance
    is treated as 'keep going' - we don't want a bad read to kill a run."""
    global TRADING_ALLOWED, STOP_REASON
    bal = await get_balance(driver)
    if bal is None or bal <= 0:
        return True
    if stake > bal:
        log(f'INSUFFICIENT BALANCE: next stake ${stake} exceeds balance ${bal:.2f}. Stopping.')
        STOP_REASON = 'insufficient balance'
        TRADING_ALLOWED = False
        return False
    return True


async def quick_trade_ma_direction(candles):
    """Current fast-vs-slow MA position (not a cross event) -> call/put.
    Used once per Quick Trade session."""
    if QT_FAST_MA >= QT_SLOW_MA:
        log('Quick Trade MA: fast period must be less than slow period')
        return None
    try:
        quotes = candles_to_quotes(candles)
        _, fast_curr = get_ma_last_two(quotes, QT_MA_TYPE, QT_FAST_MA)
        _, slow_curr = get_ma_last_two(quotes, QT_MA_TYPE, QT_SLOW_MA)
        if fast_curr is None or slow_curr is None:
            return None
        if fast_curr > slow_curr:
            return 'call'
        elif fast_curr < slow_curr:
            return 'put'
    except Exception:
        # Warmup boundary: slow MA doesn't have 2 values yet. Silent - the
        # [QT] heartbeat already tells the user it's warming up.
        pass
    return None


def _heartbeat(msg):
    global QT_LAST_HEARTBEAT
    now = datetime.now()
    if (now - QT_LAST_HEARTBEAT).total_seconds() < 10:
        return
    QT_LAST_HEARTBEAT = now
    log(f'[QT] {msg}')


async def check_quick_trade(driver):
    global QT_SESSION_COUNT, QT_SESSION_ACTIVE, QT_DIRECTION, QT_STEP, QT_BASE_AMOUNT, \
        QT_LAST_ACTION_ENDS_AT, QT_TRADE_BALANCE_BEFORE, QT_TRADE_BET_AMOUNT, QT_AMOUNT_SET, \
        QT_TP_HIT, QT_SESSION_START_BALANCE, QT_TOTAL_PROFIT, QT_RUN_FINISHED, QT_PREV_TRADE_ID, \
        QT_LAST_HEARTBEAT

    if QT_AUTO_CONTINUE:
        total_sessions = 5
    else:
        total_sessions = int(QT_SESSIONS)
        if total_sessions < 10:
            total_sessions = 10
    tp_enabled = bool(QT_TAKE_PROFIT_ENABLED)

    if QT_RUN_FINISHED:
        return

    if QT_SESSION_COUNT >= total_sessions:
        log(f'Quick Trade: target of {total_sessions} sessions reached. Total profit: {QT_TOTAL_PROFIT:+.2f} {total_emo(QT_TOTAL_PROFIT)}')
        QT_RUN_FINISHED = True
        return

    if QT_TP_HIT:
        log(f'Quick Trade: stopping on take profit after {QT_SESSION_COUNT} session(s). Total profit: {QT_TOTAL_PROFIT:+.2f} {total_emo(QT_TOTAL_PROFIT)}')
        QT_RUN_FINISHED = True
        return

    if QT_BASE_AMOUNT is None:
        QT_BASE_AMOUNT = float(QT_TRADE_AMOUNT)

    if QT_LAST_ACTION_ENDS_AT > datetime.now():
        remaining = int((QT_LAST_ACTION_ENDS_AT - datetime.now()).total_seconds())
        _heartbeat(f'trade open, {remaining}s to expiry')
        return

    # ---- Score previous trade if pending ----
    if not QT_AMOUNT_SET:
        bal_after = await get_balance(driver)
        if bal_after is None or bal_after <= 0 or QT_TRADE_BALANCE_BEFORE <= 0 or QT_TRADE_BET_AMOUNT <= 0:
            log('Quick Trade: missing/invalid balance reading, will retry next tick.')
            return

        delta = bal_after - QT_TRADE_BALANCE_BEFORE

        # Prefer DOM history entry (matches actual outcome), fall back to delta.
        latest = await wait_for_trade_result(driver, QT_PREV_TRADE_ID, timeout=2.0, poll=0.3)
        dom_outcome = latest['result'] if (latest and latest['result']) else None

        if dom_outcome:
            outcome = dom_outcome
            # Prefer DOM-sourced amount/payback for the real P/L: the demo
            # balance sometimes moves for unrelated reasons (bonus credit,
            # top-up, read race) and would give a bogus delta otherwise.
            if latest and latest.get('amount') is not None and latest.get('payback') is not None:
                delta = latest['payback'] - latest['amount']
        else:
            expected_loss = -QT_TRADE_BET_AMOUNT
            tolerance = max(QT_TRADE_BET_AMOUNT * 0.1, 0.02)
            if abs(delta - expected_loss) <= tolerance:
                outcome = 'LOSS'
            elif delta > tolerance:
                outcome = 'WIN'
            else:
                outcome = 'DRAW'

        log(f'Quick Trade result: {outcome_emo(outcome)} {outcome} (delta {delta:+.2f}, step {QT_STEP})')
        if INITIAL_DEPOSIT:
            pnl = bal_after - INITIAL_DEPOSIT
            log(f'  Balance: {bal_after:.2f} | Run P/L: {pnl:+.2f} {total_emo(pnl)}')

        if outcome == 'WIN':
            session_profit = (bal_after - QT_SESSION_START_BALANCE) if QT_SESSION_START_BALANCE is not None else delta
            QT_TOTAL_PROFIT += session_profit
            QT_SESSION_COUNT += 1
            log(f'Quick Trade: session {QT_SESSION_COUNT}/{total_sessions} closed on {EMO_WIN} WIN. '
                f'Session profit: {session_profit:+.2f} | Total: {QT_TOTAL_PROFIT:+.2f} {total_emo(QT_TOTAL_PROFIT)}')
            QT_SESSION_ACTIVE = False
            QT_STEP = 0
            QT_DIRECTION = None
            QT_SESSION_START_BALANCE = None
            if tp_enabled:
                qt_check_take_profit(bal_after)
            QT_AMOUNT_SET = True
            return
        elif outcome == 'LOSS':
            if QT_STEP + 1 >= QT_MAX_STEPS:
                session_profit = (bal_after - QT_SESSION_START_BALANCE) if QT_SESSION_START_BALANCE is not None else delta
                QT_TOTAL_PROFIT += session_profit
                log(f'Quick Trade: martingale cap ({QT_MAX_STEPS}) reached {EMO_LOSS}. '
                    f'Session result: {session_profit:+.2f} | Total: {QT_TOTAL_PROFIT:+.2f} {total_emo(QT_TOTAL_PROFIT)}')
                QT_SESSION_ACTIVE = False
                QT_STEP = 0
                QT_DIRECTION = None
                QT_SESSION_START_BALANCE = None
                QT_AMOUNT_SET = True
                return
            QT_STEP += 1
        # DRAW: keep step
        QT_AMOUNT_SET = True

    # ---- Start a session if idle ----
    if not QT_SESSION_ACTIVE:
        asset = await read_selected_pair(driver)
        if not asset:
            _heartbeat('no selected pair readable from page')
            return
        candles = CANDLES.get(asset)
        need = min_candles_needed() + 1
        if not candles or len(candles) < need:
            _heartbeat(f'warming up on {asset}: {len(candles) if candles else 0}/{need} candles')
            return
        direction = await quick_trade_ma_direction(candles[:-1])
        if not direction:
            _heartbeat(f'{asset}: MA direction unclear (fast vs slow too close?)')
            return
        QT_DIRECTION = direction
        QT_SESSION_ACTIVE = True
        QT_STEP = 0
        QT_SESSION_START_BALANCE = await get_balance(driver)
        log(f'Quick Trade: new session on {asset}, direction {dir_emo(QT_DIRECTION)} {QT_DIRECTION.upper()}')

    # ---- Payout check ----
    if QT_MIN_PAYOUT and QT_MIN_PAYOUT > 0:
        try:
            payout_text = driver.find_element(By.CSS_SELECTOR, '.profitBx .Right .Text').text
            current_payout = int(re.sub(r'\D', '', payout_text) or 0)
            if current_payout < int(QT_MIN_PAYOUT):
                log(f'Quick Trade: payout {current_payout}% below minimum {QT_MIN_PAYOUT}%, waiting.')
                await asyncio.sleep(1)
                return
        except Exception:
            pass

    # ---- Whole-dollar stake ----
    if QT_STEP == 0:
        next_amount = int(QT_BASE_AMOUNT)
    else:
        next_amount = int(QT_BASE_AMOUNT * (QT_MARTINGALE ** QT_STEP))
    if next_amount < 1:
        next_amount = 1

    # Refuse to fire a stake the account can't cover.
    if not await _check_affordable(driver, next_amount):
        return

    # Safety net against multi-positions: if the DOM still shows an open trade,
    # do NOT fire another one - our timer may have run out but the real trade
    # hasn't settled yet.
    if await has_open_trade(driver):
        _heartbeat('open trade still in DOM, waiting before next order')
        await asyncio.sleep(0.5)
        return

    if not await set_amount(driver, next_amount):
        log('Quick Trade: could not set amount, aborting this attempt.')
        return

    ui_expiry = await read_ui_expiry(driver)
    expiry = ui_expiry if ui_expiry else QT_EXPIRY_SECONDS

    latest_before = read_latest_closed_trade(driver)
    QT_PREV_TRADE_ID = latest_before['id'] if latest_before else 0

    bal_before = await get_balance(driver)
    if bal_before is None:
        log('Quick Trade: could not read balance before trade.')
        return

    log(f'{dir_emo(QT_DIRECTION)} → QT {QT_DIRECTION.upper()} | stake ${next_amount} | step {QT_STEP} | expiry {expiry}s')
    if not await place_order(driver, QT_DIRECTION):
        log('Quick Trade: order not created, will retry next tick.')
        await asyncio.sleep(1)
        return

    QT_LAST_ACTION_ENDS_AT = datetime.now() + timedelta(seconds=expiry + 0.75)
    QT_TRADE_BALANCE_BEFORE = bal_before
    QT_TRADE_BET_AMOUNT = next_amount
    QT_AMOUNT_SET = False


# ============================================================
# MAIN
# ============================================================
async def wait_for_trade_room(driver, timeout=180, poll=2.0):
    """Poll until CloseOption's trade room has rendered (Buy/Sell + balance).
    Used in --no-prompt mode instead of blocking on input()."""
    waited = 0.0
    while waited < timeout:
        try:
            ok = driver.execute_script(
                """
                if (!document.querySelector('#mainBtns')) return false;
                var b = document.querySelector('.Balance .BBB');
                if (!b) return false;
                var t = (b.innerText || '').replace(/[^0-9.]/g, '');
                return !!(t && parseFloat(t) > 0);
                """)
            if ok:
                return True
        except Exception:
            pass
        await asyncio.sleep(poll)
        waited += poll
        if int(waited) % 10 == 0:
            log(f'Still waiting for trade room + balance... ({int(waited)}s)')
    return False


async def main():
    global EXPIRY_SECONDS, TRADING_MODE, QT_TAKE_PROFIT, INITIAL_DEPOSIT, \
        QT_SESSION_COUNT, QT_SESSION_ACTIVE, QT_DIRECTION, QT_STEP, QT_BASE_AMOUNT, \
        QT_LAST_ACTION_ENDS_AT, QT_TRADE_BALANCE_BEFORE, QT_TRADE_BET_AMOUNT, QT_AMOUNT_SET, \
        QT_TP_HIT, QT_SESSION_START_BALANCE, QT_TOTAL_PROFIT, QT_RUN_FINISHED, \
        QT_AUTO_CONTINUE, QT_PREV_TRADE_ID

    load_settings()  # re-read in case the GUI rewrote the file since import

    print()
    print('Available expiries on CloseOption:')
    print('  30s, 1m, 2m, 5m, 10m, 15m, 30m, 1h, 4h, 12h, 1d, 1w, 2w, 1mo')
    skip_prompt = '--no-prompt' in sys.argv
    if skip_prompt:
        log(f'Expiry set from settings file: {EXPIRY_SECONDS}s. Make sure the UI matches.')
    else:
        entry = input('Preferred expiry (e.g. 5m). ENTER = auto-detect from UI: ').strip()
    if not skip_prompt:
        if entry:
            parsed = parse_expiry(entry)
            if parsed:
                EXPIRY_SECONDS = parsed
                log(f'Expiry set by user: {entry} = {EXPIRY_SECONDS}s. Make sure the UI matches.')
            else:
                log(f'Could not parse "{entry}"; will auto-detect from UI instead.')
        else:
            log('Expiry will be auto-detected from the UI before each trade.')

    log('Launching Chrome (10-30s)...')
    try:
        driver = await get_driver()
    except Exception as e:
        log(f'FATAL: could not start Chrome: {e}')
        return

    log(f'Loading {URL}')
    try:
        await asyncio.wait_for(asyncio.to_thread(driver.get, URL), timeout=45)
    except asyncio.TimeoutError:
        log('Page load hung past 45s. Stopping Chrome and exiting.')
        try:
            driver.quit()
        except Exception:
            pass
        _kill_stale_chrome(_profile_path())
        return
    except Exception:
        log('Page load errored, continuing anyway.')

    if '--no-prompt' in sys.argv:
        log('Waiting for trade room to render (Buy/Sell + balance)...')
        ok = await wait_for_trade_room(driver)
        if not ok:
            log('WARNING: trade room did not render in 180s. '
                'Log in manually, then restart the bot.')
            driver.quit()
            return
        log('Trade room ready.')
    else:
        input('Log in if needed and open the trade room (chart + Buy/Sell visible), '
              'then press ENTER...')

    log(f'Warming up - need >= {min_candles_needed()} closed candles per asset '
        f'({CANDLE_PERIOD}s each). Sit tight.')

    mode = TRADING_MODE if TRADING_MODE in ('normal', 'quick') else 'normal'
    log(f'Trading mode: {mode}')

    # one-shot asset inventory so we know what pairs the socket is actually sending
    if mode == 'quick':
        await asyncio.sleep(6)
        if CANDLES:
            pairs = ', '.join(f'{a}({len(c)})' for a, c in sorted(CANDLES.items()))
            log(f'[QT] assets in stream: {pairs}')
        else:
            log('[QT] no assets yet - socket may not be connected')
        selected = await read_selected_pair(driver)
        log(f'[QT] selected pair on screen: {selected}')

    while True:  # outer restart loop (Quick Trade can auto-continue)
        consecutive_dead = 0
        while True:
            if not TRADING_ALLOWED:
                break
            if not await driver_alive(driver):
                consecutive_dead += 1
                if consecutive_dead >= 3:
                    log('Chrome session lost. Stopping.')
                    try:
                        driver.quit()
                    except Exception:
                        pass
                    _kill_stale_chrome(_profile_path())
                    return
                await asyncio.sleep(1)
                continue
            consecutive_dead = 0
            try:
                await poll_socket(driver)
                _now = datetime.now()
                _last = getattr(sys.modules[__name__], '_OPCODE_HEARTBEAT', None)
                if _last is None or (_now - _last).total_seconds() >= 15:
                    sys.modules[__name__]._OPCODE_HEARTBEAT = _now
                    if _SNIFF_OPCODES:
                        summary = ', '.join(f'op{k}={v}' for k, v in sorted(_SNIFF_OPCODES.items()))
                        if _WS_VERBOSE:
                            log(f'[ws] frames received: {summary}')
                    else:
                        if _WS_VERBOSE:
                            log('[ws] frames received: 0 (no websocket traffic)')
                    if _WS_METHODS:
                        top = ', '.join(f'{k.split(".")[-1]}={v}' for k, v in
                                        sorted(_WS_METHODS.items(), key=lambda kv: -kv[1])[:6])
                        if _WS_VERBOSE:
                            log(f'[ws] top CDP methods: {top}')
                await check_deposit(driver)
                if not TRADING_ALLOWED:
                    break
                if mode == 'quick':
                    await check_quick_trade(driver)
                    if QT_RUN_FINISHED:
                        break
                else:
                    await try_trade(driver)
            except KeyboardInterrupt:
                log('Interrupted, exiting.')
                driver.quit()
                return
            except Exception as e:
                log('Loop error:', e)
                await asyncio.sleep(1)
            await asyncio.sleep(0.5)

        if not TRADING_ALLOWED:
            end_balance = await get_balance(driver)
            reason = STOP_REASON or 'TP/SL'
            if end_balance and INITIAL_DEPOSIT:
                run_pnl = end_balance - INITIAL_DEPOSIT
                log(f'Bot stopped on {reason}. Balance {INITIAL_DEPOSIT:.2f} -> {end_balance:.2f} '
                    f'({run_pnl:+.2f}) {total_emo(run_pnl)}')
            else:
                log(f'Bot stopped on {reason}.')
            break

        if mode != 'quick':
            break  # normal mode never sets QT_RUN_FINISHED; bail out anyway

        # ---- Quick Trade run just finished ----
        was_tp_stop = QT_TP_HIT
        print()
        if was_tp_stop:
            log(f'Take profit reached. Total profit this run: {QT_TOTAL_PROFIT:+.2f} {total_emo(QT_TOTAL_PROFIT)}')
        else:
            log(f'Quick Trade finished {QT_SESSION_COUNT} session(s). Total profit: {QT_TOTAL_PROFIT:+.2f} {total_emo(QT_TOTAL_PROFIT)}')

        if QT_AUTO_CONTINUE:
            terminated = countdown_with_terminate(30, terminate_key='t')
            if terminated:
                log('Terminated.')
                break
            answer = 'a'
        else:
            try:
                answer = input('Do you want to continue? (Y/N/A - A = auto-continue at 5 sessions per run): ').strip().lower()
            except (EOFError, KeyboardInterrupt):
                answer = 'y'  # piped stdin (GUI) - just keep going
                log('(no stdin - continuing)')

        if answer not in ('y', 'a'):
            log('Stopping.')
            break

        if answer == 'a' and not QT_AUTO_CONTINUE:
            QT_AUTO_CONTINUE = True
            log('Auto-continue enabled: future runs use 5 sessions each, 30s countdown between.')

        if was_tp_stop:
            new_tp = float(QT_TAKE_PROFIT) + 50
            _save_setting('QT_TAKE_PROFIT', new_tp)
            QT_TAKE_PROFIT = new_tp
            log(f'Take profit raised to {new_tp:.2f}.')

        # Reset run state for a fresh Quick Trade run
        QT_SESSION_COUNT = 0
        QT_TP_HIT = False
        QT_RUN_FINISHED = False
        QT_TOTAL_PROFIT = 0.0
        QT_SESSION_ACTIVE = False
        QT_DIRECTION = None
        QT_STEP = 0
        QT_SESSION_START_BALANCE = None
        INITIAL_DEPOSIT = None

    driver.quit()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
