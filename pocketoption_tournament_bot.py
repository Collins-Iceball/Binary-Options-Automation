#!/usr/bin/env python3
"""
Pocket Option Tournament Bot — Collins_Obi

Tournament layer built on top of the existing pocketoption_bot.py connection layer.
It reuses the existing Chrome/WebSocket candle feed, asset switching, payout reading,
balance reading and order-button automation, while replacing the old fixed normal/quick
logic with a tournament scanner/risk engine.

IMPORTANT:
- Default is PAPER_MODE=True. Set it to False in the GUI before live execution.
- This is an execution/analysis tool, not a guarantee of profit or tournament placement.
- It only trades assets for which Pocket Option exposes candle data to this browser session.
- Leaderboard parsing is best-effort because Pocket Option can change its DOM.
"""

import asyncio
import csv
import math
import os
import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta

import customtkinter as ctk

import pocketoption_bot as po


# ---------------------------------------------------------------------------
# Tournament settings
# ---------------------------------------------------------------------------

TSET = {
    "MIN_PAYOUT": 92,
    "TOURNAMENT_HOURS": 12.0,
    "MIN_SCORE": 72,
    "STRONG_SCORE": 82,
    "MIN_CANDLES": 80,
    "SCAN_INTERVAL": 0.8,
    "ASSET_REFRESH_SECONDS": 30,
    "LEADERBOARD_REFRESH_SECONDS": 15,
    "BALANCE_REFRESH_SECONDS": 2,
    "BASE_STAKE": 1.0,
    "MAX_STAKE_PCT": 0.15,
    "NORMAL_STAKE_PCT": 0.025,
    "STRONG_STAKE_PCT": 0.05,
    "FINAL_STAKE_PCT": 0.10,
    "MAX_CONSECUTIVE_LOSSES": 3,
    "LOSS_COOLDOWN_SECONDS": 60,
    "ONE_TRADE_PER_CANDLE": True,
    "USE_LEADERBOARD": True,
    "PAPER_MODE": True,
    "EXPIRIES": "30,60,90,120,180",
    "LOG_FILE": "tournament_trades.csv",
    "STATE_FILE": "tournament_state.txt",
    "LEADERBOARD_SELECTORS": (
        "table, [class*='tournament'], [class*='rating'], "
        "[class*='leaderboard'], [class*='ranking']"
    ),
}

# State
TOUR_START = None
TOUR_END = None
LAST_BALANCE = 0.0
LAST_BALANCE_READ = 0.0
LAST_LEADERBOARD = []
LAST_LEADERBOARD_AT = datetime.min
LAST_ASSET_DISCOVERY = datetime.min
LAST_SCAN_AT = datetime.min
LAST_TRADE_CANDLE = {}
OPEN_TRADE = None
CONSECUTIVE_LOSSES = 0
LOSS_COOLDOWN_UNTIL = datetime.min
TRADE_SEQ = 0
STOP_REQUESTED = False
CURRENT_TARGET = 0.0
CURRENT_LEADER_GAP = 0.0
LOG_LOCK = asyncio.Lock()
HISTORY = defaultdict(lambda: {"wins": 0, "losses": 0, "draws": 0})
RECENT_RESULTS = deque(maxlen=100)
ASSET_LAST_SCORE = {}
ASSET_LAST_REASON = {}


@dataclass
class Candidate:
    asset: str
    direction: str
    score: float
    payout: int
    expiry: int
    reasons: list
    votes: dict
    regime: str
    volatility: float
    structure: float


# ---------------------------------------------------------------------------
# Logging / persistence
# ---------------------------------------------------------------------------

def tlog(msg):
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"🕓 {stamp} {msg}")


def append_trade(row):
    path = TSET["LOG_FILE"]
    exists = os.path.exists(path)
    fields = [
        "timestamp", "trade_id", "asset", "direction", "expiry",
        "stake", "balance_before", "balance_after", "outcome",
        "score", "payout", "regime", "leader", "our_rank", "leader_gap",
        "reasons",
    ]
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if not exists:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in fields})


def save_state():
    try:
        with open(TSET["STATE_FILE"], "w", encoding="utf-8") as f:
            f.write(f"start={TOUR_START.isoformat() if TOUR_START else ''}\n")
            f.write(f"end={TOUR_END.isoformat() if TOUR_END else ''}\n")
            f.write(f"balance={LAST_BALANCE}\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Generic numerical helpers
# ---------------------------------------------------------------------------

def closes(candles):
    return [float(c[2]) for c in candles if len(c) >= 3 and isinstance(c[2], (int, float))]


def ohlc(candles):
    out = []
    for c in candles:
        try:
            out.append((float(c[1]), float(c[3]), float(c[4]), float(c[2])))
        except Exception:
            continue
    return out


def sma(values, n):
    if len(values) < n:
        return None
    return sum(values[-n:]) / n


def ema(values, n):
    if len(values) < n:
        return None
    k = 2.0 / (n + 1.0)
    e = sum(values[:n]) / n
    for v in values[n:]:
        e = v * k + e * (1 - k)
    return e


def pct_change(a, b):
    if a == 0:
        return 0.0
    return (b - a) / abs(a)


def atr(candles, n=14):
    data = ohlc(candles)
    if len(data) < n + 2:
        return None
    trs = []
    prev_close = data[0][3]
    for o, h, l, c in data[1:]:
        trs.append(max(h - l, abs(h - prev_close), abs(l - prev_close)))
        prev_close = c
    return sum(trs[-n:]) / n if len(trs) >= n else None


def rsi_simple(values, n=14):
    if len(values) < n + 1:
        return None
    gains = []
    losses = []
    for a, b in zip(values[-n-1:-1], values[-n:]):
        d = b - a
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = sum(gains) / n
    al = sum(losses) / n
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + ag / al)


