.PHONY: setup run test clean

# Respecting the .venv and Python 3.12 pathing
PYTHON := python3.12
VENV := .venv
BIN := $(VENV)/bin

# Creates the virtual environment and installs dependencies securely
setup:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -e .[dev]

# Runs the application with high-signal telemetry
run:
	$(BIN)/sanctum

# Executes the Pytest cycle for "Sandbox First" verification
test:
	$(BIN)/pytest tests/

# Wipes the environment to reset to the "Empty" state
clean:
	rm -rf $(VENV)
	rm -rf *.egg-info
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +