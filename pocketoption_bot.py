# Binary Options Automation — Collins_Obi
# https://github.com/Collins-Iceball/Binary-Options-Automation
import asyncio
import base64
import json
import operator
import os
import platform
import random
import sys
import time
from datetime import datetime, timedelta
import customtkinter as ctk
import requests
from selenium.common.exceptions import ElementNotInteractableException, NoSuchElementException, WebDriverException
from selenium.webdriver.common.by import By
from stock_indicators import indicators, Match, Quote
import undetected_chromedriver as uc

ops = {
    '>': operator.gt,
    '<': operator.lt,
}

# Binary Options Automation — Collins_Obi
# https://github.com/Collins-Iceball/Binary-Options-Automation
URL = 'https://pocketoption.com/en/cabinet/demo-quick-high-low/'
BASE_URL = ''  # no remote license server in this fork
LICENSE_URL = ''
ASSETS_URL = ''
CANDLES_URL = ''
LIMIT_TRADES_URL = ''
SERVER_STRATEGIES_URL = ''
PRODUCT_ID = ''
LICENSE_BUY_URL = ''

PERIOD = 1  # default is 1
ASSETS = {}
CANDLES = {}
ACTIONS = {}
LICENSE_VALID = True  # FIXED: Always valid
TRADES = 0
TRADING_ALLOWED = True
CURRENT_ASSET = None
FAVORITES_REANIMATED = False
SETTINGS = {}
MARTINGALE_LIST = []
MARTINGALE_LAST_ACTION_ENDS_AT = datetime.now()
LAST_ORDER_FAIL_AT = datetime(2000, 1, 1)
LAST_CANDLE_TS = {}
MARTINGALE_AMOUNT_SET = False
MARTINGALE_INITIAL = True
MARTINGALE_INDEX = 0
MULTIPLIER = 2.3
MIN_BET_AMOUNT = 1
BASE_BET = None
TRADE_BALANCE_BEFORE = 0.0
TRADE_BET_AMOUNT = 0.0
LAST_PROCESSED_TRADE = ""
MARTINGALE_MAP = {
    True: 'normal',
    False: 'disabled',
}
NUMBERS = {
    '0': '11',
    '1': '7',
    '2': '8',
    '3': '9',
    '4': '4',
    '5': '5',
    '6': '6',
    '7': '1',
    '8': '2',
    '9': '3',
}
INITIAL_DEPOSIT = None
LAST_BALANCE = 0.0
STOP_REASON = None   # set by check_deposit when TP/SL ends the run; main() reads it for a clean exit
_STOP_STREAK = 0     # consecutive ticks a TP/SL condition has held (one bad balance read can't end a run)
LAST_SAVED_URL = ""
SETTINGS_PATH = 'settings.txt'
SERVER_STRATEGIES = {}

# --- Quick Trade mode state ---
QT_SESSION_COUNT = 0
QT_SESSION_ACTIVE = False
QT_DIRECTION = None
QT_STEP = 0
QT_BASE_AMOUNT = None
QT_LAST_ACTION_ENDS_AT = datetime(2000, 1, 1)
QT_TRADE_BALANCE_BEFORE = 0.0
QT_TRADE_BET_AMOUNT = 0.0
QT_AMOUNT_SET = True
QT_TP_HIT = False
QT_SESSION_ASSET = None       # locked for the duration of one session so direction and order use the same asset
QT_SESSION_START_BALANCE = None
QT_TOTAL_PROFIT = 0.0
QT_RUN_FINISHED = False       # True once sessions target or TP is reached; main() breaks out on this
QT_MODE_CHECKED_ONCE = False  # only force-check the $/% toggle once per run, not every tick
QT_ASSET_SYNCED = False       # True once the bot has learned which chart is on screen at startup
QT_AUTO_CONTINUE = False      # set once the user picks 'A' - skips future Y/N/A prompts entirely


async def set_remote_debugging_allowed():
    os_platform = platform.platform().lower()
    if 'windows' not in os_platform:
        return  # use only for Windows
    import winreg
    key_path = r"SOFTWARE\Policies\Google\Chrome"
    value_name = "RemoteDebuggingAllowed"
    try:
        key = winreg.CreateKeyEx(
            winreg.HKEY_LOCAL_MACHINE,
            key_path,
            0,
            winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE | winreg.KEY_WOW64_64KEY
        )
        current_value, regtype = winreg.QueryValueEx(key, value_name)
        if current_value != 1:
            winreg.SetValueEx(key, value_name, 0, winreg.REG_DWORD, 1)
            log(f"Set RemoteDebuggingAllowed to 1 in regedit")
            winreg.CloseKey(key)
    except Exception as e:
        pass


async def get_driver():
    options = uc.ChromeOptions()
    options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
    options.set_capability('pageLoadStrategy', 'none')
    options.add_argument('--ignore-ssl-errors')
    options.add_argument('--ignore-certificate-errors')
    options.add_argument('--ignore-certificate-errors-spki-list')
    options.add_argument('--disable-build-check')
    options.add_argument('--restore-last-session')
    options.add_experimental_option('prefs', {
        'session.restore_on_startup': 1,
        'profile.exit_type': 'Normal',
    })
    # options.add_argument('--headless=new')

    username = os.environ.get('USER', os.environ.get('USERNAME'))
    os_platform = platform.platform().lower()
    if 'macos' in os_platform:
        path_default = fr'/Users/{username}/Library/Application Support/Google/Chrome/Trading Bot Profile'
    elif 'windows' in os_platform:
        path_default = fr'C:\Users\{username}\AppData\Local\Google\Chrome\User Data\Trading Bot Profile'
    elif 'linux' in os_platform:
        path_default = '~/.config/google-chrome/Trading Bot Profile'
    else:
        path_default = ''

    options.add_argument(fr'--user-data-dir={os.path.expanduser(path_default)}')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    driver = uc.Chrome(options=options, version_main=153, browser_executable_path='/usr/bin/google-chrome')
    return driver


async def get_email(driver):
    info_email = driver.find_element(By.CLASS_NAME, 'info__email')
    email = info_email.find_element(By.TAG_NAME, 'div').get_attribute('data-hd-show')
    if '@' not in email:
        return None
    return email


# ---- Colourful output (display only - never used in any comparison) ----
EMO_BUY = '🟩💹'
EMO_SELL = '🟥🈲'
EMO_DRAW = '🟠♊️'
EMO_LOSS = '♨️🫯'
EMO_WIN = '💲💱'
EMO_CLOCK = '🕓'
EMO_PROFIT = '🤑🤑'
EMO_LOSS_SESSION = '😞😞'


def dir_emo(action):
    """Emoji for a trade direction. Accepts call/put/buy/sell in any case."""
    a = str(action or '').strip().lower()
    if a in ('call', 'buy'):
        return EMO_BUY
    if a in ('put', 'sell'):
        return EMO_SELL
    return ''


def outcome_emo(outcome):
    """Emoji for a trade result WIN / LOSS / DRAW."""
    o = str(outcome or '').strip().upper()
    return {'WIN': EMO_WIN, 'LOSS': EMO_LOSS, 'DRAW': EMO_DRAW}.get(o, '')


def total_emo(total):
    """Session/run emoji decided by the RUNNING TOTAL, not by the last trade:
    a session that busted at max martingale stays red until the total is back above zero."""
    return EMO_PROFIT if total > 0 else EMO_LOSS_SESSION


def log(*args):
    print(f'{EMO_CLOCK} ' + datetime.now().strftime('%Y-%m-%d %H:%M:%S'), *args)


async def driver_alive(driver):
    """Cheap check that the Chrome session backing `driver` is still reachable.
    A dead session must never be silently read as a balance of 0.0 (which check_quick_trade
    would otherwise score as a LOSS against real trade history)."""
    try:
        _ = driver.current_url
        return True
    except WebDriverException as e:
        log(f'Chrome session appears to be dead/disconnected: {e}')
        return False
    except Exception as e:
        log(f'Chrome session health check failed: {e}')
        return False


async def websocket_log(driver):
    global ASSETS, PERIOD, CANDLES, ACTIONS, LICENSE_VALID, TRADES, CURRENT_ASSET, FAVORITES_REANIMATED, \
        TRADING_ALLOWED, SERVER_STRATEGIES

    try:
        _logs = driver.get_log('performance')
    except Exception:
        _logs = []
    for wsData in _logs:
        message = json.loads(wsData['message'])['message']
        response = message.get('params', {}).get('response', {})
        if response.get('opcode', 0) == 2:
            payload_str = base64.b64decode(response['payloadData']).decode('utf-8')
            data = json.loads(payload_str)

            if 'history' in data:
                if not CURRENT_ASSET:
                    CURRENT_ASSET = data['asset']
                    # print('Current asset:', CURRENT_ASSET)
                if PERIOD != data['period']:
                    # time is changed, refresh
                    PERIOD = data['period']
                    CANDLES = {}
                    ACTIONS = {}
                    FAVORITES_REANIMATED = False

                candles = list(reversed(data['candles']))  # timestamp open close high low
                # put history data to the candles
                for tstamp, value in data['history']:
                    tstamp = int(float(tstamp))
                    candle = [tstamp, value, value, value, value]
                    candle[2] = value  # set close all the time
                    if value > candle[3]:  # set high
                        candle[3] = value
                    if value < candle[4]:  # set low
                        candle[4] = value
                    if tstamp % PERIOD == 0:
                        if tstamp not in [c[0] for c in candles]:
                            candles.append([tstamp, value, value, value, value])

                CANDLES[data['asset']] = candles
                # log('Got', len(candles), 'candles for', data['asset'])

            try:
                asset = data[0][0]
                candles = CANDLES[asset]
                current_value = data[0][2]
                candles[-1][2] = current_value  # set close all the time
                if current_value > candles[-1][3]:  # set high
                    candles[-1][3] = current_value
                if current_value < candles[-1][4]:  # set low
                    candles[-1][4] = current_value
                tstamp = int(float(data[0][1]))
                if tstamp % PERIOD == 0:
                    if tstamp not in [c[0] for c in candles]:
                        # execute condition here
                        candles.append([tstamp, current_value, current_value, current_value, current_value])
                        # print('Candle appended for asset', asset, 'Len candles:', len(CANDLES[asset]))
            except:
                pass

    if not FAVORITES_REANIMATED:
        try:
            await reanimate_favorites(driver)
        except:
            pass

    # FIXED: Removed license check block - always allow trading
    if SETTINGS.get('BACKTEST') and not SETTINGS.get('BACKTEST_DONE'):
        try:
            email = await get_email(driver)
            if email:
                await backtest(email, timeframe=SETTINGS['BACKTEST_TIMEFRAME'][:-1])
                SETTINGS['BACKTEST_DONE'] = True
        except Exception as e:
            print(e)

    if SETTINGS.get('USE_SERVER_STRATEGIES') and not SERVER_STRATEGIES:
        response = requests.get(SERVER_STRATEGIES_URL)
        if response.status_code == 200:
            SERVER_STRATEGIES = response.json()
            log('Server strategies downloaded')


async def reanimate_favorites(driver):
    global CURRENT_ASSET, FAVORITES_REANIMATED
    asset_favorites_items = driver.find_elements(By.CLASS_NAME, 'assets-favorites-item')
    for item in asset_favorites_items:
        while True:
            # await asyncio.sleep(0.1)
            if 'assets-favorites-item--active' in item.get_attribute('class'):
                CURRENT_ASSET = item.get_attribute('data-id')
                # print('Current asset:', CURRENT_ASSET)
                break
            if 'assets-favorites-item--not-active' in item.get_attribute('class'):
                break  # just skip non-active assets
            try:
                item.click()
                FAVORITES_REANIMATED = True
            except ElementNotInteractableException:
                log(f"Asset {item.get_attribute('data-id')} is out of reach. Please close some favorite assets.")
                break


async def read_active_asset(driver):
    """The chart that is on screen right now, e.g. 'AUDUSD_otc' - the active tab in the favorites
    strip (same element switch_to_asset clicks). One cheap browser call. None if the strip isn't
    there. CURRENT_ASSET only ever changed when the BOT switched charts, so it went stale the
    moment a human clicked another chart."""
    try:
        return driver.execute_script(
            "var e = document.querySelector('.assets-favorites-item--active');"
            "return e ? e.getAttribute('data-id') : null;")
    except Exception:
        return None


