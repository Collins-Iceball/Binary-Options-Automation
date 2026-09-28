import os
import undetected_chromedriver as uc

user_driver = os.path.expanduser('~/.local/share/undetected_chromedriver/chromedriver')
print('driver path:', user_driver)
print('driver exists:', os.path.exists(user_driver))
print('driver readable:', os.access(user_driver, os.R_OK))

print('Launching chrome...')
options = uc.ChromeOptions()
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')

driver = uc.Chrome(
    options=options,
    version_main=153,
    browser_executable_path='/usr/bin/google-chrome',
    driver_executable_path=user_driver,
)
print('Chrome launched OK')
print('Version:', driver.capabilities.get('version'))
driver.quit()
print('Done.')
