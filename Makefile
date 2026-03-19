# --- [SANCTUM TERMINAL MASTER CONTROL] ---
PYTHON = ./.venv/bin/python
export PYTHONPATH := .

.PHONY: test seed clean scout

# 1. TDD Lifecycle: Pure Initialization
test:
	@echo ">>> [TDD] Initializing Sandboxed Vault..."
	rm -f data/vault.db
	$(PYTHON) -m pytest -vs tests/
	@echo ">>> [TDD] Tearing down Sandbox..."
	rm -f data/vault.db

# 2. Production Seeding (Still available for manual overrides)
seed:
	$(PYTHON) tools/seed_vault.py

# 3. Deep Workspace Purge
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	rm -f data/vault.db
	rm -rf *.egg-info .pytest_cache
	@echo ">>> [CLEAN] Internal scaffolds cleared."

# 4. Diagnostic
scout:
	$(PYTHON) tools/scout_check.py