async def switch_to_asset(driver, asset):
    global CURRENT_ASSET
    asset_favorites_items = driver.find_elements(By.CLASS_NAME, 'assets-favorites-item')
    for item in asset_favorites_items:
        if item.get_attribute('data-id') != asset:  # this condition is only for single asset
            continue
        while True:
            await asyncio.sleep(0.1)
            if 'assets-favorites-item--active' in item.get_attribute('class'):
                CURRENT_ASSET = asset
                # print('Current asset:', CURRENT_ASSET)
                return True
            try:
                item.click()
            except:
                log(f'Asset {asset} is out of reach. Please close some favorite assets.')
                return False
    if asset == CURRENT_ASSET:
        return True  # case when favorites are closed


async def check_payout(driver, asset):
    global ACTIONS
    try:
        payout = driver.find_element(By.CLASS_NAME, 'value__val-start').text
        if int(payout[1:-1]) >= SETTINGS['MIN_PAYOUT']:
            return True
        log(f'Payout {payout[1:]} is not allowed for asset {asset}')
        ACTIONS[asset] = datetime.now() + timedelta(minutes=1)
        return False
    except Exception:
        return True  # tournament / unreadable payout: proceed anyway

async def check_trades():
    # FIXED: Always allow trading - removed trade limit check
    return True


async def create_order(driver, action, asset, sstrategy=None, skip_cooldown=False):
    global ACTIONS, LAST_ORDER_FAIL_AT
    if not skip_cooldown and ACTIONS.get(asset) and ACTIONS[asset] + timedelta(seconds=PERIOD * 2) > datetime.now():
        return False
    try:
        switch = await switch_to_asset(driver, asset)
        if not switch:
            return False
        ok_payout = await check_payout(driver, asset)
        if not ok_payout:
            return False
        trading_allowed = await check_trades()
        if not trading_allowed:
            return False
        vice_versa = sstrategy['vice_versa'] if sstrategy else SETTINGS['VICE_VERSA']
        if vice_versa:
            action = 'call' if action == 'put' else 'put'
        clicked = False
        for cls in [f'btn-{action}', f'{action}-btn', f'btn_{action}']:
            try:
                driver.find_element(By.CLASS_NAME, cls).click()
                clicked = True
                break
            except Exception:
                continue
        if not clicked:
            js = """
            var a = arguments[0];
            var nodes = document.querySelectorAll('button, a, div, span');
            for (var i=0;i<nodes.length;i++){
                var el = nodes[i];
                var cls = (el.className||'').toString().toLowerCase();
                var txt = (el.textContent||'').trim().toLowerCase();
                if (cls.indexOf('btn-'+a)>=0 || cls.indexOf(a+'-btn')>=0 || txt===a || (a==='call'&&txt==='buy') || (a==='put'&&txt==='sell')){
                    el.click(); return true;
                }
            }
            return false;
            """
            clicked = driver.execute_script(js, action)
        if not clicked:
            raise Exception('no order button')
        ACTIONS[asset] = datetime.now()
        message = f'{dir_emo(action)} {action.capitalize()} on asset: {asset}'
        if sstrategy:
            message += f' made by server strategy with profit {sstrategy["profit"]}%'
        log(message)
    except Exception:
        now = datetime.now()
        if now - LAST_ORDER_FAIL_AT > timedelta(seconds=10):
            log("Can't create order (tournament layout?). Pausing 5s.")
        LAST_ORDER_FAIL_AT = now
        await asyncio.sleep(5)
        return False
    return True

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
    else:  # SMA
        results = indicators.get_sma(quotes, period)
        values = [r.sma for r in results if r.sma is not None]
    if len(values) < 2:
        raise ValueError("Not enough data points to calculate MA.")
    return values[-2], values[-1]


async def moving_averages_cross(candles, sstrategy=None):
    fast_ma = sstrategy['fast_ma'] if sstrategy else SETTINGS['FAST_MA']
    fast_ma_type = sstrategy['fast_ma_type'] if sstrategy else SETTINGS.get('FAST_MA_TYPE', 'SMA')
    slow_ma = sstrategy['slow_ma'] if sstrategy else SETTINGS['SLOW_MA']
    slow_ma_type = sstrategy['slow_ma_type'] if sstrategy else SETTINGS.get('SLOW_MA_TYPE', 'SMA')

    if fast_ma >= slow_ma:
        log("Moving averages 'fast' can't be bigger than 'slow'")
        return None
    try:
        quotes = candles_to_quotes(candles)
        fast_prev, fast_curr = get_ma_last_two(quotes, fast_ma_type, fast_ma)
        slow_prev, slow_curr = get_ma_last_two(quotes, slow_ma_type, slow_ma)
        if fast_prev < slow_prev and fast_curr > slow_curr:
            return 'call'
        elif fast_prev > slow_prev and fast_curr < slow_curr:
            return 'put'
    except Exception as e:
        log(e)
    return None


async def quick_trade_ma_direction(candles):
    """Current fast-vs-slow MA position (not a cross event) -> call/put, used once per Quick Trade session."""
    fast_ma = int(SETTINGS.get('QT_FAST_MA', 5))
    slow_ma = int(SETTINGS.get('QT_SLOW_MA', 10))
    ma_type = SETTINGS.get('QT_MA_TYPE', 'SMA')
    if fast_ma >= slow_ma:
        log("Quick Trade MA: fast period must be less than slow period")
        return None
    try:
        quotes = candles_to_quotes(candles)
        _, fast_curr = get_ma_last_two(quotes, ma_type, fast_ma)
        _, slow_curr = get_ma_last_two(quotes, ma_type, slow_ma)
        if fast_curr is None or slow_curr is None:
            return None
        if fast_curr > slow_curr:
            return 'call'
        elif fast_curr < slow_curr:
            return 'put'
    except Exception as e:
        log(e)
    return None


async def set_quick_trade_expiry(driver):
    """Force the expiry field to SETTINGS['QT_EXPIRY_SECONDS'] (default 5) and verify it
    actually landed. Returns the confirmed expiry in seconds, or None on failure.
    Timing (QT_LAST_ACTION_ENDS_AT) must be derived from this confirmed value - assuming
    a fixed number regardless of what's really on screen causes the bot to check results
    (and re-fire/close a session) before a longer trade has actually closed."""
    target_seconds = int(SETTINGS.get('QT_EXPIRY_SECONDS', 5))
    target_seconds = max(5, target_seconds)  # platform floor - Quick Trade spec's default is 5s
    target_str = f'00:00:{target_seconds:02d}' if target_seconds < 60 else \
        f'00:{target_seconds // 60:02d}:{target_seconds % 60:02d}'
    try:
        expiry_css = '#put-call-buttons-chart-1 > div > div.blocks-wrap > div.block.block--expiration-inputs > div.block__control.control > div.control__value.value.value--several-items'
        current = driver.find_element(By.CSS_SELECTOR, value=expiry_css).text.strip()
        if current == target_str:
            return target_seconds
        mm = target_seconds // 60
        ss = target_seconds % 60
        js_set = f"""
        var els = document.querySelectorAll('.block--expiration-inputs input');
        if (els.length >= 3) {{
            var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
            setter.call(els[0], '00'); els[0].dispatchEvent(new Event('input', {{bubbles: true}}));
            setter.call(els[1], '{mm:02d}'); els[1].dispatchEvent(new Event('input', {{bubbles: true}}));
            setter.call(els[2], '{ss:02d}'); els[2].dispatchEvent(new Event('input', {{bubbles: true}}));
        }}
        """
        driver.execute_script(js_set)
        await hand_delay()
        # Verify what's actually on screen now - don't just trust the injection worked.
        confirmed_text = driver.find_element(By.CSS_SELECTOR, value=expiry_css).text.strip()
        if confirmed_text != target_str:
            log(f'Quick Trade: expiry shows {confirmed_text} after trying to set {target_str}.')
            try:
                h, m, s = confirmed_text.split(':')
                return int(h) * 3600 + int(m) * 60 + int(s)  # use whatever is REALLY on screen for timing
            except Exception:
                return None
        return target_seconds
    except Exception as e:
        log(f'Could not set Quick Trade expiry: {e}')
        return None


async def get_rsi(candles, sstrategy=None):
    period = sstrategy['rsi_period'] if sstrategy else SETTINGS['RSI_PERIOD']
    quotes = candles_to_quotes(candles)
    results = indicators.get_rsi(quotes, period)
    values = [r.rsi for r in results if r.rsi is not None]
    if not values:
        raise ValueError("Not enough data to calculate RSI.")
    return values


def get_rsi_lower(rsi_upper):
    return 100 - rsi_upper


def get_rsi_put_sign(call_sign):
    return '<' if call_sign == '>' else '>'


async def rsi_strategy(candles, action, sstrategy=None):
    rsi = await get_rsi(candles)
    rsi_upper = sstrategy['rsi_upper'] if sstrategy else SETTINGS.get('RSI_UPPER')
    rsi_lower = get_rsi_lower(rsi_upper)
    call_sign = sstrategy['rsi_call_sign'] if sstrategy else SETTINGS.get('RSI_CALL_SIGN')
    put_sign = get_rsi_put_sign(call_sign)

    if action == 'call' and ops[call_sign](rsi[-1], rsi_upper):
        return 'call'
    elif action == 'put' and ops[put_sign](rsi[-1], rsi_lower):
        return 'put'
    return None


async def supertrend_strategy(candles, action, sstrategy=None):
    period = sstrategy.get('supertrend_period') if sstrategy else SETTINGS.get('SUPERTREND_PERIOD', 10)
    quotes = candles_to_quotes(candles)
    results = indicators.get_super_trend(quotes, period)
    last = next((r for r in reversed(results) if r.upper_band is not None or r.lower_band is not None), None)
    if last is None:
        return None
    if action == 'call' and last.lower_band is not None:
        return 'call'
    elif action == 'put' and last.upper_band is not None:
        return 'put'
    return None


async def get_price_action(candles, action):
    if action == 'call':
        if candles[-1][2] > candles[-3][2]:
            return action
    elif action == 'put':
        if candles[-1][2] < candles[-3][2]:
            return action
    return None


async def set_amount_icon(driver):
    amount_style = driver.find_element(By.CSS_SELECTOR,
                                       value='#put-call-buttons-chart-1 > div > div.blocks-wrap > div.block.block--bet-amount > div.block__control.control > div.control-buttons__wrapper > div > a')

    def is_usd_mode():
        try:
            amount_style.find_element(By.CLASS_NAME, value='currency-icon--usd')
            return True
        except NoSuchElementException:
            return False

    async def wait_for_usd_mode(timeout=2.0, poll_interval=0.25):
        # Poll instead of a single blind sleep - the UI may take longer than
        # one hand_delay() to actually re-render after the click.
        waited = 0.0
        while waited < timeout:
            if is_usd_mode():
                return True
            await asyncio.sleep(poll_interval)
            waited += poll_interval
        return False

    if is_usd_mode():
        return  # already in fixed-amount ($) mode, nothing to do

    # Not in $ mode (i.e. in % mode) - click to switch, then VERIFY it actually changed
    amount_style.click()

    if await wait_for_usd_mode():
        log('Amount mode: switched from % to $ successfully.')
    else:
        # Click didn't land as expected - try once more before giving up
        amount_style.click()
        if await wait_for_usd_mode():
            log('Amount mode: switched from % to $ on second attempt.')
        else:
            log('WARNING: Could not confirm $ (fixed-amount) mode is active - bot may still be in % mode. Check the trade type toggle on screen.')


async def set_estimation_icon(driver):
    time_style = driver.find_element(By.CSS_SELECTOR,
                                     value='#put-call-buttons-chart-1 > div > div.blocks-wrap > div.block.block--expiration-inputs > div.block__control.control > div.control-buttons__wrapper > div > a > div > div > svg')
    if 'exp-mode-2.svg' in time_style.get_attribute('data-src'):  # should be 'exp-mode-2.svg'
        time_style.click()  # switch time style


async def get_estimation(driver):
    estimation = driver.find_element(By.CSS_SELECTOR,
                                     value='#put-call-buttons-chart-1 > div > div.blocks-wrap > div.block.block--expiration-inputs > div.block__control.control > div.control__value.value.value--several-items')
    est = datetime.strptime(estimation.text, '%H:%M:%S')
    return (est.hour * 3600) + (est.minute * 60) + est.second


