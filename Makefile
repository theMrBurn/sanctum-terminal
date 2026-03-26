.PHONY: clean factory test test-unit test-quest run trunk-check

# ── Clean ─────────────────────────────────────────────────────────────────────
clean:
	rm -rf data/live_assets/*
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

# ── Asset Pipeline ────────────────────────────────────────────────────────────
factory:
	PYTHONPATH=. ./.venv/bin/python utils/VoxelFactory.py

# ── Tests ─────────────────────────────────────────────────────────────────────
test:
	PYTHONPATH=. ./.venv/bin/python -m pytest tests/ \
		--ignore=tests/unit/test_observer.py \
		-v --tb=short

test-unit:
	PYTHONPATH=. ./.venv/bin/python -m pytest tests/unit/ \
		--ignore=tests/unit/test_observer.py \
		-v --tb=short

test-quest:
	PYTHONPATH=. ./.venv/bin/python -m pytest tests/test_quest_engine.py \
		-v --tb=short

# ── Lint ──────────────────────────────────────────────────────────────────────
trunk-check:
	trunk check core/systems/quest_engine.py \
		core/systems/biome_registry.py \
		utils/VoxelFactory.py \
		core/vault.py \
		core/input_handler.py \
		SimulationRunner.py \
		FirstLight.py

# ── Run ───────────────────────────────────────────────────────────────────────
run:
	PYTHONPATH=. ./.venv/bin/python SimulationRunner.py