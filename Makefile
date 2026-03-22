# --- [SANCTUM TERMINAL MASTER CONTROL] ---
PYTHON = ./.venv/bin/python
export PYTHONPATH := .

.PHONY: test seed clean scout crawl stress-test run

# 1. TDD Lifecycle: Pure Initialization & World Logic Regression
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

# 5. Interactive RPG Engine (The Logic Walker)
crawl:
	@echo ">>> [SYSTEM] Initializing Interactive Logic Crawler..."
	$(PYTHON) systems/logic_walker.py

# 6. Scaling Stress Test (Target: Floor 25)
stress-test:
	@echo ">>> [STRESS] Validating Exponential Scaling at Floor 25..."
	$(PYTHON) -m pytest tests/test_world_regression.py::test_scaling_integrity_floor_25 -v

# 7. Run Main Application
run:
	@echo ">>> [SYSTEM] Booting Sanctum OS Engine..."
	$(PYTHON) main.py