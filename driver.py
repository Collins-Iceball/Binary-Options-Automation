import os
import platform
import subprocess

import undetected_chromedriver as uc


def _chrome_major_version():
    """Detect the installed Google Chrome's major version.
    Falls back to 153 if detection fails."""
    try:
        out = subprocess.run(['/usr/bin/google-chrome', '--version'],
                             capture_output=True, text=True, timeout=5)
        # "Google Chrome 153.0.8010.47" -> 153
        return int(out.stdout.strip().split()[2].split('.')[0])
    except Exception:
        return 153


def get_driver():
    options = uc.ChromeOptions()
    options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
    options.add_argument('--ignore-ssl-errors')
    options.add_argument('--ignore-certificate-errors')
    options.add_argument('--ignore-certificate-errors-spki-list')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    # options.add_argument('--headless=new')

    username = os.environ.get('USER', os.environ.get('USERNAME'))
    os_platform = platform.platform().lower()

    # Shared profile with po_bot_v2.py / closeoption_bot.py so login carries over.
    if 'macos' in os_platform:
        path_default = fr'/Users/{username}/Library/Application Support/Google/Chrome/Trading Bot Profile'
    elif 'windows' in os_platform:
        path_default = fr'C:\Users\{username}\AppData\Local\Google\Chrome\User Data\Trading Bot Profile'
    elif 'linux' in os_platform:
        path_default = '~/.config/google-chrome/Trading Bot Profile'
    else:
        path_default = ''
    options.add_argument(fr'--user-data-dir={os.path.expanduser(path_default)}')

    # Force the local user-owned chromedriver. uc patches this binary in place,
    # so it must not be the root-owned /usr/bin one, and it must match Chrome's
    # major version - otherwise uc tries to download its own (which breaks on
    # version mismatch).
    user_driver = os.path.expanduser('~/.local/share/undetected_chromedriver/chromedriver')
    major = _chrome_major_version()

    kwargs = {
        'options': options,
        'version_main': major,
        'browser_executable_path': '/usr/bin/google-chrome',
    }
    if os.path.exists(user_driver):
        kwargs['driver_executable_path'] = user_driver

    return uc.Chrome(**kwargs)


companies = {
    'Apple OTC': '#AAPL_otc',
    'American Express OTC': '#AXP_otc',
    'Boeing Company OTC': '#BA_otc',
    'Johnson & Johnson OTC': '#JNJ_otc',
    "McDonald's OTC": '#MCD_otc',
    'Tesla OTC': '#TSLA_otc',
    'Amazon OTC': 'AMZN_otc',
    'VISA OTC': 'VISA_otc',
    'Netflix OTC': 'NFLX_otc',
    'Alibaba OTC': 'BABA_otc',
    'ExxonMobil OTC': '#XOM_otc',
    'FedEx OTC': 'FDX_otc',
    'FACEBOOK INC OTC': '#FB_otc',
    'Pfizer Inc OTC': '#PFE_otc',
    'Intel OTC': '#INTC_otc',
    'TWITTER OTC': 'TWITTER_otc',
    'Microsoft OTC': '#MSFT_otc',
    'Cisco OTC': '#CSCO_otc',
    'Citigroup Inc OTC': 'CITI_otc',
}
