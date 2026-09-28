import base64, json, os, sys, time
from collections import Counter
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By

PLATFORM_URLS = {
    'pocketoption': 'https://pocketoption.com/en/cabinet/demo-quick-high-low/',
    'binarium': 'https://binarium.com',
    'binaryfunded': 'https://binaryfunded.com',
    'binodex': 'https://binodex.app',
    'binolla': 'https://binolla.com',
    'binomo': 'https://binomo.com',
    'casatrade': 'https://trade.casatrade.com',
    'closeoption': 'https://www.closeoption.com',
    'deriv': 'https://home.deriv.com',
    'expertoption': 'https://app.expertoption.com',
    'iqoption': 'https://iqoption.com',
    'olymptrade': 'https://olymptrade.com',
    'quotex': 'https://qxbroker.com',
}


def get_driver():
    options = uc.ChromeOptions()
    options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
    options.set_capability('pageLoadStrategy', 'none')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument(f'--user-data-dir={os.path.expanduser("~/.config/google-chrome/Recon Profile")}')
    return uc.Chrome(options=options, version_main=153, browser_executable_path='/usr/bin/google-chrome')


def capture_ws(driver, seconds, label):
    print(f'\n📡 Capturing WS traffic for {seconds}s — {label}...')
    stats, key_counter, samples = Counter(), Counter(), {}
    end = time.time() + seconds
    while time.time() < end:
        try:
            entries = driver.get_log('performance')
        except Exception:
            entries = []
        for e in entries:
            try:
                msg = json.loads(e['message'])['message']
            except Exception:
                continue
            resp = msg.get('params', {}).get('response', {})
            opcode = resp.get('opcode', 0)
            stats[f'opcode_{opcode}'] += 1
            if opcode not in (1, 2):
                continue  # only 1 (text) and 2 (binary) carry real payloads per RFC 6455
            raw_payload = resp.get('payloadData', '')
            if opcode == 2:
                # binary frame - PO and similar send base64-encoded UTF-8 JSON this way
                try:
                    text = base64.b64decode(raw_payload).decode('utf-8')
                except Exception:
                    continue
            else:
                # opcode 1 - text frame, CDP already gives this as plain text, not base64
                text = raw_payload
            # try JSON first
            frame_type = f'op{opcode}'
            try:
                data = json.loads(text)
                if isinstance(data, dict):
                    keys = tuple(sorted(data.keys()))
                    key_counter[('dict', frame_type, keys)] += 1
                    if ('dict', frame_type, keys) not in samples:
                        samples[('dict', frame_type, keys)] = text[:500]
                elif isinstance(data, list):
                    shape = f'list[{len(data)}]'
                    key_counter[('list', frame_type, shape)] += 1
                    if ('list', frame_type, shape) not in samples:
                        samples[('list', frame_type, shape)] = text[:500]
            except Exception:
                # not JSON - engine.io framing like "42[...]" or "0{...}" etc.
                prefix = text[:2] if len(text) >= 2 else text
                key_counter[('raw', frame_type, f'prefix_{prefix!r}')] += 1
                if ('raw', frame_type, f'prefix_{prefix!r}') not in samples:
                    samples[('raw', frame_type, f'prefix_{prefix!r}')] = text[:500]
        time.sleep(0.4)
    return stats, key_counter, samples


def find_element_context(driver, label, keyword_hints):
    """
    Instead of guessing a selector, search the live DOM text for elements
    whose innerText or class name loosely matches what we're looking for,
    and print the surrounding HTML so a human can pick the real selector.
    """
    print(f'\n🔍 {label}')
    js = """
    const hints = arguments[0].map(h => h.toLowerCase());
    const results = [];
    const all = document.querySelectorAll('*');
    for (const el of all) {
        const txt = (el.innerText || '').trim().toLowerCase();
        const cls = (el.className || '').toString().toLowerCase();
        const id = (el.id || '').toLowerCase();
        for (const h of hints) {
            if ((txt && txt.length < 40 && txt.includes(h)) || cls.includes(h) || id.includes(h)) {
                results.push({
                    tag: el.tagName,
                    id: el.id || null,
                    className: el.className ? el.className.toString() : null,
                    text: (el.innerText || '').trim().slice(0, 60),
                    outerHTML: el.outerHTML.slice(0, 300)
                });
                break;
            }
        }
        if (results.length >= 8) break;
    }
    return results;
    """
    try:
        results = driver.execute_script(js, keyword_hints)
    except Exception as ex:
        print(f'  [ERR] {ex}')
        return
    if not results:
        print('  -- no matches found for hints:', keyword_hints)
        return
    for r in results:
        print(f"  <{r['tag']}> id={r['id']!r} class={r['className']!r}")
        print(f"    text: {r['text']!r}")
        print(f"    html: {r['outerHTML']}")
        print()


