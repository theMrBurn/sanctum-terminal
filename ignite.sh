#!/bin/bash
# Sanctum Terminal - M2 Pro Bootstrapper (QA Verified)

export PYTHONPATH=.:src
clear

echo "--- [IGNITING SANCTUM VIEWPORT] ---"
echo "HARDWARE: Apple M2 Pro (12-Core)"
echo "LOCATION: Portland / Miami Sensor Sync"
echo "MODE: Standard Priority (M2 Native)"
echo "-----------------------------------"

# Launch without nice to avoid permission issues
./.venv/bin/python sanctum.py