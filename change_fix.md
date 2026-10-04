# 1. Kill anything Chrome-related still holding the old profile
pkill -f chrome
pkill -f chromedriver
sleep 2

# 2. Move/rename the folder
# mv "/old/path/to/folder" "/new/path/to/folder" (uncheck the "#" if necessary
cd "/new/path/to/folder"

# 3. Nuke and rebuild the venv (it does NOT survive a move)
rm -rf .venv
python3 -m venv .venv
source .venv/bin/activate

# 4. Verify you're in the new venv, not the system python
which python3
which pip
# Both must show .../new/path/.venv/bin/... — if they show /usr/bin, stop and fix

# 5. Reinstall everything
pip install --upgrade pip
pip install customtkinter matplotlib undetected-chromedriver selenium stock-indicators pythonnet

# 6. Update the .desktop file path (if you made one)
#    and any hardcoded paths in your own scripts

# 7. Launch
python3 -u startup.py