def aggregate_candles(candles, bucket_seconds):
    """Aggregate PO candles to a higher timeframe using timestamp buckets."""
    if not candles:
        return []
    out = []
    bucket = {}
    for c in candles:
        try:
            ts, op, hi, lo, cl = int(float(c[0])), float(c[1]), float(c[3]), float(c[4]), float(c[2])
        except Exception:
            continue
        b = ts - (ts % bucket_seconds)
        if b not in bucket:
            bucket[b] = [b, op, cl, hi, lo]
        else:
            x = bucket[b]
            x[2] = cl
            x[3] = max(x[3], hi)
            x[4] = min(x[4], lo)
    for b in sorted(bucket):
        out.append(bucket[b])
    return out


def trend_signal(candles, fast=5, slow=20):
    c = closes(candles)
    if len(c) < slow + 2:
        return 0
    f1, f2 = sma(c[:-1], fast), sma(c, fast)
    s1, s2 = sma(c[:-1], slow), sma(c, slow)
    if None in (f1, f2, s1, s2):
        return 0
    if f2 > s2 and f2 >= f1:
        return 1
    if f2 < s2 and f2 <= f1:
        return -1
    return 0


def momentum_signal(candles, lookback=5):
    c = closes(candles)
    if len(c) <= lookback:
        return 0
    d = c[-1] - c[-1-lookback]
    if d > 0:
        return 1
    if d < 0:
        return -1
    return 0


def price_action_signal(candles):
    if len(candles) < 4:
        return 0
    o1, h1, l1, c1 = ohlc(candles)[-1]
    o2, h2, l2, c2 = ohlc(candles)[-2]
    body = abs(c1 - o1)
    rng = max(h1 - l1, 1e-12)
    # engulfing
    bull_engulf = c1 > o1 and c2 < o2 and c1 >= o2 and o1 <= c2
    bear_engulf = c1 < o1 and c2 > o2 and c1 <= o2 and o1 >= c2
    # rejection wick
    lower = min(o1, c1) - l1
    upper = h1 - max(o1, c1)
    if bull_engulf or (lower > body * 1.5 and lower > upper * 1.25 and c1 > o1):
        return 1
    if bear_engulf or (upper > body * 1.5 and upper > lower * 1.25 and c1 < o1):
        return -1
    return 0


def structure_signal(candles, lookback=17):
    """Fractal-style structure using the user's previously used period 17."""
    data = ohlc(candles)
    if len(data) < lookback * 2 + 3:
        return 0, 0.0
    # ohlc() returns (open, close, high, low); use CLOSE for zone position.
    last = data[-1][1]
    highs = [x[1] for x in data[-(lookback*2+1):-1]]
    lows = [x[2] for x in data[-(lookback*2+1):-1]]
    hi = max(highs)
    lo = min(lows)
    span = max(hi - lo, 1e-12)
    pos = (last - lo) / span
    # Near lower zone -> CALL reversal bias; near upper -> PUT reversal bias.
    if pos <= 0.20:
        return 1, 1 - pos
    if pos >= 0.80:
        return -1, pos
    return 0, 0.0