def dump_all_inputs(driver):
    print('\n🔍 ALL <input> elements on page (amount field candidates)')
    js = """
    return Array.from(document.querySelectorAll('input')).map(el => ({
        type: el.type,
        id: el.id || null,
        className: el.className ? el.className.toString() : null,
        placeholder: el.placeholder || null,
        value: el.value || null,
        outerHTML: el.outerHTML.slice(0, 250)
    }));
    """
    try:
        inputs = driver.execute_script(js)
    except Exception as ex:
        print(f'  [ERR] {ex}')
        return
    for i, inp in enumerate(inputs):
        print(f"  [{i}] type={inp['type']} id={inp['id']!r} class={inp['className']!r} placeholder={inp['placeholder']!r} value={inp['value']!r}")
        print(f"      html: {inp['outerHTML']}")


def choose_platform():
    names = list(PLATFORM_URLS.keys())
    print('\nAvailable platforms:')
    for i, name in enumerate(names, 1):
        print(f'  {i}. {name}  ({PLATFORM_URLS[name]})')
    while True:
        choice = input('\nSelect a number (or type the name directly): ').strip().lower()
        if choice.isdigit() and 1 <= int(choice) <= len(names):
            return names[int(choice) - 1]
        if choice in PLATFORM_URLS:
            return choice
        print('  Not recognized, try again.')


def main(platform=None):
    if platform is None:
        platform = choose_platform()
    url = PLATFORM_URLS.get(platform, platform)
    print(f'🚀 Opening {url} ...')
    driver = get_driver()
    driver.get(url)
    input('\n>>> LOG IN if needed and open the TRADING terminal (chart + call/put visible), then press ENTER...')

    # Phase 1: idle capture (just candles/subscription traffic)
    stats1, keys1, samples1 = capture_ws(driver, 15, 'idle (just watching the chart)')

    print('\n>>> Now PLACE ONE DEMO TRADE (any direction), then press ENTER as soon as you click Buy/Call...')
    input()

    # Phase 2: capture right around the trade placement
    stats2, keys2, samples2 = capture_ws(driver, 20, 'around trade placement + result')

    print('\n' + '=' * 70)
    print('=== PHASE 1 (idle) — OPCODE STATS ===')
    for k, v in stats1.most_common():
        print(f'  {k}: {v}')
    print('\n=== PHASE 1 (idle) — TOP FRAME SHAPES ===')
    for (kind, frame_type, shape), cnt in keys1.most_common(10):
        print(f'  {cnt}x [{kind}/{frame_type}] {shape}')
        print(f'      sample: {samples1[(kind, frame_type, shape)]}')

    print('\n' + '=' * 70)
    print('=== PHASE 2 (trade) — OPCODE STATS ===')
    for k, v in stats2.most_common():
        print(f'  {k}: {v}')
    print('\n=== PHASE 2 (trade) — TOP FRAME SHAPES ===')
    for (kind, frame_type, shape), cnt in keys2.most_common(15):
        print(f'  {cnt}x [{kind}/{frame_type}] {shape}')
        print(f'      sample: {samples2[(kind, frame_type, shape)]}')

    print('\n' + '=' * 70)
    print('=== DOM RECON ===')
    find_element_context(driver, 'BALANCE (searching for numbers/currency/balance/wallet)',
                          ['balance', 'wallet', 'deposit'])
    find_element_context(driver, 'CALL / BUY BUTTON', ['call', 'buy', 'up', 'higher'])
    find_element_context(driver, 'PUT / SELL BUTTON', ['put', 'sell', 'down', 'lower'])
    find_element_context(driver, 'PAYOUT %', ['payout', '%'])
    find_element_context(driver, 'CLOSED TRADES / HISTORY / RESULT', ['deal', 'trade', 'history', 'closed', 'result'])
    dump_all_inputs(driver)

    print('\n' + '=' * 70)
    input('\nPress ENTER to close Chrome...')
    driver.quit()


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else None)