async def hand_delay():
    await asyncio.sleep(random.choice([0.2, 0.3, 0.4, 0.5, 0.6]))


async def get_balance(driver):
    return await get_balance_robust(driver)


async def get_balance_robust(driver):
    try:
        # Try standard class first
        el = driver.find_element(By.CSS_SELECTOR, '.balance-info-block__balance')
        text = el.text.replace(',', '').replace('$', '').replace('€', '').replace('£', '').strip()
        return float(text)
    except:
        pass
    
    # Fallback: JS search for currency pattern in header
    try:
        js = """
        let header = document.querySelector('header') || document.body;
        let text = header.innerText;
        // Match patterns like $1,234.56 or 1234.56 USD
        let match = text.match(/([$€£])?\\s*([\\d,]+\\.?\\d*)/);
        if(match) return match[2].replace(',', '');
        return null;
        """
        val = driver.execute_script(js)
        if val: return float(val)
    except:
        pass
    return 0.0

async def check_indicators(driver):
    global MARTINGALE_LAST_ACTION_ENDS_AT, MARTINGALE_AMOUNT_SET, MARTINGALE_INITIAL, LAST_CANDLE_TS, TRADE_BALANCE_BEFORE, TRADE_BET_AMOUNT, MARTINGALE_INDEX, BASE_BET
    MARTINGALE_LIST = SETTINGS.get('MARTINGALE_LIST')
    use_list = bool(SETTINGS.get('MARTINGALE_ENABLED'))
    multiplier = float(SETTINGS.get('MULTIPLIER', 2.3))
    base = '#modal-root > div > div > div > div > div > div:nth-child(2) > div.panel-collapse__body > div > div > div:nth-child(%s) > div'
    amount_css = '#put-call-buttons-chart-1 > div > div.blocks-wrap > div.block.block--bet-amount > div.block__control.control > div.control__value.value.value--several-items > div > input[type=text]'

    # --- One-time init ---
    if MARTINGALE_INITIAL:
        if use_list:
            try:
                await set_amount_icon(driver)
                amount = driver.find_element(By.CSS_SELECTOR, value=amount_css)
                amount_value = int(float((amount.get_attribute('value').replace(',', ''))))
                if amount_value != MARTINGALE_LIST[0]:
                    amount.click()
                    for number in str(MARTINGALE_LIST[0]):
                        driver.find_element(By.CSS_SELECTOR, value=base % NUMBERS[number]).click()
                        await hand_delay()
                MARTINGALE_INITIAL = False
                MARTINGALE_AMOUNT_SET = True
            except Exception:
                return
            return
        else:
            try:
                await set_amount_icon(driver)
                amount = driver.find_element(By.CSS_SELECTOR, value=amount_css)
                field_value = float((amount.get_attribute('value').replace(',', '') or 0))
            except Exception:
                field_value = 0.0
            _min_bet_init = float(SETTINGS.get('MIN_BET_AMOUNT', 1))
            BASE_BET = _min_bet_init if _min_bet_init > 0 else (field_value if field_value > 0 else 1.0)
            # Push BASE_BET onto the actual page — reading it into memory isn't enough,
            # the field itself must show the real starting amount before the first trade fires.
            try:
                amount = driver.find_element(By.CSS_SELECTOR, value=amount_css)
                current_field_value = float((amount.get_attribute('value').replace(',', '') or 0))
                if round(current_field_value, 2) != round(BASE_BET, 2):
                    amount.click()
                    await hand_delay()
                    target_str = str(int(BASE_BET)) if BASE_BET == int(BASE_BET) else str(BASE_BET)
                    for number in target_str.replace('.', ''):
                        if number in NUMBERS:
                            driver.find_element(By.CSS_SELECTOR, value=base % NUMBERS[number]).click()
                            await hand_delay()
            except Exception as e:
                log(f'Could not write starting bet to page, will self-correct after first trade: {e}')
            log(f'--- Multiplier Martingale armed: base ${BASE_BET} x{multiplier} ---')
            MARTINGALE_INITIAL = False
            MARTINGALE_AMOUNT_SET = True
            return

    # --- Wait for the previous trade to finish ---
    if MARTINGALE_LAST_ACTION_ENDS_AT + timedelta(seconds=4) > datetime.now():
        return

    # --- Result handling + next bet sizing (BOTH modes) ---
    if not MARTINGALE_AMOUNT_SET:
        balance_after = await get_balance(driver)
        print()
        log("--- MARTINGALE (Balance Delta) ---")
        log(f"Balance before: {TRADE_BALANCE_BEFORE} | after: {balance_after} | bet: {TRADE_BET_AMOUNT}")
        outcome = None
        if balance_after is None or TRADE_BALANCE_BEFORE <= 0 or TRADE_BET_AMOUNT <= 0:
            log("Missing balance data. Keeping current bet.")
        else:
            delta = balance_after - TRADE_BALANCE_BEFORE
            log(f"Balance delta: {delta:+.2f}")
            if delta > TRADE_BET_AMOUNT * 0.5:
                outcome = 'WIN'
            elif delta < -TRADE_BET_AMOUNT * 0.5:
                outcome = 'LOSS'
            else:
                outcome = 'DRAW'
            log(f"Outcome: {outcome_emo(outcome)} {outcome}")

        if use_list:
            if outcome == 'WIN':
                log(f"RESULT: {EMO_WIN} WIN. Resetting Martingale to base bet.")
                MARTINGALE_INDEX = 0
            elif outcome == 'LOSS':
                log(f"RESULT: {EMO_LOSS} LOSS. Incrementing Martingale step.")
                MARTINGALE_INDEX += 1
                if MARTINGALE_INDEX >= len(MARTINGALE_LIST):
                    log("Max Martingale steps reached. Resetting to base bet.")
                    MARTINGALE_INDEX = 0
            else:
                log(f"RESULT: {EMO_DRAW} DRAW. No loss -> keeping the SAME bet.")
            next_amount = MARTINGALE_LIST[MARTINGALE_INDEX]
            min_bet = float(SETTINGS.get('MIN_BET_AMOUNT', 1))
            if next_amount < min_bet:
                next_amount = min_bet
        else:
            if BASE_BET is None or BASE_BET <= 0:
                BASE_BET = TRADE_BET_AMOUNT if TRADE_BET_AMOUNT and TRADE_BET_AMOUNT > 0 else 1.0
            if outcome == 'WIN':
                next_amount = BASE_BET
                log(f"RESULT: {EMO_WIN} WIN. Resetting to base bet ${BASE_BET}.")
            elif outcome == 'LOSS':
                next_amount = round((TRADE_BET_AMOUNT or BASE_BET) * multiplier, 2)
                log(f"RESULT: {EMO_LOSS} LOSS. Next bet = previous x{multiplier} = ${next_amount}.")
            else:
                next_amount = TRADE_BET_AMOUNT if TRADE_BET_AMOUNT and TRADE_BET_AMOUNT > 0 else BASE_BET
                log(f"RESULT: {EMO_DRAW} DRAW. Keeping the SAME bet ${next_amount}.")

        log(f"Setting next bet to: ${next_amount}")
        js_set_amount = f"""
        var input = document.querySelector('#put-call-buttons-chart-1 input[type="text"]');
        if(!input) input = document.querySelector('.block--bet-amount input');
        if(input) {{
            var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
            setter.call(input, '{next_amount}');
            input.dispatchEvent(new Event('input', {{ bubbles: true }}));
            input.dispatchEvent(new Event('change', {{ bubbles: true }}));
        }}
        """
        driver.execute_script(js_set_amount)
        try:
            amount_el = driver.find_element(By.CSS_SELECTOR, value='#put-call-buttons-chart-1 input[type=text]')
            log(f"Amount field now shows: {amount_el.get_attribute('value')}")
        except Exception:
            log("Could not read amount field back")
        MARTINGALE_AMOUNT_SET = True
        print(f"----------------------------------\n")

    action = None
    sstrategy = None
    for asset, candles in CANDLES.items():
        if SETTINGS.get('BEGINNING_CANDLE_ORDER'):
            current_ts = candles[-1][0] if candles else None
            if not current_ts or current_ts == LAST_CANDLE_TS.get(asset):
                continue
            LAST_CANDLE_TS[asset] = current_ts
        if SETTINGS.get('USE_SERVER_STRATEGIES') and \
                asset in SERVER_STRATEGIES and \
                len(SERVER_STRATEGIES[asset]) > 0 and \
                PERIOD == 60:  # TODO: update for timeframe later
            for sstrategy in SERVER_STRATEGIES[asset]:
                action = await check_strategies(candles, sstrategy=sstrategy)
                if action:  # if action found, exit for loop
                    continue
        else:  # usual strategy set in web interface
            action = await check_strategies(candles, sstrategy=None)
        if not action:
            continue
        _bal_before_trade = await get_balance(driver)
        order_created = await create_order(driver, action, asset, sstrategy=sstrategy)
        if order_created:
            try:
                await set_estimation_icon(driver)  # actually, it's just a check
                seconds = await get_estimation(driver)
            except Exception:
                seconds = PERIOD
            MARTINGALE_LAST_ACTION_ENDS_AT = datetime.now() + timedelta(seconds=seconds)
            TRADE_BALANCE_BEFORE = _bal_before_trade if _bal_before_trade is not None else 0.0
            if use_list:
                TRADE_BET_AMOUNT = MARTINGALE_LIST[MARTINGALE_INDEX]
            else:
                try:
                    amount_el = driver.find_element(By.CSS_SELECTOR, value=amount_css)
                    TRADE_BET_AMOUNT = float((amount_el.get_attribute('value').replace(',', '') or 0))
                except Exception:
                    pass
                if not TRADE_BET_AMOUNT or TRADE_BET_AMOUNT <= 0:
                    TRADE_BET_AMOUNT = BASE_BET or 1.0
            MARTINGALE_AMOUNT_SET = False
            await asyncio.sleep(1)
            return


async def get_balance_settled(driver, balance_before, bet_amount, timeout=3.0, poll_interval=0.3):
    """Poll the balance after a trade's expiry instead of trusting a single snapshot.
    Pocket Option doesn't credit/debit the balance the instant a candle closes - there's
    a short settlement lag. Reading too early returns the pre-trade balance and gets
    misread as a DRAW (or the wrong trade's result gets attributed to the next one)."""
    waited = 0.0
    last_value = None
    while waited < timeout:
        val = await get_balance(driver)
        last_value = val
        if val is not None and val > 0 and abs(val - balance_before) > 0.005:
            return val  # balance actually moved - trade has settled
        await asyncio.sleep(poll_interval)
        waited += poll_interval
    return last_value  # settlement never showed up in time - caller will treat as unreadable if unchanged