def volatility_regime(candles):
    a = atr(candles, 14)
    c = closes(candles)
    if a is None or len(c) < 30 or c[-1] == 0:
        return "unknown", 0.0
    normalized = a / abs(c[-1])
    recent = []
    for i in range(max(15, len(c)-60), len(c)):
        aa = atr(candles[:i], 14)
        if aa is not None and c[i-1] != 0:
            recent.append(aa / abs(c[i-1]))
    med = sorted(recent)[len(recent)//2] if recent else normalized
    ratio = normalized / max(med, 1e-12)
    if ratio > 1.8:
        return "high", ratio
    if ratio < 0.65:
        return "low", ratio
    return "normal", ratio


# ---------------------------------------------------------------------------
# Strategy ensemble
# ---------------------------------------------------------------------------

async def strategy_votes(candles):
    """
    Use the existing bot's indicator implementations where practical.
    Returns votes in {-1,0,+1}; no single indicator is allowed to decide alone.
    """
    # Use closed candles only when a live candle is present.
    data = candles[:-1] if len(candles) > 5 else candles
    votes = {}
    try:
        votes["ma"] = {"call": 1, "put": -1}.get(await po.moving_averages_cross(data), 0)
    except Exception:
        votes["ma"] = 0
    try:
        votes["psar"] = {"call": 1, "put": -1}.get(await po.psar_strategy(data), 0)
    except Exception:
        votes["psar"] = 0
    try:
        votes["vortex"] = {"call": 1, "put": -1}.get(await po.vortex_strategy(data), 0)
    except Exception:
        votes["vortex"] = 0
    try:
        votes["marubozu"] = {"call": 1, "put": -1}.get(await po.marubozu_strategy(data), 0)
    except Exception:
        votes["marubozu"] = 0
    try:
        votes["cci"] = {"call": 1, "put": -1}.get(await po.cci_strategy(data), 0)
    except Exception:
        votes["cci"] = 0
    try:
        votes["bb"] = {"call": 1, "put": -1}.get(await po.bollinger_bands_strategy(data), 0)
    except Exception:
        votes["bb"] = 0

    votes["trend"] = trend_signal(data, 5, 20)
    votes["momentum"] = momentum_signal(data, 5)
    votes["price_action"] = price_action_signal(data)
    stf = aggregate_candles(data, max(po.PERIOD, 60) * 5)
    ltf = aggregate_candles(data, max(po.PERIOD, 60) * 10)
    votes["5x_trend"] = trend_signal(stf, 3, 8)
    votes["10x_trend"] = trend_signal(ltf, 3, 8)

    r = rsi_simple(closes(data), 14)
    if r is None:
        votes["rsi"] = 0
    elif r < 35:
        votes["rsi"] = 1
    elif r > 65:
        votes["rsi"] = -1
    else:
        votes["rsi"] = 0

    return votes


async def score_asset(asset, candles, payout):
    if len(candles) < TSET["MIN_CANDLES"]:
        return None

    votes = await strategy_votes(candles)
    struct, struct_strength = structure_signal(candles, 17)
    regime, vol_ratio = volatility_regime(candles)

    weighted = {
        "ma": 1.5, "psar": 0.8, "vortex": 1.2, "marubozu": 0.8,
        "cci": 1.0, "bb": 1.0, "trend": 1.7, "momentum": 1.0,
        "price_action": 1.4, "5x_trend": 1.5, "10x_trend": 1.7,
        "rsi": 0.8,
    }
    total = sum(weighted.values())
    signed = sum(votes[k] * weighted[k] for k in weighted)
    direction = "call" if signed > 0 else "put" if signed < 0 else None
    if not direction:
        return None

    agreement = abs(signed) / total
    score = 50 + agreement * 35

    # Multi-timeframe agreement is rewarded heavily.
    d = 1 if direction == "call" else -1
    if votes["5x_trend"] == d:
        score += 6
    if votes["10x_trend"] == d:
        score += 7
    if votes["price_action"] == d:
        score += 5
    if struct == d:
        score += 5 * struct_strength
    elif struct == -d:
        score -= 6

    # Avoid treating extreme volatility as automatically bullish/bearish.
    if regime == "high":
        score -= 5
    elif regime == "normal":
        score += 2
    elif regime == "low":
        score -= 1

    # RSI conflict is a penalty; RSI alone never generates a trade.
    if votes["rsi"] == -d:
        score -= 5

    score = max(0.0, min(100.0, score))
    reasons = [
        f"ensemble={signed:+.1f}/{total:.1f}",
        f"5x={'+' if votes['5x_trend']==d else '-'}",
        f"10x={'+' if votes['10x_trend']==d else '-'}",
        f"PA={'+' if votes['price_action']==d else '-'}",
        f"structure={struct:+d}",
        f"vol={regime}",
    ]
    return {
        "asset": asset,
        "direction": direction,
        "score": score,
        "payout": payout,
        "votes": votes,
        "regime": regime,
        "volatility": vol_ratio,
        "structure": struct_strength,
        "reasons": reasons,
    }


# ---------------------------------------------------------------------------
# Pocket Option UI helpers
# ---------------------------------------------------------------------------

async def discover_assets(driver):
    """
    Discover actual Pocket Option chart assets.

    The previous version queried every [data-id] element on the page. PO uses
    data-id for many unrelated UI elements, and the asset strip itself is
    represented by .assets-favorites-item. That caused an empty asset list and
    therefore every scan ended with "No valid market candidate".

    First use the same favorite-asset elements that the original connection
    layer already knows how to switch. Then add assets already present in the
    WebSocket candle cache and the current chart.
    """
    global LAST_ASSET_DISCOVERY
    now = datetime.now()
    if (now - LAST_ASSET_DISCOVERY).total_seconds() < TSET["ASSET_REFRESH_SECONDS"]:
        cached = list(dict.fromkeys(list(po.CANDLES.keys()) + ([po.CURRENT_ASSET] if po.CURRENT_ASSET else [])))
        if cached:
            return cached

    assets = []

    # This is the real asset strip used by the original PO connector.
    try:
        items = driver.find_elements(po.By.CLASS_NAME, "assets-favorites-item")
        for item in items:
            aid = (item.get_attribute("data-id") or "").strip()
            if aid and aid not in assets:
                assets.append(aid)
    except Exception as e:
        tlog(f"Asset strip read failed: {e}")

    # Existing candle streams are valid assets too.
    for aid in po.CANDLES.keys():
        if aid and aid not in assets:
            assets.append(aid)

    # Always retain the chart currently on screen.
    try:
        active = await po.read_active_asset(driver)
    except Exception:
        active = None
    active = active or po.CURRENT_ASSET
    if active and active not in assets:
        assets.insert(0, active)

    LAST_ASSET_DISCOVERY = now
    if assets:
        tlog(f"Asset scanner: {len(assets)} chart assets available: {', '.join(assets[:12])}{' ...' if len(assets) > 12 else ''}")
    else:
        tlog("⚠️ Asset scanner found 0 chart assets. Open the Pocket Option chart/favorites strip.")
    return assets


async def switch_to_any_asset(driver, asset):
    """
    Tournament-specific asset switcher.
    The original bot switches only .assets-favorites-item. Tournament scanning
    needs every asset currently exposed in the page DOM, so this first tries
    any [data-id] asset node and falls back to the original switcher.
    """
    try:
        current = await po.read_active_asset(driver)
        if current == asset:
            return True
    except Exception:
        pass

    script = """
    const wanted = arguments[0];
    const nodes = document.querySelectorAll('[data-id]');
    for (const e of nodes) {
      if (e.getAttribute('data-id') !== wanted) continue;
      const cls = String(e.className || '').toLowerCase();
      const txt = String(e.textContent || '').trim();
      if (!(cls.includes('asset') || cls.includes('favorite') || /[A-Z]{3,6}.*(USD|EUR|GBP|JPY|CHF|AUD|CAD|NZD)/i.test(wanted))) {
        continue;
      }
      try { e.scrollIntoView({block:'center', inline:'center'}); } catch(_) {}
      try { e.click(); return true; } catch(_) {}
      try {
        e.dispatchEvent(new MouseEvent('mousedown', {bubbles:true}));
        e.dispatchEvent(new MouseEvent('mouseup', {bubbles:true}));
        e.dispatchEvent(new MouseEvent('click', {bubbles:true}));
        return true;
      } catch(_) {}
    }
    return false;
    """
    try:
        clicked = await asyncio.to_thread(driver.execute_script, script, asset)
        if clicked:
            await asyncio.sleep(0.25)
            current = await po.read_active_asset(driver)
            if current == asset:
                po.CURRENT_ASSET = asset
                return True
    except Exception:
        pass

    # Existing, known-good favorites path.
    return await po.switch_to_asset(driver, asset)


async def get_payout(driver, asset):
    try:
        if await po.read_active_asset(driver) != asset:
            if not await switch_to_any_asset(driver, asset):
                return None
            # Let WebSocket history arrive.
            await asyncio.sleep(0.35)
            await po.websocket_log(driver)
        text = driver.find_element(po.By.CLASS_NAME, "value__val-start").text.strip()
        m = re.search(r"(\d+)", text)
        return int(m.group(1)) if m else None
    except Exception:
        return None


async def set_expiry(driver, seconds):
    # Reuse the existing expiry setter; it already verifies what landed in the UI.
    old = po.SETTINGS.get("QT_EXPIRY_SECONDS", 5)
    po.SETTINGS["QT_EXPIRY_SECONDS"] = int(seconds)
    try:
        return await po.set_quick_trade_expiry(driver)
    finally:
        po.SETTINGS["QT_EXPIRY_SECONDS"] = old


async def set_amount(driver, amount):
    amount = max(1, int(math.floor(amount)))
    css = "#put-call-buttons-chart-1 input[type='text']"
    js = """
    var input = document.querySelector("#put-call-buttons-chart-1 input[type='text']");
    if(!input) input = document.querySelector(".block--bet-amount input");
    if(!input) return false;
    var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
    setter.call(input, arguments[0].toString());
    input.dispatchEvent(new Event("input", {bubbles:true}));
    input.dispatchEvent(new Event("change", {bubbles:true}));
    return true;
    """
    ok = driver.execute_script(js, amount)
    if not ok:
        return False
    await po.hand_delay()
    try:
        val = float(driver.find_element(po.By.CSS_SELECTOR, css).get_attribute("value").replace(",", ""))
        return round(val, 2) == round(amount, 2)
    except Exception:
        return False


async def read_visible_tournament_text(driver):
    js = """
    const root = document.body;
    return root ? root.innerText : "";
    """
    try:
        return await asyncio.to_thread(driver.execute_script, js) or ""
    except Exception:
        return ""


def parse_remaining_seconds(text):
    m = re.search(r"Ends\\s+in\\s+(?:(\\d+)\\s*h\\s*)?(?:(\\d+)\\s*m\\s*)?(?:(\\d+)\\s*s)?", text, re.I)
    if not m:
        return None
    h = int(m.group(1) or 0)
    mi = int(m.group(2) or 0)
    s = int(m.group(3) or 0)
    return h * 3600 + mi * 60 + s


async def read_tournament_remaining(driver):
    text = await read_visible_tournament_text(driver)
    sec = parse_remaining_seconds(text)
    if sec is not None:
        return sec
    if TOUR_END:
        return max(0, int((TOUR_END - datetime.now()).total_seconds()))
    return int(TSET["TOURNAMENT_HOURS"] * 3600)


async def read_leaderboard(driver):
    """
    Best-effort parser. It intentionally does not infer competitor trades.
    It only extracts visible leaderboard balances/ranks from the page.
    """
    global LAST_LEADERBOARD, LAST_LEADERBOARD_AT
    now = datetime.now()
    if (now - LAST_LEADERBOARD_AT).total_seconds() < TSET["LEADERBOARD_REFRESH_SECONDS"]:
        return LAST_LEADERBOARD

    script = f"""
    const selectors = `{TSET["LEADERBOARD_SELECTORS"]}`.split(",").map(x=>x.trim());
    const rows = [];
    const seen = new Set();
    for (const sel of selectors) {{
      let nodes = [];
      try {{ nodes = document.querySelectorAll(sel); }} catch(e) {{}}
      for (const n of nodes) {{
        const txt = (n.innerText || n.textContent || "").trim();
        if (!txt || seen.has(txt)) continue;
        seen.add(txt);
        rows.push(txt);
      }}
    }}
    return rows.slice(0, 500);
    """
    try:
        chunks = await asyncio.to_thread(driver.execute_script, script)
        candidates = []
        for chunk in chunks or []:
            # Look for monetary/decimal numbers; remove prize-like values when possible.
            nums = re.findall(r"(?:[$€£]\\s*)?([0-9][0-9,]*(?:\\.\\d+)?)", chunk.replace("\\n", " "))
            if not nums:
                continue
            vals = []
            for n in nums:
                try:
                    vals.append(float(n.replace(",", "")))
                except Exception:
                    pass
            # Tournament balances are generally the largest number in a row,
            # while a prize ($125/$75/$50) is much smaller.
            if vals:
                candidates.append(max(vals))
        candidates = sorted(set(v for v in candidates if v > 100), reverse=True)
        LAST_LEADERBOARD = candidates[:50]
        LAST_LEADERBOARD_AT = now
        return LAST_LEADERBOARD
    except Exception:
        return LAST_LEADERBOARD


# ---------------------------------------------------------------------------
# Tournament risk engine
# ---------------------------------------------------------------------------

def our_rank(balance, leaderboard):
    if not leaderboard:
        return None
    higher = sum(1 for x in leaderboard if x > balance)
    return higher + 1


def tournament_stake(balance, score, remaining, leader):
    """
    Adaptive tournament staking.

    The leaderboard can increase allowable risk, but it never creates a trade.
    Stake is always bounded by MAX_STAKE_PCT and reduced after losses.
    """
    if balance <= 0:
        return 0

    hours = remaining / 3600.0
    pct = TSET["NORMAL_STAKE_PCT"]

    if score >= TSET["STRONG_SCORE"]:
        pct = TSET["STRONG_STAKE_PCT"]

    # Final-hour pressure increases exposure only if the signal is already strong.
    if hours <= 1.0 and score >= TSET["STRONG_SCORE"]:
        pct = max(pct, TSET["FINAL_STAKE_PCT"])

    if leader and leader > balance:
        gap = leader / max(balance, 1)
        # Bounded tournament-pressure factor. It never exceeds max risk.
        if gap >= 20:
            pct *= 1.8
        elif gap >= 10:
            pct *= 1.5
        elif gap >= 5:
            pct *= 1.25
        elif gap >= 2:
            pct *= 1.10

    if CONSECUTIVE_LOSSES == 1:
        pct *= 0.70
    elif CONSECUTIVE_LOSSES == 2:
        pct *= 0.50
    elif CONSECUTIVE_LOSSES >= TSET["MAX_CONSECUTIVE_LOSSES"]:
        return 0

    pct = min(pct, TSET["MAX_STAKE_PCT"])
    amount = max(TSET["BASE_STAKE"], balance * pct)
    amount = min(amount, max(TSET["BASE_STAKE"], balance))
    return int(math.floor(amount))


# ---------------------------------------------------------------------------
# Trade execution/result handling
# ---------------------------------------------------------------------------

async def wait_for_settlement(driver, before, stake, timeout):
    waited = 0.0
    last = before
    while waited < timeout:
        last = await po.get_balance_robust(driver)
        if last and before and abs(last - before) > max(0.005, stake * 0.01):
            return last
        await asyncio.sleep(0.25)
        waited += 0.25
    return last


def classify_result(before, after, stake):
    if before is None or after is None:
        return "UNKNOWN"
    delta = after - before
    tol = max(0.05, stake * 0.05)
    if delta < -stake + tol:
        return "LOSS"
    if delta > tol:
        return "WIN"
    return "DRAW"


async def execute_candidate(driver, cand, stake, leader, rank, remaining):
    global OPEN_TRADE, TRADE_SEQ, CONSECUTIVE_LOSSES, LOSS_COOLDOWN_UNTIL, LAST_BALANCE

    if stake < 1:
        return False

    if datetime.now() < LOSS_COOLDOWN_UNTIL:
        return False

    if not await po.switch_to_asset(driver, cand.asset):
        return False

    payout = await get_payout(driver, cand.asset)
    if payout is not None and payout < TSET["MIN_PAYOUT"]:
        return False

    confirmed_expiry = await set_expiry(driver, cand.expiry)
    if not confirmed_expiry:
        return False

    if not await set_amount(driver, stake):
        tlog(f"Stake write failed for {cand.asset}; trade aborted.")
        return False

    before = await po.get_balance_robust(driver)
    if before <= 0:
        return False

    TRADE_SEQ += 1
    trade_id = TRADE_SEQ

    tlog(
        f"🎯 #{trade_id} {cand.direction.upper()} {cand.asset} "
        f"stake=${stake} expiry={confirmed_expiry}s score={cand.score:.1f} "
        f"payout={payout or cand.payout}% | {', '.join(cand.reasons)}"
    )

    if TSET["PAPER_MODE"]:
        tlog("🧪 PAPER MODE — no order button clicked.")
        # Simulated outcome is deliberately NOT fabricated.
        return False

    ok = await po.create_order(driver, cand.direction, cand.asset, skip_cooldown=True)
    if not ok:
        return False

    OPEN_TRADE = {
        "id": trade_id,
        "asset": cand.asset,
        "direction": cand.direction,
        "stake": stake,
        "expiry": confirmed_expiry,
        "before": before,
        "score": cand.score,
        "payout": payout or cand.payout,
        "regime": cand.regime,
        "leader": leader,
        "rank": rank,
        "gap": leader / before if leader and before else 0,
        "reasons": cand.reasons,
    }

    await asyncio.sleep(confirmed_expiry + 0.75)
    after = await wait_for_settlement(driver, before, stake, timeout=5.0)
    outcome = classify_result(before, after, stake)

    if outcome == "LOSS":
        CONSECUTIVE_LOSSES += 1
        LOSS_COOLDOWN_UNTIL = datetime.now() + timedelta(
            seconds=TSET["LOSS_COOLDOWN_SECONDS"] * max(1, CONSECUTIVE_LOSSES)
        )
    elif outcome == "WIN":
        CONSECUTIVE_LOSSES = 0
    elif outcome == "DRAW":
        pass

    key = (cand.asset, cand.direction, confirmed_expiry, cand.regime)
    HISTORY[key][{"WIN": "wins", "LOSS": "losses", "DRAW": "draws"}.get(outcome, "draws")] += 1
    RECENT_RESULTS.append(outcome)

    LAST_BALANCE = after if after else before
    append_trade({
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "trade_id": trade_id,
        "asset": cand.asset,
        "direction": cand.direction,
        "expiry": confirmed_expiry,
        "stake": stake,
        "balance_before": before,
        "balance_after": after,
        "outcome": outcome,
        "score": round(cand.score, 2),
        "payout": payout or cand.payout,
        "regime": cand.regime,
        "leader": leader or "",
        "our_rank": rank or "",
        "leader_gap": round(leader / before, 4) if leader and before else "",
        "reasons": "; ".join(cand.reasons),
    })

    tlog(
        f"📊 RESULT {outcome} | ${before:.2f} -> "
        f"${after:.2f} | consecutive losses={CONSECUTIVE_LOSSES}"
    )
    OPEN_TRADE = None
    return True


# ---------------------------------------------------------------------------
# Candidate selection
# ---------------------------------------------------------------------------

def choose_expiry(asset, score):
    # Until enough empirical history exists, prefer the middle of the allowed set.
    vals = []
    for x in str(TSET["EXPIRIES"]).split(","):
        try:
            n = int(x.strip())
            if n >= 5:
                vals.append(n)
        except Exception:
            pass
    if not vals:
        return 60
    # Stronger setups get a shorter expiry; weaker accepted setups get a little more time.
    vals = sorted(set(vals))
    if score >= 85:
        return vals[min(1, len(vals)-1)]
    if score >= 78:
        return vals[min(2, len(vals)-1)]
    return vals[min(3, len(vals)-1)]


async def scan_markets(driver):
    assets = await discover_assets(driver)
    candidates = []
    stats = {"assets": len(assets), "switched": 0, "candles": 0, "short": 0, "low_payout": 0, "scored": 0}

    for asset in assets:
        if STOP_REQUESTED:
            break
        try:
            if not await switch_to_any_asset(driver, asset):
                continue
            stats["switched"] += 1

            # Switching charts triggers PO's WebSocket history response. Poll
            # briefly instead of assuming 180 ms is enough.
            candles = None
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                await po.websocket_log(driver)
                candles = po.CANDLES.get(asset)
                if candles and len(candles) >= TSET["MIN_CANDLES"]:
                    break
                await asyncio.sleep(0.15)

            if not candles:
                continue
            stats["candles"] += 1
            if len(candles) < TSET["MIN_CANDLES"]:
                stats["short"] += 1
                ASSET_LAST_REASON[asset] = f"only {len(candles)} candles (need {TSET['MIN_CANDLES']})"
                continue

            payout = await get_payout(driver, asset)
            if payout is not None and payout < TSET["MIN_PAYOUT"]:
                stats["low_payout"] += 1
                ASSET_LAST_REASON[asset] = f"payout {payout}% < {TSET['MIN_PAYOUT']}%"
                continue

            result = await score_asset(asset, candles, payout or TSET["MIN_PAYOUT"])
            if not result:
                ASSET_LAST_REASON[asset] = "ensemble produced no direction"
                continue

            stats["scored"] += 1
            ASSET_LAST_SCORE[asset] = result["score"]
            ASSET_LAST_REASON[asset] = "; ".join(result["reasons"])
            result["expiry"] = choose_expiry(asset, result["score"])
            candidates.append(result)
        except Exception as e:
            ASSET_LAST_REASON[asset] = f"scan error: {e}"

    candidates.sort(key=lambda x: x["score"], reverse=True)
    if not candidates:
        details = ", ".join(f"{a}:{ASSET_LAST_REASON.get(a,'no-data')}" for a in assets[:8])
        tlog(f"🔎 No valid market candidate | assets={stats['assets']} switched={stats['switched']} candle_sets={stats['candles']} short={stats['short']} low_payout={stats['low_payout']} scored={stats['scored']}" + (f" | {details}" if details else ""))
    else:
        top = candidates[:3]
        tlog("📊 Candidates: " + " | ".join(f"{x['asset']} {x['direction'].upper()} {x['score']:.1f}" for x in top))
    return candidates


# ---------------------------------------------------------------------------
# Tournament main loop
# ---------------------------------------------------------------------------

async def tournament_main():
    global TOUR_START, TOUR_END, LAST_BALANCE, LAST_BALANCE_READ
    global CURRENT_TARGET, CURRENT_LEADER_GAP, STOP_REQUESTED, LAST_SCAN_AT

    po.SETTINGS.update({
        "MIN_PAYOUT": TSET["MIN_PAYOUT"],
        "TRADING_MODE": "normal",
        "SMART_FILTERS_ENABLED": False,
        "ONE_TRADE_PER_CANDLE": True,
    })

    await po.set_remote_debugging_allowed()
    tlog("🚀 Launching Chrome using the existing Pocket Option connection layer...")
    driver = await po.get_driver()
    await asyncio.sleep(3)

    # Preserve existing logged-in/tournament tab when possible.
    current = driver.current_url
    if not ("pocketoption" in current or "cabinet" in current or "tournament" in current):
        try:
            driver.get(po.URL)
        except Exception:
            pass

    # Initial state.
    await po.websocket_log(driver)
    LAST_BALANCE = await po.get_balance_robust(driver)
    LAST_BALANCE_READ = LAST_BALANCE
    TOUR_START = datetime.now()
    TOUR_END = TOUR_START + timedelta(hours=TSET["TOURNAMENT_HOURS"])
    save_state()

    tlog(f"💰 Starting balance: ${LAST_BALANCE:.2f}")
    tlog(f"⏱️ Fallback tournament clock: {TSET['TOURNAMENT_HOURS']:.1f} hours")
    tlog(f"📈 Minimum payout: {TSET['MIN_PAYOUT']}%")
    tlog(f"🧪 PAPER_MODE={TSET['PAPER_MODE']}")

    consecutive_dead = 0

    while not STOP_REQUESTED:
        if not await po.driver_alive(driver):
            consecutive_dead += 1
            if consecutive_dead >= 3:
                tlog("Chrome session lost. Stopping safely.")
                break
            await asyncio.sleep(1)
            continue
        consecutive_dead = 0

        await po.websocket_log(driver)

        remaining = await read_tournament_remaining(driver)
        if remaining <= 0:
            tlog("🏁 Tournament time reached. Stopping.")
            break

        balance = await po.get_balance_robust(driver)
        if balance and balance > 0:
            LAST_BALANCE = balance
            LAST_BALANCE_READ = balance

        leaderboard = await read_leaderboard(driver) if TSET["USE_LEADERBOARD"] else []
        leader = leaderboard[0] if leaderboard else 0.0
        rank = our_rank(LAST_BALANCE, leaderboard)

        CURRENT_TARGET = leader
        CURRENT_LEADER_GAP = leader / LAST_BALANCE if leader and LAST_BALANCE else 0.0

        # Don't trade if we have just traded the same candle/asset.
        if datetime.now() >= LOSS_COOLDOWN_UNTIL:
            candidates = await scan_markets(driver)
            if candidates:
                best = candidates[0]
                asset = best["asset"]
                candle_ts = po.CANDLES.get(asset, [[]])[-1][0] if po.CANDLES.get(asset) else None
                if TSET["ONE_TRADE_PER_CANDLE"] and candle_ts == LAST_TRADE_CANDLE.get(asset):
                    candidates = candidates[1:]

                if candidates:
                    best = candidates[0]
                    if best["score"] >= TSET["MIN_SCORE"]:
                        stake = tournament_stake(
                            LAST_BALANCE,
                            best["score"],
                            remaining,
                            leader,
                        )

                        # Avoid stacking trades while one is settling.
                        if stake >= 1 and OPEN_TRADE is None:
                            tlog(
                                f"🏆 BEST {best['asset']} {best['direction'].upper()} "
                                f"score={best['score']:.1f} stake=${stake} "
                                f"leader=${leader:.2f} rank={rank or '?'} "
                                f"remaining={remaining//3600}h {(remaining%3600)//60}m"
                            )
                            traded = await execute_candidate(
                                driver, Candidate(
                                    asset=best["asset"],
                                    direction=best["direction"],
                                    score=best["score"],
                                    payout=best["payout"],
                                    expiry=best["expiry"],
                                    reasons=best["reasons"],
                                    votes=best["votes"],
                                    regime=best["regime"],
                                    volatility=best["volatility"],
                                    structure=best["structure"],
                                ),
                                stake,
                                leader,
                                rank,
                                remaining,
                            )
                            if traded:
                                LAST_TRADE_CANDLE[asset] = candle_ts
                        else:
                            tlog(
                                f"⏸️ Candidate accepted but stake/lock blocked "
                                f"(stake=${stake}, open={OPEN_TRADE is not None})."
                            )
                    else:
                        tlog(f"⏸️ Best score {best['score']:.1f} below threshold {TSET['MIN_SCORE']}.")
            else:
                tlog("🔎 No valid market candidate this scan.")
        else:
            wait = max(1, int((LOSS_COOLDOWN_UNTIL - datetime.now()).total_seconds()))
            tlog(f"🧊 Loss cooldown active: {wait}s.")

        save_state()
        await asyncio.sleep(TSET["SCAN_INTERVAL"])

    try:
        end_balance = await po.get_balance_robust(driver)
        tlog(f"🏁 Tournament bot stopped. Balance=${end_balance:.2f}")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

def run_gui():
    global TSET

    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
    root = ctk.CTk()
    root.title("Pocket Option — Tournament AI")
    root.geometry("980x760")
    root.minsize(900, 700)

    BG = "#0f1117"
    PANEL = "#161a24"
    FG = "#e8eaf0"
    DIM = "#8b90a3"
    ACC = "#3d7eff"
    root.configure(fg_color=BG)

    root.grid_columnconfigure(0, weight=1)
    root.grid_rowconfigure(1, weight=1)

    ctk.CTkLabel(
        root, text="Pocket Option Tournament AI",
        font=("TkDefaultFont", 24, "bold"), text_color=FG
    ).grid(row=0, column=0, sticky="w", padx=25, pady=(20, 5))

    ctk.CTkLabel(
        root,
        text="12-hour tournament scanner • multi-pair selection • ensemble analysis • adaptive tournament risk",
        text_color=DIM
    ).grid(row=0, column=0, sticky="w", padx=27, pady=(0, 18))

    panel = ctk.CTkScrollableFrame(root, fg_color=PANEL, corner_radius=16)
    panel.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 20))

    vars_ = {}

    def row(label, key, default, cast=str):
        r = len(vars_) + 1
        ctk.CTkLabel(panel, text=label, text_color=DIM).grid(
            row=r, column=0, sticky="w", padx=18, pady=7
        )
        v = ctk.StringVar(value=str(default))
        e = ctk.CTkEntry(panel, textvariable=v, width=250)
        e.grid(row=r, column=1, sticky="e", padx=18, pady=7)
        vars_[key] = (v, cast)

    panel.grid_columnconfigure(0, weight=1)
    panel.grid_columnconfigure(1, weight=1)

    row("Minimum payout %", "MIN_PAYOUT", TSET["MIN_PAYOUT"], int)
    row("Tournament duration (hours)", "TOURNAMENT_HOURS", TSET["TOURNAMENT_HOURS"], float)
    row("Minimum signal score", "MIN_SCORE", TSET["MIN_SCORE"], float)
    row("Strong signal score", "STRONG_SCORE", TSET["STRONG_SCORE"], float)
    row("Base stake $", "BASE_STAKE", TSET["BASE_STAKE"], float)
    row("Normal stake % of balance", "NORMAL_STAKE_PCT", TSET["NORMAL_STAKE_PCT"], float)
    row("Strong stake % of balance", "STRONG_STAKE_PCT", TSET["STRONG_STAKE_PCT"], float)
    row("Final-hour max stake %", "FINAL_STAKE_PCT", TSET["FINAL_STAKE_PCT"], float)
    row("Absolute max stake %", "MAX_STAKE_PCT", TSET["MAX_STAKE_PCT"], float)
    row("Loss cooldown seconds", "LOSS_COOLDOWN_SECONDS", TSET["LOSS_COOLDOWN_SECONDS"], int)
    row("Scan interval seconds", "SCAN_INTERVAL", TSET["SCAN_INTERVAL"], float)
    row("Allowed expiries (seconds)", "EXPIRIES", TSET["EXPIRIES"], str)

    paper = ctk.BooleanVar(value=TSET["PAPER_MODE"])
    leader = ctk.BooleanVar(value=TSET["USE_LEADERBOARD"])

    ctk.CTkCheckBox(
        panel, text="PAPER MODE — analyze without placing orders",
        variable=paper
    ).grid(row=20, column=0, columnspan=2, sticky="w", padx=18, pady=10)

    ctk.CTkCheckBox(
        panel, text="Use visible tournament leaderboard when available",
        variable=leader
    ).grid(row=21, column=0, columnspan=2, sticky="w", padx=18, pady=10)

    info = ctk.CTkLabel(
        panel,
        text=(
            "The bot reuses the existing Chrome/WebSocket/PO order layer. "
            "It scans assets exposed by the current PO page. "
            "Leaderboard parsing is best-effort because the tournament DOM can change."
        ),
        text_color=DIM, justify="left", wraplength=820
    )
    info.grid(row=22, column=0, columnspan=2, sticky="w", padx=18, pady=18)

    def start():
        try:
            for key, (var, cast) in vars_.items():
                value = cast(var.get())
                if key.endswith("_PCT"):
                    if not 0 < value <= 1:
                        raise ValueError(f"{key} must be between 0 and 1")
                TSET[key] = value
            TSET["PAPER_MODE"] = bool(paper.get())
            TSET["USE_LEADERBOARD"] = bool(leader.get())
        except Exception as e:
            info.configure(text=f"Configuration error: {e}")
            return
        root.destroy()

    ctk.CTkButton(
        panel, text="▶ START TOURNAMENT ENGINE",
        command=start, fg_color=ACC, height=45
    ).grid(row=23, column=0, columnspan=2, padx=18, pady=(12, 25), sticky="ew")

    root.mainloop()


if __name__ == "__main__":
    run_gui()
    asyncio.run(tournament_main())
