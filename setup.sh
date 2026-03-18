#!/bin/bash

echo "--- [SANCTUM TERMINAL: INITIALIZING] ---"

# 1. Environment Check
if [ ! -d ".venv" ]; then
    echo "[!] .venv not found. Creating environment..."
    python3 -m venv .venv
fi

# 2. Dependency Sync
echo "[+] Syncing core dependencies..."
./.venv/bin/pip install ursina psutil requests numpy

# 3. Asset Displacement (The macOS fix)
echo "[+] Localizing engine assets..."
mkdir -p textures models
cp -r ./.venv/lib/python3.12/site-packages/ursina/textures/* ./textures/ 2>/dev/null
cp -r ./.venv/lib/python3.12/site-packages/ursina/models/* ./models/ 2>/dev/null

# 4. Alias Injection
if ! grep -q "alias project=" ~/.zshrc; then
    echo "[+] Injecting 'project' alias into ~/.zshrc..."
    echo "alias project='source $(pwd)/.venv/bin/activate && python3 $(pwd)/viewport.py'" >> ~/.zshrc
    echo "[!] Run 'source ~/.zshrc' to finalize."
else
    echo "[*] Alias 'project' already exists."
fi

echo "--- [INITIATION COMPLETE] ---"