async def check_quick_trade(driver):
    """Quick Trade mode: MA-confirmed direction per session, 5s fixed expiry,
    instant re-fire martingale on loss (no wait), win closes the session.
    Runs QT_SESSIONS sessions (min 10) then stops - unless take profit is
    enabled and hit first, in which case it can stop before 10 sessions."""
    global QT_SESSION_COUNT, QT_SESSION_ACTIVE, QT_DIRECTION, QT_STEP, QT_BASE_AMOUNT, \
        QT_LAST_ACTION_ENDS_AT, QT_TRADE_BALANCE_BEFORE, QT_TRADE_BET_AMOUNT, QT_AMOUNT_SET, QT_TP_HIT, \
        QT_SESSION_ASSET, QT_SESSION_START_BALANCE, QT_TOTAL_PROFIT, QT_RUN_FINISHED, QT_MODE_CHECKED_ONCE, \
        QT_AUTO_CONTINUE, CURRENT_ASSET, QT_ASSET_SYNCED

    if QT_AUTO_CONTINUE:
        total_sessions = 5  # auto-continue always runs shorter cycles, regardless of the saved GUI setting
    else:
        total_sessions = int(SETTINGS.get('QT_SESSIONS', 10))
        if total_sessions < 10:
            total_sessions = 10
    tp_enabled = bool(SETTINGS.get('QT_TAKE_PROFIT_ENABLED'))

    if QT_RUN_FINISHED:
        return  # main() will break out and handle the Y/N prompt

    if QT_SESSION_COUNT >= total_sessions:
        log(f'Quick Trade: target of {total_sessions} sessions reached. Total profit: {QT_TOTAL_PROFIT:+.2f}')
        QT_RUN_FINISHED = True
        return

    if QT_TP_HIT:
        # Take profit can end the run even below 10 sessions - that's the point of TP.
        log(f'Quick Trade: stopping on take profit after {QT_SESSION_COUNT} session(s). Total profit: {QT_TOTAL_PROFIT:+.2f}')
        QT_RUN_FINISHED = True
        return

    if QT_BASE_AMOUNT is None:
        QT_BASE_AMOUNT = float(SETTINGS.get('QT_TRADE_AMOUNT', 1))

    # Only force-check the $/% amount toggle once at the start of the run, not every
    # tick - on some account layouts (e.g. tournaments) the detection can't confirm
    # the mode even though trades are correctly landing in $ amounts, and re-clicking
    # it every tick risks eventually flipping it the wrong way for no reason.
    if not QT_MODE_CHECKED_ONCE:
        try:
            await set_amount_icon(driver)
        except Exception as e:
            log(f'Quick Trade: could not check $/% amount mode at startup: {e}')
        QT_MODE_CHECKED_ONCE = True

    if QT_LAST_ACTION_ENDS_AT > datetime.now():
        return

    if not QT_AMOUNT_SET:
        balance_after = await get_balance_settled(driver, QT_TRADE_BALANCE_BEFORE, QT_TRADE_BET_AMOUNT)
        outcome = None
        if balance_after is None or balance_after <= 0 or QT_TRADE_BALANCE_BEFORE <= 0 or QT_TRADE_BET_AMOUNT <= 0:
            log('Quick Trade: missing/invalid balance reading, will retry next tick rather than score a result.')
            return
        else:
            delta = balance_after - QT_TRADE_BALANCE_BEFORE
            # A loss is always exactly -bet. A win is +bet*payout% (e.g. +0.85 on a
            # $1 bet at 85% payout) - NOT necessarily more than half the bet, so a
            # fixed 0.5x threshold misreads low-payout wins as draws. Use a tight
            # tolerance around the two real expected outcomes instead of a guess.
            expected_loss = -QT_TRADE_BET_AMOUNT
            tolerance = max(QT_TRADE_BET_AMOUNT * 0.1, 0.02)
            if abs(delta - expected_loss) <= tolerance:
                outcome = 'LOSS'
            elif delta > tolerance:
                outcome = 'WIN'
            else:
                outcome = 'DRAW'
            log(f'Quick Trade result: {outcome_emo(outcome)} {outcome} (delta {delta:+.2f}, step {QT_STEP})')

        if outcome == 'WIN':
            session_profit = balance_after - QT_SESSION_START_BALANCE if QT_SESSION_START_BALANCE is not None else delta
            QT_TOTAL_PROFIT += session_profit
            QT_SESSION_COUNT += 1
            log(f'Quick Trade: session {QT_SESSION_COUNT}/{total_sessions} closed on {EMO_WIN} WIN. '
                f'Session profit: {session_profit:+.2f} | Total profit so far: {QT_TOTAL_PROFIT:+.2f} {total_emo(QT_TOTAL_PROFIT)}')
            QT_SESSION_ACTIVE = False
            QT_STEP = 0
            QT_DIRECTION = None
            QT_SESSION_ASSET = None
            QT_SESSION_START_BALANCE = None
            if tp_enabled:
                qt_check_take_profit(driver, balance_after)
            QT_AMOUNT_SET = True
            return
        elif outcome == 'LOSS':
            max_steps = int(SETTINGS.get('QT_MAX_STEPS', 7))
            if QT_STEP + 1 >= max_steps:
                session_profit = balance_after - QT_SESSION_START_BALANCE if QT_SESSION_START_BALANCE is not None else delta
                QT_TOTAL_PROFIT += session_profit
                log(f'Quick Trade: martingale cap ({max_steps}) reached this session {EMO_LOSS}. Resetting without counting a win. '
                    f'Session result: {session_profit:+.2f} | Total profit so far: {QT_TOTAL_PROFIT:+.2f} {total_emo(QT_TOTAL_PROFIT)}')
                QT_SESSION_ACTIVE = False
                QT_STEP = 0
                QT_DIRECTION = None
                QT_SESSION_ASSET = None
                QT_SESSION_START_BALANCE = None
                QT_AMOUNT_SET = True
                return
            QT_STEP += 1
        else:
            pass  # DRAW: QT_STEP untouched on purpose - same amount re-fires, no martingale applied
        QT_AMOUNT_SET = True

    # ---- know which chart is REALLY on screen ----
    screen_asset = await read_active_asset(driver)
    if screen_asset:
        if not QT_ASSET_SYNCED:
            CURRENT_ASSET = screen_asset  # first look: just learn where we are, nothing to follow yet
            QT_ASSET_SYNCED = True
        elif screen_asset != CURRENT_ASSET:
            # The bot updates CURRENT_ASSET every time IT switches chart, so a different chart on
            # screen means the user switched it. Follow them instead of yanking the chart back.
            CURRENT_ASSET = screen_asset
            if QT_SESSION_ACTIVE and QT_SESSION_ASSET and screen_asset != QT_SESSION_ASSET:
                if QT_STEP == 0:
                    log(f'Quick Trade: you switched to {screen_asset} (was {QT_SESSION_ASSET}). Re-picking the session on the chart you are in.')
                    QT_SESSION_ACTIVE = False
                    QT_SESSION_ASSET = None
                    QT_DIRECTION = None
                else:
                    # mid-martingale: keep the step (the loss still has to be recovered) but trade the chart you moved to
                    log(f'Quick Trade: you switched to {screen_asset} (was {QT_SESSION_ASSET}). Continuing the martingale (step {QT_STEP}) there.')
                    QT_SESSION_ASSET = screen_asset
                    QT_DIRECTION = None
            if screen_asset not in CANDLES:
                # brand-new chart: its candle history is still arriving. Give it a second instead of
                # letting the scan below jump to some other asset and drag the chart away from you.
                await asyncio.sleep(1)
                return

    if not QT_SESSION_ACTIVE:
        direction = None
        chosen_asset = None
        # try the chart the user is on first, then the rest in their usual order (sort is stable)
        _on_screen = screen_asset or CURRENT_ASSET
        for asset, candles in sorted(CANDLES.items(), key=lambda kv: kv[0] != _on_screen):
            direction = await quick_trade_ma_direction(candles)
            if direction:
                chosen_asset = asset
                break
        if not direction:
            return
        QT_DIRECTION = direction
        QT_SESSION_ASSET = chosen_asset  # lock this asset for the whole session - direction and order must agree
        QT_SESSION_ACTIVE = True
        QT_STEP = 0
        QT_SESSION_START_BALANCE = await get_balance(driver)

    asset = QT_SESSION_ASSET
    if not asset or asset not in CANDLES:
        return
    if QT_DIRECTION is None:
        # only after following the user mid-martingale: read the new chart's MA before firing
        QT_DIRECTION = await quick_trade_ma_direction(CANDLES[asset])
        if QT_DIRECTION is None:
            return

    min_payout = SETTINGS.get('QT_MIN_PAYOUT')
    if min_payout not in (None, ''):
        try:
            # The payout box shows the chart on screen. Make sure that IS the asset we are about to
            # trade, otherwise we'd judge one chart's payout and then trade another one.
            if screen_asset and screen_asset != asset:
                if not await switch_to_asset(driver, asset):
                    log(f'Quick Trade: could not switch to {asset}, waiting.')
                    await asyncio.sleep(1)
                    return
            payout_text = driver.find_element(By.CLASS_NAME, 'value__val-start').text
            current_payout = int(payout_text[1:-1])
            if current_payout < int(min_payout):
                log(f'Quick Trade: payout {current_payout}% below minimum {min_payout}% for {asset}, waiting.')
                await asyncio.sleep(1)
                return
        except Exception:
            pass  # unreadable payout (tournament layout etc.) - proceed anyway, same as Normal Trading

    multiplier = float(SETTINGS.get('QT_MARTINGALE', 2.1))
    if QT_STEP == 0:
        next_amount = QT_BASE_AMOUNT
    else:
        next_amount = round(QT_BASE_AMOUNT * (multiplier ** QT_STEP), 2)

    try:
        js_set_amount = f"""
        var input = document.querySelector('#put-call-buttons-chart-1 input[type="text"]');
        if(!input) input = document.querySelector('.block--bet-amount input');
        if(input) {{
            var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
            setter.call(input, '{next_amount}');
            input.dispatchEvent(new Event('input', {{ bubbles: true }}));
            input.dispatchEvent(new Event('change', {{ bubbles: true }}));
        }}
        """
        driver.execute_script(js_set_amount)
        await hand_delay()
        # Verify it actually landed before trusting it - a silent no-op here previously
        # caused a wrong stake (and a bogus WIN/LOSS/DRAW read) to slip through.
        amount_field = driver.find_element(By.CSS_SELECTOR, value='#put-call-buttons-chart-1 input[type=text]')
        confirmed_value = float((amount_field.get_attribute('value') or '0').replace(',', ''))
        if round(confirmed_value, 2) != round(next_amount, 2):
            log(f'Quick Trade: amount field shows {confirmed_value} after trying to set {next_amount}, aborting this re-fire attempt.')
            return
    except Exception as e:
        log(f'Quick Trade: could not set amount, aborting this re-fire attempt: {e}')
        return  # don't limp on to expiry/order calls against a connection that just failed

    confirmed_expiry_seconds = await set_quick_trade_expiry(driver)
    if confirmed_expiry_seconds is None:
        log('Quick Trade: could not confirm expiry, aborting this re-fire attempt.')
        return

    _bal_before_trade = await get_balance(driver)
    order_created = await create_order(driver, QT_DIRECTION, asset, skip_cooldown=True)
    if order_created:
        # Wait for the CONFIRMED expiry (whatever is really on screen) plus a short
        # settlement buffer - Pocket Option doesn't update the displayed balance the
        # instant the candle closes. Previously this was hardcoded to 5.75s regardless
        # of actual expiry, so any expiry above ~5-6s meant the bot checked the result
        # (and could re-fire or close a session) before the trade had actually closed.
        QT_LAST_ACTION_ENDS_AT = datetime.now() + timedelta(seconds=confirmed_expiry_seconds + 0.75)
        QT_TRADE_BALANCE_BEFORE = _bal_before_trade if _bal_before_trade is not None else 0.0
        QT_TRADE_BET_AMOUNT = next_amount
        QT_AMOUNT_SET = False
    else:
        log('Quick Trade: order was not created, will retry next tick.')
        await asyncio.sleep(1)  # guard against a fast-failing path spinning at full speed


def qt_check_take_profit(driver, balance_now=None):
    """Optional hard stop for Quick Trade once a TP figure (if configured) is reached.
    Target = balance at the start of the run (INITIAL_DEPOSIT) + the TP value - the TP value is
    never compared to the balance directly. balance_now is the settled balance read right after
    the session's result was scored. (This used to read LAST_BALANCE, which nothing ever updated,
    so Quick Trade take profit could never fire.)"""
    global QT_TP_HIT
    if not SETTINGS.get('QT_TAKE_PROFIT_ENABLED'):
        return
    if INITIAL_DEPOSIT is None:
        return
    tp = SETTINGS.get('QT_TAKE_PROFIT')
    if tp in (None, ''):
        return
    try:
        tp = float(tp)
    except Exception:
        return
    current = balance_now if balance_now else LAST_BALANCE
    if current and current > INITIAL_DEPOSIT + tp:
        log(f'Quick Trade: take profit reached. Initial: {INITIAL_DEPOSIT}, current: {current} ({current - INITIAL_DEPOSIT:+.2f})')
        QT_TP_HIT = True


