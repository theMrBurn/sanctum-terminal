# --- [SANCTUM TERMINAL MASTER CONTROL] ---
PYTHON = ./.venv/bin/python
export PYTHONPATH := .:src

.PHONY: test seed ignite clean flush scout

# 1. TDD Lifecycle (The "Clean Room" Approach)
test:
	@echo ">>> [TDD] Initializing Sandboxed Vault..."
	$(PYTHON) tools/seed_vault.py
	$(PYTHON) -m pytest -vs tests/
	@echo ">>> [TDD] Tearing down Sandbox..."
	rm -f data/vault.db

# 2. Production Seeding (For manual flight)
seed:
	$(PYTHON) tools/seed_vault.py

# 3. Ignition
ignite:
	./ignite.sh

# 4. Deep Workspace Purge
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	rm -f sanctum.db
	rm -rf *.egg-info .pytest_cache
	@echo ">>> [CLEAN] Internal scaffolds cleared."

# 5. Diagnostic
scout:
	$(PYTHON) tools/scout_check.py