# Binary Options Automation — Collins_Obi
# https://github.com/Collins-Iceball/Binary-Options-Automation
#
# Ops notes for this machine. Prefer the launcher for day-to-day use.

echo 'export DOTNET_ROOT=$HOME/.dotnet' >> ~/.bashrc
echo 'export PATH=$PATH:$DOTNET_ROOT:$DOTNET_ROOT/tools' >> ~/.bashrc
source ~/.bashrc

# --- Recommended daily launch ---
cd "/home/collins/Me/Software/Trading Bot GUI/pocket_option_trading_bot"
source .venv/bin/activate
export DOTNET_ROOT=$HOME/.dotnet
export PATH=$PATH:$DOTNET_ROOT:$DOTNET_ROOT/tools
python3 -u startup.py

# Direct Pocket Option (no launcher):
# python3 -u pocketoption_bot.py

# Direct CloseOption GUI:
# python3 -u closeoption_gui.py


# 1. Kill any zombie Chrome/chromedriver processes
pkill -f "Trading Bot Profile"
pkill -f chromedriver

# 2. Clear stale profile locks
rm -f "$HOME/.config/google-chrome/Trading Bot Profile/SingletonLock"
rm -f "$HOME/.config/google-chrome/Trading Bot Profile/SingletonSocket"
rm -f "$HOME/.config/google-chrome/Trading Bot Profile/SingletonCookie"

# 3. Go to the bot folder
cd "/home/collins/Me/Software/Trading Bot GUI/pocket_option_trading_bot"

# 4. Activate the virtual environment
source .venv/bin/activate

# 5. Load the .NET runtime (needed for the indicators)
export DOTNET_ROOT=$HOME/.dotnet
export PATH=$PATH:$DOTNET_ROOT:$DOTNET_ROOT/tools

# 6. Launch (launcher preferred; or pocketoption_bot.py directly)
python3 -u startup.py
# python3 -u pocketoption_bot.py



# 1. Kill ALL lingering Chrome and chromedriver processes to prevent lock conflicts
pkill -9 -f chrome
pkill -9 -f chromedriver
sleep 2

# 2. Reinstall Chrome using the .deb file already in your folder
sudo apt install -y --reinstall ./google-chrome-stable_current_amd64.deb

# 3. Verify the installation succeeded and check the version
google-chrome --version

# 4. Clear any stale profile locks just in case
rm -rf "$HOME/.config/google-chrome/Trading Bot Profile/Singleton*"

# 5. Launch the bot
python3 -u startup.py


ls -la "/home/collins/.config/google-chrome/Trading Bot Profile/Default/Preferences"
cp "/home/collins/.config/google-chrome/Trading Bot Profile/Default/Preferences" "/home/collins/.config/google-chrome/Trading Bot Profile/Default/Preferences.bak"
rm "/home/collins/.config/google-chrome/Trading Bot Profile/Default/Preferences"
python3 -u startup.py



# Fix for a change of Location

# 1. Go to the NEW folder (quotes are mandatory because of the space)
cd "/home/collins/Me/Software/Trading Bot GUI/pocket_option_trading_bot"

# 2. Kill any zombie Chrome/chromedriver processes
pkill -9 -f "Trading Bot Profile"
pkill -9 -f chromedriver
pkill -9 -f chrome

# 3. Clear stale profile locks
rm -f "$HOME/.config/google-chrome/Trading Bot Profile/SingletonLock"
rm -f "$HOME/.config/google-chrome/Trading Bot Profile/SingletonSocket"
rm -f "$HOME/.config/google-chrome/Trading Bot Profile/SingletonCookie"

# 4. Delete the broken virtual environment (moving a folder breaks venv symlinks)
rm -rf .venv

# 5. Create a fresh virtual environment
python3 -m venv .venv

# 6. Activate it
source .venv/bin/activate

# 7. Reinstall all required packages (selenium, undetected-chromedriver, etc.)
pip install -r requirements.txt

# 8. Load the .NET runtime (needed for the indicators)
export DOTNET_ROOT=$HOME/.dotnet
export PATH=$PATH:$DOTNET_ROOT:$DOTNET_ROOT/tools

# 9. Launch the bot
python3 -u startup.py


# 1. Install the missing stock_indicators package
pip install stock_indicators

# 2. Install the rest of the required packages just in case
pip install -r requirements.txt

# 3. Load the .NET runtime environment variables (required for stock_indicators)
export DOTNET_ROOT=$HOME/.dotnet
export PATH=$PATH:$DOTNET_ROOT:$DOTNET_ROOT/tools

# 4. Launch the bot
python3 -u startup.py