async def check_deposit(driver):
    global INITIAL_DEPOSIT, TRADING_ALLOWED, STOP_REASON, _STOP_STREAK
    deposit = await get_balance_robust(driver)
    if INITIAL_DEPOSIT is None:
        if deposit <= 0:
            await asyncio.sleep(2)
            return
        INITIAL_DEPOSIT = deposit
        _STOP_STREAK = 0
        log(f'Initial deposit: {INITIAL_DEPOSIT}')
        await asyncio.sleep(1)
        return
    if deposit <= 0:
        return  # unreadable balance this tick (get_balance_robust returns 0.0 on failure) - never act on it
    quick = SETTINGS.get('TRADING_MODE', 'normal') == 'quick'
    # Targets are measured from the balance at the start of the run (INITIAL_DEPOSIT):
    #   take profit = INITIAL_DEPOSIT + TP value,  stop loss = INITIAL_DEPOSIT - SL value.
    # Quick mode has its own TP, checked in check_quick_trade right after a session's result is
    # scored (so no result is lost), so the Normal-mode TP box only applies to Normal mode.
    hit = None
    if not quick and SETTINGS.get('TAKE_PROFIT_ENABLED'):
        if deposit > INITIAL_DEPOSIT + SETTINGS.get('TAKE_PROFIT', 100):
            hit = 'take profit'
    if SETTINGS.get('STOP_LOSS_ENABLED'):
        if deposit < INITIAL_DEPOSIT - SETTINGS.get('STOP_LOSS', 50):
            hit = 'stop loss'
    if not hit:
        _STOP_STREAK = 0
        return
    _STOP_STREAK += 1
    if _STOP_STREAK < 2:
        return  # must hold on two consecutive ticks, so a single misread can't end the run
    label = 'Take profit' if hit == 'take profit' else 'Stop loss'
    log(f'{label} reached, trading stopped. Initial deposit: {INITIAL_DEPOSIT}, '
        f'current deposit: {deposit} ({deposit - INITIAL_DEPOSIT:+.2f})')
    STOP_REASON = hit
    TRADING_ALLOWED = False


async def psar_strategy(candles, sstrategy=None):
    quotes = candles_to_quotes(candles)
    results = indicators.get_parabolic_sar(quotes)
    last = results[-1] if results else None
    if last is None or not last.is_reversal:
        return None
    close = candles[-1][2]
    if last.sar < close:
        return 'call'
    elif last.sar > close:
        return 'put'
    return None


async def vortex_strategy(candles, sstrategy=None):
    period = sstrategy.get('vortex_period') if sstrategy else SETTINGS.get('VORTEX_PERIOD', 14)
    quotes = candles_to_quotes(candles, estimate_ohlc=True)
    results = indicators.get_vortex(quotes, period)
    valid = [r for r in results if r.pvi is not None and r.nvi is not None]
    if len(valid) < 2:
        return None
    prev, curr = valid[-2], valid[-1]
    if prev.pvi <= prev.nvi and curr.pvi > curr.nvi:
        return 'call'
    elif prev.pvi >= prev.nvi and curr.pvi < curr.nvi:
        return 'put'
    return None


async def marubozu_strategy(candles, sstrategy=None):
    min_body = sstrategy.get('marubozu_min_body') if sstrategy else SETTINGS.get('MARUBOZU_MIN_BODY', 95)
    quotes = candles_to_quotes(candles, estimate_ohlc=True)
    results = indicators.get_marubozu(quotes, min_body_percent=min_body)
    if results[-1].match.value > 0:
        return 'call'
    elif results[-1].match.value < 0:
        return 'put'
    return None


async def cci_strategy(candles, sstrategy=None):
    period = sstrategy.get('cci_period') if sstrategy else SETTINGS.get('CCI_PERIOD', 20)
    quotes = candles_to_quotes(candles, estimate_ohlc=True)
    results = indicators.get_cci(quotes, lookback_periods=period)
    valid = [r for r in results if r.cci is not None]
    if len(valid) < 2:
        return None
    prev, curr = valid[-2], valid[-1]
    if prev.cci <= 100 and curr.cci > 100:
        return 'call'
    elif prev.cci >= -100 and curr.cci < -100:
        return 'put'
    return None


async def bollinger_bands_strategy(candles, sstrategy=None):
    period = sstrategy.get('bb_period') if sstrategy else SETTINGS.get('BB_PERIOD', 20)
    quotes = candles_to_quotes(candles, estimate_ohlc=True)
    results = indicators.get_bollinger_bands(quotes, lookback_periods=period)
    valid = [r for r in results if r.percent_b is not None]
    if len(valid) < 2:
        return None
    prev, curr = valid[-2], valid[-1]
    if prev.percent_b >= 0 and curr.percent_b < 0:
        return 'call'
    elif prev.percent_b <= 1 and curr.percent_b > 1:
        return 'put'
    return None


async def check_strategies(candles, sstrategy=None):
    strategy = sstrategy.get('strategy', 1) if sstrategy else SETTINGS.get('STRATEGY', 1)
    if strategy == 6:
        action = await bollinger_bands_strategy(candles, sstrategy=sstrategy)
    elif strategy == 5:
        action = await cci_strategy(candles, sstrategy=sstrategy)
    elif strategy == 4:
        action = await marubozu_strategy(candles, sstrategy=sstrategy)
    elif strategy == 3:
        action = await vortex_strategy(candles, sstrategy=sstrategy)
    elif strategy == 2:
        action = await psar_strategy(candles, sstrategy=sstrategy)
    else:
        action = await moving_averages_cross(candles, sstrategy=sstrategy)

    if not action:
        return

    rsi_enabled = True if sstrategy else SETTINGS.get('RSI_ENABLED')
    if rsi_enabled:
        action = await rsi_strategy(candles, action, sstrategy=sstrategy)
        if not action:
            return

    supertrend_enabled = True if sstrategy else SETTINGS.get('SUPERTREND_ENABLED')
    if supertrend_enabled:
        action = await supertrend_strategy(candles, action, sstrategy=sstrategy)
        if not action:
            return

    # action = await get_price_action(candles, action)
    # if not action:
    #     return  # secret ingredient
    return action


async def get_candles_yfinance(email, asset, timeframe):
    response = requests.get(CANDLES_URL, params={'asset': asset, 'email': email, 'timeframe': timeframe, 'size': 1000})
    if response.status_code != 200:
        raise Exception(response.json()['error'])
    candles = [['', '', c] for c in response.json()[asset]]  # ['', '', val] to fit into strategies where 'close' is [2]
    # print('Candles: ', len(candles))
    return candles


async def backtest(email, timeframe='1m'):  # 1m, 2m, 3m, 5m, 10m, 15m, 30m, 60m
    assets = requests.get(ASSETS_URL, params={'email': email})
    if assets.status_code != 200:
        log(assets.json()['error'])
        return
    PROFITS = []
    for asset in assets.json()['assets']:
        await asyncio.sleep(0.6)
        try:
            candles = await get_candles_yfinance(email, asset, timeframe=timeframe)
        except:
            log(f'Backtest on {asset} with {timeframe}min timeframe! No candles available, try later.')
            continue
        if not candles:
            log(f'Backtest on {asset} with {timeframe}min timeframe! No candles available, try later.')
            continue

        strategy = SETTINGS.get('STRATEGY', 1)
        if strategy == 6:
            size = SETTINGS.get('BB_PERIOD', 20)
        elif strategy == 5:
            size = SETTINGS.get('CCI_PERIOD', 20)
        elif strategy == 4:
            size = 5
        elif strategy == 3:
            size = SETTINGS.get('VORTEX_PERIOD', 14)
        elif strategy == 2:
            size = 50  # PSAR needs enough warmup candles
        else:
            size = SETTINGS.get('SLOW_MA', 8)

        if SETTINGS.get('RSI_ENABLED'):
            size = max(size, SETTINGS.get('RSI_PERIOD', 14))
        if SETTINGS.get('SUPERTREND_ENABLED'):
            size = max(size, SETTINGS.get('SUPERTREND_PERIOD', 10))
        size += 11

        actions = {}
        for i in range(size, len(candles) + 1):
            candles_part = candles[i - size:i + 1]
            action = await check_strategies(candles_part)
            if action:
                if SETTINGS['VICE_VERSA']:
                    action = 'call' if action == 'put' else 'put'
                actions[i] = action

        print('Actions:', len(actions))
        try:
            per = int(len(candles) / len(actions))
        except ZeroDivisionError:
            per = ''
        log(f'Backtest on last {len(candles)} candles for {asset} with {timeframe}min timeframe! Frequency: 1 order per {per} candles. ')

        for estimation in [1, 2, 3]:  # candles
            wins = 0
            draws = 0
            for i, action in actions.items():
                try:
                    if candles[i][2] == candles[i + estimation][2]:
                        draws += 1
                    if action == 'call' and candles[i][2] < candles[i + estimation][2]:
                        wins += 1
                    elif action == 'put' and candles[i][2] > candles[i + estimation][2]:
                        wins += 1
                except IndexError:
                    pass
            try:
                profit = wins * 100 // (len(actions) - draws)
                PROFITS.append(profit)
                log(f'By estimation of {estimation} candles, profit is {profit}%')
            except ZeroDivisionError:
                log(f'No trades.')
                continue

    log(f'Backtest average profit for all assets: {sum(PROFITS) // len(PROFITS)}%')
    log('Backtest ended, trading...')


def countdown_with_terminate(seconds, terminate_key='t'):
    """Show a live countdown in the terminal; return True if the user pressed the
    terminate key during it, False if the countdown ran out naturally. Non-blocking
    read via select() so the countdown keeps ticking while waiting for input."""
    import select
    for remaining in range(seconds, 0, -1):
        print(f'\r{EMO_CLOCK} Auto-continuing in {remaining:2d}s... press T to terminate: ', end='', flush=True)
        try:
            ready, _, _ = select.select([sys.stdin], [], [], 1.0)
            if ready:
                line = sys.stdin.readline().strip().lower()
                if line == terminate_key:
                    print()
                    return True
        except Exception:
            time.sleep(1)  # non-terminal stdin (e.g. piped input) - fall back to plain wait
    print()
    return False


async def main():
    global QT_SESSION_COUNT, QT_TP_HIT, QT_RUN_FINISHED, QT_TOTAL_PROFIT, QT_BASE_AMOUNT, \
        QT_SESSION_ACTIVE, QT_DIRECTION, QT_STEP, QT_SESSION_ASSET, QT_SESSION_START_BALANCE, \
        QT_MODE_CHECKED_ONCE, INITIAL_DEPOSIT, QT_AUTO_CONTINUE

    await set_remote_debugging_allowed()
    print('🚀 Launching Chrome... (can take 10-30s)')
    driver = await get_driver()
    print('✅ Chrome launched. Checking session tab...')
    await asyncio.sleep(3)  # let the restored tab settle
    current = driver.current_url
    target = URL
    try:
        with open('last_url.txt') as f:
            saved = f.read().strip()
        if saved and ('cabinet' in saved or 'pocketoption' in saved or 'tournament' in saved):
            target = saved
    except Exception:
        pass
    if ('pocketoption' in current or 'pocket2.click' in current or 'cabinet' in current) and 'login' not in current and 'sign' not in current:
        print(f'✅ Resuming existing session tab (no forced reload): {current}')
        target = current
    else:
        print(f'🌐 Loading: {target}')
        try:
            driver.set_page_load_timeout(15)
            driver.get(target)
        except Exception:
            print('⚠️ Page load timed out, continuing anyway...')

    while True:  # outer restart loop - re-entered on Y after a Quick Trade run finishes
        consecutive_dead_checks = 0
        chrome_lost = False
        while True:
            if not TRADING_ALLOWED:
                break  # TP/SL already ended the run - leave the loop instead of spinning forever
            if not await driver_alive(driver):
                consecutive_dead_checks += 1
                if consecutive_dead_checks >= 3:
                    log('Chrome session lost. Stopping the bot so no trade result gets misread against a dead connection.')
                    chrome_lost = True
                    break
                await asyncio.sleep(1)
                continue
            consecutive_dead_checks = 0
            await websocket_log(driver)
            await check_deposit(driver)
            if not TRADING_ALLOWED:
                break  # TP/SL hit just now - leave before any trade slips through
            if SETTINGS.get('TRADING_MODE', 'normal') == 'quick':
                await check_quick_trade(driver)
                if QT_RUN_FINISHED:
                    break  # graceful stop - drop out to the Y/N prompt below instead of hot-spinning
            else:
                await check_indicators(driver)

        if chrome_lost:
            break  # real crash - no prompt, just stop

        if not TRADING_ALLOWED:
            # Stop loss (either mode) or the Normal-mode take profit ended the run. Nothing to prompt
            # for: show where we ended up and fall out of main() so the terminal prompt comes back.
            end_balance = await get_balance(driver)
            print()
            if end_balance and INITIAL_DEPOSIT:
                run_pnl = end_balance - INITIAL_DEPOSIT
                log(f'Bot stopped on {STOP_REASON}. Balance {INITIAL_DEPOSIT} -> {end_balance}. '
                    f'Run P/L: {run_pnl:+.2f} {total_emo(run_pnl)}')
            else:
                log(f'Bot stopped on {STOP_REASON}.')
            if SETTINGS.get('TRADING_MODE', 'normal') == 'quick':
                log(f'Quick Trade: {QT_SESSION_COUNT} session(s) closed. '
                    f'Total profit this run: {QT_TOTAL_PROFIT:+.2f} {total_emo(QT_TOTAL_PROFIT)}')
            break

        # Quick Trade run finished (sessions target reached, or take profit hit).
        was_tp_stop = QT_TP_HIT
        print()
        if was_tp_stop:
            log(f'Take profit reached. Total profit this run: {QT_TOTAL_PROFIT:+.2f} {total_emo(QT_TOTAL_PROFIT)}')
        else:
            log(f'Quick Trade finished {QT_SESSION_COUNT} session(s). Total profit this run: {QT_TOTAL_PROFIT:+.2f} {total_emo(QT_TOTAL_PROFIT)}')

        if QT_AUTO_CONTINUE:
            # Already in auto-continue mode from a previous 'A' - no more prompting,
            # just a countdown the user can interrupt with T.
            terminated = countdown_with_terminate(30, terminate_key='t')
            if terminated:
                log('Terminated.')
                break
            answer = 'a'
        else:
            try:
                answer = input('Do you want to continue? (Y/N/A - A = auto-continue at 5 sessions per run): ').strip().lower()
            except (EOFError, KeyboardInterrupt):
                answer = 'n'

        if answer not in ('y', 'a'):
            log('Stopping.')
            break

        if answer == 'a' and not QT_AUTO_CONTINUE:
            QT_AUTO_CONTINUE = True
            log('Auto-continue enabled: future runs will use 5 sessions each (your saved session '
                  'setting is unchanged), with a 30s countdown between runs. '
                  'Press T during the countdown at any time to terminate.')

        if was_tp_stop:
            current_tp = float(SETTINGS.get('QT_TAKE_PROFIT', 100))
            new_tp = current_tp + 50
            save_settings(QT_TAKE_PROFIT=new_tp)
            log(f'Take profit raised to {new_tp:.2f}. Restarting Quick Trade with the same settings.')
        else:
            log('Restarting Quick Trade with the same settings.')

        # Reset run state for a fresh Quick Trade run, same configured settings.
        QT_SESSION_COUNT = 0
        QT_TP_HIT = False
        QT_RUN_FINISHED = False
        QT_TOTAL_PROFIT = 0.0
        QT_SESSION_ACTIVE = False
        QT_DIRECTION = None
        QT_STEP = 0
        QT_SESSION_ASSET = None
        QT_SESSION_START_BALANCE = None
        QT_MODE_CHECKED_ONCE = False
        INITIAL_DEPOSIT = None  # let check_deposit re-baseline so a fresh TP target is measured from here



