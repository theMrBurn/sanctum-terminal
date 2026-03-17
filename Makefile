# --- Configuration ---
PYTHON = /opt/homebrew/bin/python3.12
APP = sanctum.py
# Ensures src/ is in the path for all targets
ENV = export PYTHONPATH=.:src
# Default city if none is provided via 'city=name'
CITY ?= portland

.PHONY: install test status clean scout flush repair s q

# --- System ---
install:
	$(PYTHON) -m pip install -e . --break-system-packages

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	rm -rf *.egg-info .pytest_cache

test:
	$(ENV) && $(PYTHON) -m pytest -vs tests/

# --- Core Commands ---
# Usage: make status city=pdx
status:
	$(ENV) && $(PYTHON) $(APP) status $(CITY)

# Usage: make scout city=pdx
scout:
	$(ENV) && $(PYTHON) $(APP) scout $(CITY)

# --- Maintenance ---
flush:
	$(ENV) && $(PYTHON) $(APP) flush

repair:
	$(ENV) && $(PYTHON) $(APP) repair

# --- Tactical Shorthands (Aliases) ---
# High-speed status check
s:
	@$(ENV) && $(PYTHON) $(APP) status $(CITY)

# High-speed scout
q:
	@$(ENV) && $(PYTHON) $(APP) scout $(CITY)