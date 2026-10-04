import base64
import json
from datetime import datetime, timedelta

import pandas as pd
from selenium.webdriver.common.by import By
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split
from stock_indicators import indicators

from driver import get_driver
from utils import get_quotes, get_value

# ---- Colourful output (display only - never used in any comparison) ----
EMO_BUY    = '🟩💹'
EMO_SELL   = '🟥🔻'
EMO_CLOCK  = '⏰'
EMO_MODEL  = '🤖'
EMO_WAIT   = '⏳'
EMO_PUT    = '🔻'
EMO_CALL   = '🔺'

BASE_URL = 'https://pocketoption.com'  # change if PO is blocked in your country
_DEBUG_STATS = {'loops': 0, 'log_entries': 0, 'opcode2': 0, 'decoded': 0, 'candle_updates': 0, 'last_report': 0}
PERIOD = 0  # PERIOD on the graph in seconds, one of: 5, 10, 15, 30, 60, 300 etc.
TIME = 1  # minutes
CANDLES = []
ACTIONS = {}  # dict of {datetime: value} when an action has been made
MAX_ACTIONS = 1  # how many actions allowed at the period of time
ACTIONS_SECONDS = PERIOD  # how long action still in ACTIONS
LAST_REFRESH = datetime.now()
CURRENCY = None
CURRENCY_CHANGE = False
CURRENCY_CHANGE_DATE = datetime.now()
HEADER = [
    # 'supertrend',
    'emalong',
    # 'emashort',
    'awesome_oscillator',
    'psar',
    'cci',
    'macd',
    'profit',
]

driver = get_driver()


def load_web_driver():
    url = f'{BASE_URL}/en/cabinet/demo-quick-high-low/'
    driver.get(url)


def do_action(signal):
    action = True
    last_value = CANDLES[-1][2]

    global ACTIONS, IS_AMOUNT_SET
    for dat in list(ACTIONS.keys()):
        if dat < datetime.now() - timedelta(seconds=ACTIONS_SECONDS):
            del ACTIONS[dat]

    if action:
        if len(ACTIONS) >= MAX_ACTIONS:
            # print(f"Max actions reached, don't do a {signal} action")
            action = False

    if action:
        try:
            dir_emo = EMO_BUY if signal == 'call' else EMO_SELL
            print(
                f"{EMO_CLOCK} {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
                f"{dir_emo} {signal.upper()} on {CURRENCY} | price {last_value}")
            driver.find_element(by=By.CLASS_NAME, value=f'btn-{signal}').click()
            ACTIONS[datetime.now()] = last_value
            IS_AMOUNT_SET = False
        except Exception as e:
            print(f'❌ {e}')


def get_data(quotes, only_last_row=False):
    supertrend = indicators.get_super_trend(quotes)
    emalong = indicators.get_ema(quotes, lookback_periods=8)
    emashort = indicators.get_ema(quotes, lookback_periods=3)
    awesome_oscillator = indicators.get_awesome(quotes)
    psar = indicators.get_parabolic_sar(quotes)
    cci = indicators.get_cci(quotes)
    macd = indicators.get_macd(quotes)

    data = []
    for i in range(40, len(quotes), 1):
        try:
            row = []
            if only_last_row:
                i = -1
                # row.append(1 if supertrend[i].upper_band else 0)  # not working on Windows non-en_US locale
            row.append(1 if emashort[-2].ema > emalong[-2].ema and emashort[-1].ema < emalong[-1].ema and get_value(
                quotes[-1]) < get_value(quotes[-2]) < get_value(quotes[-3]) else 0)
            # row.append(0 if emashort[-2].ema < emalong[-2].ema and emashort[-1].ema > emalong[-1].ema and get_value(
            #     quotes[-1]) > get_value(quotes[-2]) > get_value(quotes[-3]) else 1)
            row.append(1 if awesome_oscillator[i].oscillator >= 0 else 0)
            row.append(1 if psar[i].is_reversal else 0)
            row.append(1 if cci[i].cci <= 0 else 0)
            row.append(1 if macd[i].macd >= macd[i].signal else 0)
            if only_last_row:
                return [row]
            row.append(1 if get_value(quotes[i + TIME]) <= get_value(quotes[i]) else 0)  # profit
            # print(f"Row length: {len(row)}")
            data.append(row)
        except:
            pass
    print('len data', len(data))
    return data