def cleanup_martingale_list(value):
    value = value.replace(' ', '')
    value_list = value.split(',')
    value_list = [int(v) for v in value_list]
    if len(value_list) < 2 or value_list[0] < 1 or value_list[0] > 19999 or value_list[-1] > 20000:
        raise
    martingale_list = []
    for i, v in enumerate(value_list):
        if i == 0:
            martingale_list.append(v)
        elif i < len(value_list):
            if value_list[i - 1] < value_list[i]:
                martingale_list.append(v)
            else:
                raise
    return martingale_list


def read_settings():
    global SETTINGS
    try:
        with open(SETTINGS_PATH, 'r') as settings_file:
            for line in settings_file.readlines():
                parts = line.replace('\n', '').split(':')
                setting = parts[0]
                setting_type = parts[1]
                split = setting.split('=')
                value = split[1]
                if setting_type == 'bool':
                    value = True if value == 'True' else False
                elif setting_type == 'int':
                    value = int(value)
                elif setting_type == 'float':
                    value = float(value)
                elif setting_type == 'str':
                    if split[0] == 'MARTINGALE_LIST':
                        value = cleanup_martingale_list(value)
                    else:
                        value = value
                SETTINGS[split[0]] = value
    except FileNotFoundError as e:
        log(f'Settings.txt not found, creating it. Error: {e}')


def save_settings(**kwargs):
    global SETTINGS
    with open(SETTINGS_PATH, 'w') as settings_file:
        for setting, value in kwargs.items():
            if setting == 'MARTINGALE_LIST':
                SETTINGS[setting] = cleanup_martingale_list(value)  # no try: is needed, as it checks before
            else:
                SETTINGS[setting] = value  # refresh global SETTINGS
            settings_file.write(f"{setting}={value}:{type(value).__name__}\n")


def tkinter_run():
    global window
    read_settings()

    ctk.set_appearance_mode('dark')
    ctk.set_default_color_theme('dark-blue')

    window = ctk.CTk()
    window.geometry('1620x820')
    window.title('Binary Options Automation — Pocket Option · Collins_Obi')
    window.configure(fg_color='#0f1117')
    window.minsize(1400, 720)

    BG = '#0f1117'
    PANEL_N = '#161a24'
    PANEL_Q = '#1a1620'
    FG = '#e8eaf0'
    FG_DIM = '#8b90a3'
    FG_FAINT = '#565c72'
    ACC_N = '#3d7eff'
    ACC_Q = '#f4c95d'
    BORDER = '#232838'
    ENTRY_BG = '#252a3c'

    # ---- shared widget helpers ----
    def L(parent, text, bold=False):
        return ctk.CTkLabel(parent, text=text,
                            text_color=FG if bold else FG_DIM,
                            font=('TkDefaultFont', 12 if bold else 11,
                                  'bold' if bold else 'normal'),
                            anchor='w')

    def E(parent, var, width=70):
        return ctk.CTkEntry(parent, textvariable=var, width=width, height=28,
                            justify='right', corner_radius=8,
                            fg_color=ENTRY_BG, border_width=0)

    def CH(parent, var, text):
        return ctk.CTkCheckBox(parent, text=text, variable=var,
                               font=('TkDefaultFont', 11),
                               checkbox_width=18, checkbox_height=18,
                               corner_radius=4, border_width=2,
                               fg_color=ACC_N, hover_color='#5a91ff')

    def R(parent, var, value, text, accent=ACC_N):
        return ctk.CTkRadioButton(parent, text=text, variable=var, value=value,
                                  font=('TkDefaultFont', 11),
                                  radiobutton_width=16, radiobutton_height=16,
                                  fg_color=accent, hover_color=accent,
                                  border_width_checked=5,
                                  text_color=FG)

    def OM(parent, var, values, width=76):
        return ctk.CTkOptionMenu(parent, variable=var, values=values,
                                 width=width, height=28, corner_radius=8,
                                 fg_color=ENTRY_BG, button_color='#2f3550',
                                 button_hover_color='#3a4060')

    # ---- header ----
    header = ctk.CTkFrame(window, fg_color='transparent')
    header.grid(row=0, column=0, columnspan=2, sticky='ew', padx=24, pady=(18, 4))
    ctk.CTkLabel(header, text='Pocket Option', text_color=FG,
                 font=('TkDefaultFont', 20, 'bold')).pack(side='left')
    ctk.CTkLabel(header, text='  Trading Bot', text_color=ACC_N,
                 font=('TkDefaultFont', 20, 'bold')).pack(side='left')
    ctk.CTkLabel(header, text='  Collins_Obi', text_color=FG_DIM,
                 font=('TkDefaultFont', 14)).pack(side='left', pady=(6, 0))

    # ---- variables ----
    radio_var = ctk.IntVar(value=SETTINGS.get('STRATEGY', 1))
    mode_var = ctk.StringVar(value=SETTINGS.get('TRADING_MODE', 'normal'))

    fast_ma_type = ctk.StringVar(value=SETTINGS.get('FAST_MA_TYPE', 'SMA'))
    slow_ma_type = ctk.StringVar(value=SETTINGS.get('SLOW_MA_TYPE', 'SMA'))
    rsi_upper_sign = ctk.StringVar(value=SETTINGS.get('RSI_CALL_SIGN', '>'))
    rsi_lower_sign = ctk.StringVar(value=get_rsi_put_sign(SETTINGS.get('RSI_CALL_SIGN', '>')))
    backtest_timeframe = ctk.StringVar(value=SETTINGS.get('BACKTEST_TIMEFRAME', '1m'))

    fast_ma_val = ctk.StringVar(value=str(SETTINGS.get('FAST_MA', 3)))
    slow_ma_val = ctk.StringVar(value=str(SETTINGS.get('SLOW_MA', 8)))
    vortex_period_val = ctk.StringVar(value=str(SETTINGS.get('VORTEX_PERIOD', 14)))
    marubozu_min_body_val = ctk.StringVar(value=str(SETTINGS.get('MARUBOZU_MIN_BODY', 95)))
    cci_period_val = ctk.StringVar(value=str(SETTINGS.get('CCI_PERIOD', 20)))
    bb_period_val = ctk.StringVar(value=str(SETTINGS.get('BB_PERIOD', 20)))
    rsi_period_val = ctk.StringVar(value=str(SETTINGS.get('RSI_PERIOD', 14)))
    rsi_upper_val = ctk.StringVar(value=str(SETTINGS.get('RSI_UPPER', 70)))
    rsi_lower_val = ctk.StringVar(value=str(get_rsi_lower(int(SETTINGS.get('RSI_UPPER', 70)))))
    supertrend_period_val = ctk.StringVar(value=str(SETTINGS.get('SUPERTREND_PERIOD', 10)))
    min_payout_val = ctk.StringVar(value=str(SETTINGS.get('MIN_PAYOUT', 92)))
    take_profit_val = ctk.StringVar(value=str(SETTINGS.get('TAKE_PROFIT', 100)))
    stop_loss_val = ctk.StringVar(value=str(SETTINGS.get('STOP_LOSS', 50)))
    chrome_version_val = ctk.StringVar(value=str(SETTINGS.get('CHROME_VERSION', 149)))
    mar_value = ', '.join([str(v) for v in SETTINGS.get('MARTINGALE_LIST', [1, 3, 7, 15, 32, 67])])
    ent_mar_val = ctk.StringVar(value=mar_value)
    multiplier_gui_val = ctk.StringVar(value=str(SETTINGS.get('MULTIPLIER', 2.3)))
    min_bet_gui_val = ctk.StringVar(value=str(SETTINGS.get('MIN_BET_MIN', 1)) if False else str(SETTINGS.get('MIN_BET_AMOUNT', 1)))

    qt_fast_ma_type = ctk.StringVar(value=SETTINGS.get('QT_MA_TYPE', 'SMA'))
    qt_fast_ma_val = ctk.StringVar(value=str(SETTINGS.get('QT_FAST_MA', 5)))
    qt_slow_ma_val = ctk.StringVar(value=str(SETTINGS.get('QT_SLOW_MA', 10)))
    qt_amount_val = ctk.StringVar(value=str(SETTINGS.get('QT_TRADE_AMOUNT', 1)))
    qt_mart_val = ctk.StringVar(value=str(SETTINGS.get('QT_MARTINGALE', 2.1)))
    qt_max_steps_val = ctk.StringVar(value=str(SETTINGS.get('QT_MAX_STEPS', 7)))
    qt_sessions_val = ctk.StringVar(value=str(SETTINGS.get('QT_SESSIONS', 10)))
    qt_tp_val = ctk.StringVar(value=str(SETTINGS.get('QT_TAKE_PROFIT', 100)))
    qt_min_payout_val = ctk.StringVar(value=str(SETTINGS.get('QT_MIN_PAYOUT', 50)))
    qt_expiry_val = ctk.StringVar(value=str(SETTINGS.get('QT_EXPIRY_SECONDS', 5)))

    chk_rsi_var = ctk.IntVar(value=1 if SETTINGS.get('RSI_ENABLED', False) else 0)
    chk_supertrend_var = ctk.IntVar(value=1 if SETTINGS.get('SUPERTREND_ENABLED', False) else 0)
    chk_take_prof = ctk.IntVar(value=1 if SETTINGS.get('TAKE_PROFIT_ENABLED', False) else 0)
    chk_stop_lo = ctk.IntVar(value=1 if SETTINGS.get('STOP_LOSS_ENABLED', False) else 0)
    chk_var = ctk.IntVar(value=1 if SETTINGS.get('VICE_VERSA', False) else 0)
    chk_back = ctk.IntVar(value=1 if SETTINGS.get('BACKTEST', False) else 0)
    chk_begin = ctk.IntVar(value=1 if SETTINGS.get('BEGINNING_CANDLE_ORDER', False) else 0)
    chk_mar = ctk.IntVar(value=1 if SETTINGS.get('MARTINGALE_ENABLED', False) else 0)
    chk_qt_tp_var = ctk.IntVar(value=1 if SETTINGS.get('QT_TAKE_PROFIT_ENABLED', False) else 0)

    # ---- panels row ----
    top = ctk.CTkFrame(window, fg_color='transparent')
    top.grid(row=1, column=0, columnspan=2, sticky='nsew', padx=16, pady=(8, 8))
    window.grid_columnconfigure(0, weight=3)
    window.grid_columnconfigure(1, weight=1)
    window.grid_rowconfigure(1, weight=1)
    top.grid_columnconfigure(0, weight=3)
    top.grid_columnconfigure(1, weight=1)
    top.grid_rowconfigure(0, weight=1)

    # ---------- Normal panel ----------
    normal_panel = ctk.CTkFrame(top, fg_color=PANEL_N, corner_radius=16,
                                border_width=2, border_color=ACC_N)
    normal_panel.grid(row=0, column=0, sticky='nsew', padx=(0, 8))
    normal_panel.grid_columnconfigure(0, weight=1)

    R(normal_panel, mode_var, 'normal', 'Use Normal Trading').grid(
        row=0, column=0, sticky='w', padx=20, pady=(16, 8))

    normal_content = ctk.CTkFrame(normal_panel, fg_color='transparent')
    normal_content.grid(row=1, column=0, sticky='nsew', padx=16, pady=(0, 16))
    for i in range(4):
        normal_content.grid_columnconfigure(i, weight=0)

    # --- Strategies column ---
    col_s = ctk.CTkFrame(normal_content, fg_color='transparent')
    col_s.grid(row=0, column=0, sticky='nw', padx=(4, 20))

    L(col_s, 'Strategies', bold=True).grid(row=0, column=0, columnspan=3, sticky='w', pady=(0, 6))
    strategies = ['Moving Averages Crossing', 'Parabolic SAR', 'Vortex',
                  'Marubozu', 'CCI', 'Bollinger Bands']
    for i, name in enumerate(strategies, start=1):
        R(col_s, radio_var, i, name).grid(row=i, column=0, columnspan=3,
                                          sticky='w', pady=1)
    r = len(strategies) + 1
    L(col_s, 'Fast').grid(row=r, column=0, sticky='w')
    OM(col_s, fast_ma_type, ['SMA', 'EMA', 'WMA']).grid(row=r, column=1, padx=(6, 6))
    E(col_s, fast_ma_val, width=54).grid(row=r, column=2, sticky='e')
    r += 1
    L(col_s, 'Slow').grid(row=r, column=0, sticky='w')
    OM(col_s, slow_ma_type, ['SMA', 'EMA', 'WMA']).grid(row=r, column=1, padx=(6, 6))
    E(col_s, slow_ma_val, width=54).grid(row=r, column=2, sticky='e')
    r += 1
    for label, var in [('Vortex period', vortex_period_val),
                       ('Marubozu %', marubozu_min_body_val),
                       ('CCI period', cci_period_val),
                       ('BB period', bb_period_val)]:
        L(col_s, label).grid(row=r, column=0, sticky='w')
        E(col_s, var, width=54).grid(row=r, column=2, sticky='e', pady=2)
        r += 1

    # --- Indicators column ---
    col_i = ctk.CTkFrame(normal_content, fg_color='transparent')
    col_i.grid(row=0, column=1, sticky='nw', padx=(0, 20))

    L(col_i, 'Indicators', bold=True).grid(row=0, column=0, columnspan=3, sticky='w', pady=(0, 6))
    CH(col_i, chk_rsi_var, 'RSI').grid(row=1, column=0, sticky='w', pady=2)
    L(col_i, 'period').grid(row=1, column=1, sticky='e')
    ent_rsi_period = E(col_i, rsi_period_val, width=54)
    ent_rsi_period.grid(row=1, column=2, sticky='e', pady=2)

    lbl_rsi_call = L(col_i, 'Call if RSI')
    lbl_rsi_call.grid(row=2, column=0, sticky='w')
    rsi_upper_drop = OM(col_i, rsi_upper_sign, ['>', '<'], width=56)
    rsi_upper_drop.grid(row=2, column=1, padx=(6, 6))
    ent_rsi_upper = E(col_i, rsi_upper_val, width=54)
    ent_rsi_upper.grid(row=2, column=2, sticky='e', pady=2)

    lbl_rsi_put = L(col_i, 'Put if RSI')
    lbl_rsi_put.grid(row=3, column=0, sticky='w')
    rsi_lower_drop = OM(col_i, rsi_lower_sign, ['>', '<'], width=56)
    rsi_lower_drop.grid(row=3, column=1, padx=(6, 6))
    ent_rsi_lower = E(col_i, rsi_lower_val, width=54)
    ent_rsi_lower.grid(row=3, column=2, sticky='e', pady=2)

    CH(col_i, chk_supertrend_var, 'Supertrend').grid(row=4, column=0, sticky='w', pady=(10, 2))
    L(col_i, 'period').grid(row=4, column=1, sticky='e')
    ent_supertrend_period = E(col_i, supertrend_period_val, width=54)
    ent_supertrend_period.grid(row=4, column=2, sticky='e', pady=(10, 2))

    # --- Options column ---
    col_o = ctk.CTkFrame(normal_content, fg_color='transparent')
    col_o.grid(row=0, column=2, sticky='nw', padx=(0, 20))

    L(col_o, 'Options', bold=True).grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 6))
    L(col_o, 'Min payout %').grid(row=1, column=0, sticky='w')
    ent_min_payout = E(col_o, min_payout_val, width=54)
    ent_min_payout.grid(row=1, column=1, sticky='e', pady=2)

    CH(col_o, chk_take_prof, 'Take profit $').grid(row=2, column=0, sticky='w', pady=2)
    ent_take_profit = E(col_o, take_profit_val, width=72)
    ent_take_profit.grid(row=2, column=1, sticky='e', pady=2)

    CH(col_o, chk_stop_lo, 'Stop loss $').grid(row=3, column=0, sticky='w', pady=2)
    ent_stop_loss = E(col_o, stop_loss_val, width=72)
    ent_stop_loss.grid(row=3, column=1, sticky='e', pady=2)

    chk_vice_versa = CH(col_o, chk_var, 'Vice versa Call <-> Put')
    chk_vice_versa.grid(row=4, column=0, columnspan=2, sticky='w', pady=4)

    chk_backtest = CH(col_o, chk_back, 'Backtest for')
    chk_backtest.grid(row=5, column=0, sticky='w', pady=2)
    backtest_option = OM(col_o, backtest_timeframe,
                         ['1m', '2m', '3m', '5m', '10m', '15m', '30m', '60m'], width=80)
    backtest_option.grid(row=5, column=1, sticky='e', pady=2)

    chk_beginning = CH(col_o, chk_begin, 'Beginning candle order')
    chk_beginning.grid(row=6, column=0, columnspan=2, sticky='w', pady=4)

    L(col_o, 'Chrome version').grid(row=7, column=0, sticky='w')
    ent_chrome_version = E(col_o, chrome_version_val, width=54)
    ent_chrome_version.grid(row=7, column=1, sticky='e', pady=2)

    # --- Martingale column ---
    col_m = ctk.CTkFrame(normal_content, fg_color='transparent')
    col_m.grid(row=0, column=3, sticky='nw')

    L(col_m, 'Martingale', bold=True).grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 6))

    chk_martingale = CH(col_m, chk_mar, 'Use list (OFF = x2.3)')
    chk_martingale.grid(row=1, column=0, columnspan=2, sticky='w', pady=2)
    ent_mar = ctk.CTkEntry(col_m, textvariable=ent_mar_val, width=170, height=28,
                           justify='right', corner_radius=8, fg_color=ENTRY_BG,
                           border_width=0)
    ent_mar.grid(row=2, column=0, columnspan=2, sticky='w', pady=(2, 8))

    L(col_m, 'Multiplier x').grid(row=3, column=0, sticky='w')
    ent_multiplier = E(col_m, multiplier_gui_val, width=72)
    ent_multiplier.grid(row=3, column=1, sticky='e', pady=2)

    L(col_m, 'Min bet $').grid(row=4, column=0, sticky='w')
    ent_min_bet = E(col_m, min_bet_gui_val, width=72)
    ent_min_bet.grid(row=4, column=1, sticky='e', pady=2)

    # ---------- Quick panel ----------
    quick_panel = ctk.CTkFrame(top, fg_color=PANEL_Q, corner_radius=16,
                               border_width=2, border_color=BORDER)
    quick_panel.grid(row=0, column=1, sticky='nsew', padx=(8, 0))
    quick_panel.grid_columnconfigure(0, weight=1)

    R(quick_panel, mode_var, 'quick', 'Use Quick Trade', accent=ACC_Q).grid(
        row=0, column=0, sticky='w', padx=20, pady=(16, 8))

    quick_content = ctk.CTkFrame(quick_panel, fg_color='transparent')
    quick_content.grid(row=1, column=0, sticky='nsew', padx=18, pady=(0, 16))

    L(quick_content, 'Session-based: MA-position direction, martingale per session.') \
        .grid(row=0, column=0, columnspan=3, sticky='w', pady=(0, 12))

    r = 1
    L(quick_content, 'Fast MA').grid(row=r, column=0, sticky='w')
    qt_fast_ma_drop = OM(quick_content, qt_fast_ma_type, ['SMA', 'EMA', 'WMA'], width=76)
    qt_fast_ma_drop.grid(row=r, column=1, padx=(6, 6))
    ent_qt_fast_ma = E(quick_content, qt_fast_ma_val, width=72)
    ent_qt_fast_ma.grid(row=r, column=2, sticky='e', pady=2)
    r += 1
    L(quick_content, 'Slow MA').grid(row=r, column=0, sticky='w')
    ent_qt_slow_ma = E(quick_content, qt_slow_ma_val, width=72)
    ent_qt_slow_ma.grid(row=r, column=2, sticky='e', pady=2)
    r += 1
    L(quick_content, 'Trade Amount $').grid(row=r, column=0, sticky='w')
    ent_qt_amount = E(quick_content, qt_amount_val, width=72)
    ent_qt_amount.grid(row=r, column=2, sticky='e', pady=2)
    r += 1
    L(quick_content, 'Martingale x').grid(row=r, column=0, sticky='w')
    ent_qt_mart = E(quick_content, qt_mart_val, width=72)
    ent_qt_mart.grid(row=r, column=2, sticky='e', pady=2)
    r += 1
    L(quick_content, 'Max Steps').grid(row=r, column=0, sticky='w')
    ent_qt_max_steps = E(quick_content, qt_max_steps_val, width=72)
    ent_qt_max_steps.grid(row=r, column=2, sticky='e', pady=2)
    r += 1
    L(quick_content, 'Sessions (min 10)').grid(row=r, column=0, sticky='w')
    ent_qt_sessions = E(quick_content, qt_sessions_val, width=72)
    ent_qt_sessions.grid(row=r, column=2, sticky='e', pady=2)
    r += 1
    CH(quick_content, chk_qt_tp_var, 'Quick Trade Take Profit').grid(
        row=r, column=0, columnspan=2, sticky='w', pady=4)
    ent_qt_tp = E(quick_content, qt_tp_val, width=72)
    ent_qt_tp.grid(row=r, column=2, sticky='e', pady=4)
    r += 1
    L(quick_content, 'Min Payout %').grid(row=r, column=0, sticky='w')
    ent_qt_min_payout = E(quick_content, qt_min_payout_val, width=72)
    ent_qt_min_payout.grid(row=r, column=2, sticky='e', pady=2)
    r += 1
    L(quick_content, 'Expiry (sec)').grid(row=r, column=0, sticky='w')
    ent_qt_expiry = E(quick_content, qt_expiry_val, width=72)
    ent_qt_expiry.grid(row=r, column=2, sticky='e', pady=2)

    # ---- widget group lists for mode toggle ----
    qt_normal_widgets = [
        col_s, col_i, col_o, col_m,
    ]
    qt_quick_widgets = [
        quick_content,
    ]

    # ---- callbacks ----
    def enable_rsi():
        state = 'normal' if chk_rsi_var.get() else 'disabled'
        for el in [ent_rsi_period, lbl_rsi_call, lbl_rsi_put,
                   rsi_upper_drop, ent_rsi_upper,
                   rsi_lower_drop, ent_rsi_lower]:
            try:
                el.configure(state=state)
            except Exception:
                pass

    def enable_supertrend():
        state = 'normal' if chk_supertrend_var.get() else 'disabled'
        try:
            ent_supertrend_period.configure(state=state)
        except Exception:
            pass

    def enable_take_profit():
        try:
            ent_take_profit.configure(state='normal' if chk_take_prof.get() else 'disabled')
        except Exception:
            pass

    def enable_stop_loss():
        try:
            ent_stop_loss.configure(state='normal' if chk_stop_lo.get() else 'disabled')
        except Exception:
            pass

    def set_rsi_lower_sign(*args):
        rsi_lower_sign.set('<' if rsi_upper_sign.get() == '>' else '>')

    def set_rsi_lower(*args):
        try:
            value = int(float(rsi_upper_val.get()))
            if value > 99:
                raise ValueError
            rsi_lower_val.set(str(100 - value))
        except Exception:
            pass

    # wire the initial states
    enable_rsi()
    enable_supertrend()
    enable_take_profit()
    enable_stop_loss()
    chk_rsi_var.trace_add('write', lambda *a: enable_rsi())
    chk_supertrend_var.trace_add('write', lambda *a: enable_supertrend())
    chk_take_prof.trace_add('write', lambda *a: enable_take_profit())
    chk_stop_lo.trace_add('write', lambda *a: enable_stop_loss())
    rsi_upper_val.trace_add('write', set_rsi_lower)
    rsi_upper_sign.trace_add('write', set_rsi_lower_sign)

    def set_mar_state():
        try:
            ent_mar.configure(state='normal' if chk_mar.get() else 'disabled')
        except Exception:
            pass

    def set_qt_tp_state():
        try:
            ent_qt_tp.configure(state='normal' if chk_qt_tp_var.get() else 'disabled')
        except Exception:
            pass

    set_mar_state()
    set_qt_tp_state()
    chk_mar.trace_add('write', lambda *a: set_mar_state())
    chk_qt_tp_var.trace_add('write', lambda *a: set_qt_tp_state())

    def _walk_state(w, state):
        try:
            w.configure(state=state)
        except Exception:
            pass
        try:
            for child in w.winfo_children():
                _walk_state(child, state)
        except Exception:
            pass

    def set_mode_state():
        quick = mode_var.get() == 'quick'
        try:
            normal_panel.configure(border_color=BORDER if quick else ACC_N)
            quick_panel.configure(border_color=ACC_Q if quick else BORDER)
        except Exception:
            pass
        for w in qt_normal_widgets:
            _walk_state(w, 'disabled' if quick else 'normal')
        for w in qt_quick_widgets:
            _walk_state(w, 'normal' if quick else 'disabled')
        # re-enable the QT tp entry if its checkbox is on and we're in quick mode
        if quick and chk_qt_tp_var.get():
            try:
                ent_qt_tp.configure(state='normal')
            except Exception:
                pass
        if not quick:
            # normal-mode widgets have their own conditional enables
            enable_rsi()
            enable_supertrend()
            enable_take_profit()
            enable_stop_loss()
            set_mar_state()

    set_mode_state()
    mode_var.trace_add('write', lambda *a: set_mode_state())

    def validate_int(value, min_=1, max_=10000):
        v = str(value).strip()
        if not v.isdigit():
            return False
        return min_ <= int(v) <= max_

    def validate_list(value):
        try:
            cleanup_martingale_list(value)
        except Exception:
            return False
        return True

    # ---- error line + buttons ----
    error_variable = ctk.StringVar(value='')
    lbl_error = ctk.CTkLabel(window, textvariable=error_variable, anchor='w',
                             text_color='#ff6b81',
                             font=('TkDefaultFont', 11))
    lbl_error.grid(row=2, column=0, columnspan=2, sticky='ew', padx=24, pady=(0, 4))

    btn_row = ctk.CTkFrame(window, fg_color='transparent')
    btn_row.grid(row=3, column=0, columnspan=2, sticky='ew', padx=24, pady=(0, 18))

    def run():
        error_variable.set('')
        try:
            _m = float(multiplier_gui_val.get())
            if _m < 1.0 or _m > 10.0:
                raise Exception()
        except Exception:
            error_variable.set('Multiplier: number between 1.0 and 10.0')
            return
        if not validate_int(fast_ma_val.get(), 1, 99):
            error_variable.set('Fast MA: should be number 1-99'); return
        if not validate_int(slow_ma_val.get(), 1, 99):
            error_variable.set('Slow MA: should be number 1-99'); return
        if int(fast_ma_val.get()) > int(slow_ma_val.get()):
            error_variable.set('Fast MA > Slow MA'); return
        if not validate_int(min_bet_gui_val.get(), 1, 20000):
            error_variable.set('Min bet: should be number 1-20000'); return
        if not validate_int(min_payout_val.get(), 20, 92):
            error_variable.set('min Payout: should be number 20-92'); return
        if chk_mar.get() and not validate_list(ent_mar_val.get()):
            error_variable.set('Martingale list: should be a comma separated list of increasing numbers'); return
        if chk_rsi_var.get() and not validate_int(rsi_period_val.get(), 1, 20):
            error_variable.set('RSI period: should be number 1-20'); return
        if chk_rsi_var.get() and not validate_int(rsi_upper_val.get(), 1, 99):
            error_variable.set('RSI: should be number 1-99'); return
        if chk_take_prof.get() and not validate_int(take_profit_val.get(), 1, 20000):
            error_variable.set('Take profit: should be number 1-20000'); return
        if chk_stop_lo.get() and not validate_int(stop_loss_val.get(), 1, 20000):
            error_variable.set('Stop loss: should be number 1-20000'); return
        if not validate_int(vortex_period_val.get(), 2, 99):
            error_variable.set('Vortex period: should be number 2-99'); return
        if not validate_int(marubozu_min_body_val.get(), 1, 99):
            error_variable.set('Marubozu min body: should be number 1-99'); return
        if not validate_int(cci_period_val.get(), 2, 99):
            error_variable.set('CCI period: should be number 2-99'); return
        if not validate_int(bb_period_val.get(), 2, 99):
            error_variable.set('Bollinger Bands period: should be number 2-99'); return
        if chk_supertrend_var.get() and not validate_int(supertrend_period_val.get(), 1, 99):
            error_variable.set('Supertrend period: should be number 1-99'); return
        if not validate_int(chrome_version_val.get(), 80, 999):
            error_variable.set('Chrome version: should be number 80-999'); return
        if mode_var.get() == 'quick':
            if not validate_int(qt_fast_ma_val.get(), 1, 99):
                error_variable.set('Quick Trade Fast MA: should be number 1-99'); return
            if not validate_int(qt_slow_ma_val.get(), 2, 200):
                error_variable.set('Quick Trade Slow MA: should be number 2-200'); return
            if int(qt_fast_ma_val.get()) >= int(qt_slow_ma_val.get()):
                error_variable.set('Quick Trade: Fast MA must be less than Slow MA'); return
            if not validate_int(qt_amount_val.get(), 1, 20000):
                error_variable.set('Quick Trade amount: should be number 1-20000'); return
            try:
                if float(qt_mart_val.get()) <= 1:
                    raise ValueError
            except ValueError:
                error_variable.set('Quick Trade martingale: should be a number greater than 1'); return
            if not validate_int(qt_max_steps_val.get(), 1, 20):
                error_variable.set('Quick Trade max martingale steps: should be number 1-20'); return
            if int(qt_sessions_val.get()) < 10:
                error_variable.set('Quick Trade sessions: minimum is 10'); return
            if chk_qt_tp_var.get() and not validate_int(qt_tp_val.get(), 1, 20000):
                error_variable.set('Quick Trade take profit: should be number 1-20000'); return
            if not validate_int(qt_min_payout_val.get(), 1, 92):
                error_variable.set('Quick Trade min payout: should be number 1-92'); return
            if not validate_int(qt_expiry_val.get(), 5, 3600):
                error_variable.set('Quick Trade expiry: should be number 5-3600 (seconds)'); return

        save_settings(
            STRATEGY=radio_var.get(),
            VORTEX_PERIOD=int(vortex_period_val.get()),
            MARUBOZU_MIN_BODY=int(marubozu_min_body_val.get()),
            CCI_PERIOD=int(cci_period_val.get()),
            BB_PERIOD=int(bb_period_val.get()),
            FAST_MA=int(fast_ma_val.get()),
            FAST_MA_TYPE=fast_ma_type.get(),
            SLOW_MA=int(slow_ma_val.get()),
            SLOW_MA_TYPE=slow_ma_type.get(),
            MIN_PAYOUT=int(min_payout_val.get()),
            VICE_VERSA=True if chk_var.get() else False,
            MARTINGALE_ENABLED=True if chk_mar.get() else False,
            MARTINGALE_LIST=ent_mar_val.get() if chk_mar.get() else mar_value,
            RSI_ENABLED=True if chk_rsi_var.get() else False,
            RSI_PERIOD=int(rsi_period_val.get()) if chk_rsi_var.get() else SETTINGS.get('RSI_PERIOD', 14),
            RSI_UPPER=int(rsi_upper_val.get()) if chk_rsi_var.get() else SETTINGS.get('RSI_UPPER', 70),
            RSI_CALL_SIGN=rsi_upper_sign.get() if chk_rsi_var.get() else SETTINGS.get('RSI_CALL_SIGN', '>'),
            BACKTEST=True if chk_back.get() else False,
            BACKTEST_TIMEFRAME=backtest_timeframe.get(),
            TAKE_PROFIT_ENABLED=True if chk_take_prof.get() else False,
            TAKE_PROFIT=int(take_profit_val.get()) if chk_take_prof.get() else SETTINGS.get('TAKE_PROFIT', 100),
            STOP_LOSS_ENABLED=True if chk_stop_lo.get() else False,
            STOP_LOSS=int(stop_loss_val.get()) if chk_stop_lo.get() else SETTINGS.get('STOP_LOSS', 50),
            USE_SERVER_STRATEGIES=SETTINGS.get('USE_SERVER_STRATEGIES', False),
            BEGINNING_CANDLE_ORDER=True if chk_begin.get() else False,
            SUPERTREND_ENABLED=True if chk_supertrend_var.get() else False,
            SUPERTREND_PERIOD=int(supertrend_period_val.get()) if chk_supertrend_var.get() else SETTINGS.get('SUPERTREND_PERIOD', 10),
            CHROME_VERSION=int(chrome_version_val.get()),
            MULTIPLIER=float(multiplier_gui_val.get()),
            MIN_BET_AMOUNT=int(min_bet_gui_val.get()),
            TRADING_MODE=mode_var.get(),
            QT_FAST_MA=int(qt_fast_ma_val.get()),
            QT_SLOW_MA=int(qt_slow_ma_val.get()),
            QT_MA_TYPE=qt_fast_ma_type.get(),
            QT_TRADE_AMOUNT=int(qt_amount_val.get()),
            QT_MARTINGALE=float(qt_mart_val.get()),
            QT_MAX_STEPS=int(qt_max_steps_val.get()),
            QT_SESSIONS=int(qt_sessions_val.get()) if int(qt_sessions_val.get()) >= 10 else 10,
            QT_TAKE_PROFIT_ENABLED=True if chk_qt_tp_var.get() else False,
            QT_TAKE_PROFIT=int(qt_tp_val.get()) if chk_qt_tp_var.get() else SETTINGS.get('QT_TAKE_PROFIT', 100),
            QT_MIN_PAYOUT=int(qt_min_payout_val.get()),
            QT_EXPIRY_SECONDS=int(qt_expiry_val.get()),
        )
        window.destroy()

    def on_close():
        window.destroy()
        sys.exit()

    run_btn = ctk.CTkButton(btn_row, text='▶   RUN', command=run,
                            fg_color=ACC_N, hover_color='#5a91ff',
                            corner_radius=12, width=140, height=44,
                            font=('TkDefaultFont', 14, 'bold'))
    run_btn.pack(side='right')

    window.protocol('WM_DELETE_WINDOW', on_close)
    window.mainloop()


if __name__ == '__main__':
    tkinter_run()
    read_settings()
    asyncio.run(main())