def check_data():
    quotes = get_quotes(CANDLES)

    data = get_data(quotes[-200:])
    df = pd.DataFrame(data, columns=HEADER)
    X = df.iloc[:, :len(HEADER) - 1]
    y = df['profit']
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    model = RandomForestClassifier(n_estimators=400)
    model.fit(X_train, y_train)
    y_pred = model.predict(X_test)
    model_accuracy = accuracy_score(y_test, y_pred)
    last = pd.DataFrame(get_data(quotes, only_last_row=True), columns=HEADER[:-1])
    probe = model.predict_proba(last)
    acc_emoji = '🟢' if model_accuracy > 0.55 else ('🟡' if model_accuracy > 0.45 else '🔴')
    print(f'{EMO_MODEL} Accuracy: {acc_emoji} {round(model_accuracy, 2)}  |  '
          f'{EMO_PUT} PUT: {round(probe[0][0], 2)}  |  '
          f'{EMO_CALL} CALL: {round(probe[0][1], 2)}')

    # if model_accuracy > 0.50:
    if probe[0][0] > 0.60:
        do_action('put')
    elif probe[0][1] > 0.60:
        do_action('call')
    else:
        print(f'{EMO_WAIT} {quotes[-1].date} — no signal, waiting...')


def _debug_report():
    import time
    _DEBUG_STATS['loops'] += 1
    now = time.time()
    if now - _DEBUG_STATS['last_report'] < 10:
        return
    _DEBUG_STATS['last_report'] = now
    print(f"{EMO_CLOCK} [status] loops={_DEBUG_STATS['loops']}  "
          f"log_entries={_DEBUG_STATS['log_entries']}  "
          f"opcode2={_DEBUG_STATS['opcode2']}  "
          f"decoded={_DEBUG_STATS['decoded']}  "
          f"candle_updates={_DEBUG_STATS['candle_updates']}  "
          f"currency={CURRENCY!r}  "
          f"candles={len(CANDLES)}")


def websocket_log():
    global CURRENCY, CURRENCY_CHANGE, CURRENCY_CHANGE_DATE, LAST_REFRESH, PERIOD, CANDLES
    _debug_report()
    try:
        current_symbol = driver.find_element(by=By.CLASS_NAME, value='current-symbol').text
        if current_symbol != CURRENCY:
            CURRENCY = current_symbol
            CURRENCY_CHANGE = True
            CURRENCY_CHANGE_DATE = datetime.now()
            print(f'[status] currency changed to {current_symbol!r}')
    except Exception:
        pass

    if CURRENCY_CHANGE and CURRENCY_CHANGE_DATE < datetime.now() - timedelta(seconds=5):
        driver.refresh()  # refresh page to cut off unwanted signals
        CURRENCY_CHANGE = False
        CANDLES = []
        PERIOD = 0

    try:
        entries = driver.get_log('performance')
    except Exception as e:
        print(f'[status] get_log failed: {e}')
        return
    _DEBUG_STATS['log_entries'] += len(entries)

    for wsData in entries:
        message = json.loads(wsData['message'])['message']
        response = message.get('params', {}).get('response', {})
        if response.get('opcode', 0) == 2 and not CURRENCY_CHANGE:
            _DEBUG_STATS['opcode2'] += 1
            payload_str = base64.b64decode(response['payloadData']).decode('utf-8')
            try:
                data = json.loads(payload_str)
                _DEBUG_STATS['decoded'] += 1
            except Exception:
                continue
            if 'asset' in data and 'candles' in data:  # 5m
                PERIOD = data['period']
                CANDLES = list(reversed(data['candles']))  # timestamp open close high low
                CANDLES.append([CANDLES[-1][0] + PERIOD, CANDLES[-1][1], CANDLES[-1][2], CANDLES[-1][3], CANDLES[-1][4]])
                for tstamp, value in data['history']:
                    tstamp = int(float(tstamp))
                    CANDLES[-1][2] = value  # set close all the time
                    if value > CANDLES[-1][3]:  # set high
                        CANDLES[-1][3] = value
                    elif value < CANDLES[-1][4]:  # set low
                        CANDLES[-1][4] = value
                    if tstamp % PERIOD == 0:
                        if tstamp not in [c[0] for c in CANDLES]:
                            CANDLES.append([tstamp, value, value, value, value])
                print(f'📊 Got {len(CANDLES)} candles for {data["asset"]}')
            try:
                current_value = data[0][2]
                CANDLES[-1][2] = current_value  # set close all the time
                if current_value > CANDLES[-1][3]:  # set high
                    CANDLES[-1][3] = current_value
                elif current_value < CANDLES[-1][4]:  # set low
                    CANDLES[-1][4] = current_value
                tstamp = int(float(data[0][1]))
                if tstamp % PERIOD == 0:
                    if tstamp not in [c[0] for c in CANDLES]:
                        try:
                            check_data()
                        except Exception as e:
                            print(e)
                        CANDLES.append([tstamp, current_value, current_value, current_value, current_value])
            except:
                pass


if __name__ == '__main__':
    load_web_driver()
    import time as _t
    print(f'{EMO_WAIT} waiting for data... (log in to PO and open the demo trade room)')
    while True:
        websocket_log()
        _t.sleep(0.25)  # was a tight loop, hammering CPU and the perf-log API
