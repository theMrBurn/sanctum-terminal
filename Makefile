.PHONY: clean factory test test-unit test-quest run seed-db trunk-check meshes brain brain-cavern

# ── Clean ─────────────────────────────────────────────────────────────────────
clean:
	rm -rf data/live_assets/*
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

# ── Asset Pipeline ────────────────────────────────────────────────────────────
factory:
	PYTHONPATH=. ./.venv/bin/python utils/VoxelFactory.py

# ── Database ──────────────────────────────────────────────────────────────────
seed-db:
	PYTHONPATH=. ./.venv/bin/python tools/seed_db.py

# ── Tests ─────────────────────────────────────────────────────────────────────
test:
	PYTHONPATH=. ./.venv/bin/python -m pytest tests/ \
		--ignore=tests/unit/test_observer.py \
		--ignore=tests/test_seed_engine.py \
		--ignore=tests/test_spawn_engine.py \
		--ignore=tests/test_biome_stack.py \
		--ignore=tests/test_active_pipeline.py \
		--ignore=tests/test_creation_lab_pipeline.py \
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

lab:
	PYTHONPATH=. ./.venv/bin/python main.py

room:
	PYTHONPATH=. ./.venv/bin/python room_lab.py

creation:
	PYTHONPATH=. ./.venv/bin/python creation_lab.py

theater:
	PYTHONPATH=. ./.venv/bin/python simulation_theater.py

dungeon:
	PYTHONPATH=. ./.venv/bin/python dungeon.py

shadowbox:
	PYTHONPATH=. ./.venv/bin/python shadowbox_dungeon.py

cavern:
	PYTHONPATH=. ./.venv/bin/python cavern.py

viewer:
	PYTHONPATH=. ./.venv/bin/python template_viewer.py

# Headless ASCII sanctum — the game at its bedrock. No Godot.
# `terminal` opens a new macOS Terminal window so the game runs in its
# own space, leaving your current shell free. `terminal-inline` runs it
# in the current shell (useful for piping input in tests / CI).
# Controls: wasd move, t tag, q quit.
terminal:
	@osascript \
	  -e 'tell application "Terminal" to activate' \
	  -e "tell application \"Terminal\" to do script \"cd '$$PWD' && make terminal-inline\""

terminal-inline:
	PYTHONPATH=. ./.venv/bin/python sanctum_terminal.py

# ── Godot Bridge ──────────────────────────────────────────────────────────────
godot-export:
	PYTHONPATH=. ./.venv/bin/python godot_export.py outdoor

godot-export-cavern:
	PYTHONPATH=. ./.venv/bin/python godot_export.py cavern

godot-meshes:
	PYTHONPATH=. ./.venv/bin/python tools/export_glb.py

# Regenerate every gen_kind_mesh-authored kind. Eliminates the
# invisible-build-step problem where editing tools/gen_kind_mesh.py
# does nothing visible until someone manually re-runs the script.
# Run this after any change to gen_kind_mesh.py before reloading
# Godot, or wire it as a dependency of brain-cavern / brain.
meshes:
	PYTHONPATH=. ./.venv/bin/python tools/gen_kind_mesh.py --all

# Brain server — both targets default to SANCTUM_STAMP=1 (pure-function
# stamp_world mode) so infinite walking works without manual env var.
# bc6ca1f added stamp_world / bucket_world as opt-in flags but never
# updated the launcher; the slow TileExchange path was leaking through
# as the silent default. Setting the env var here locks in the intended
# operating mode.
brain: meshes
	SANCTUM_STAMP=1 PYTHONPATH=. ./.venv/bin/python brain_server.py outdoor

brain-cavern: meshes
	SANCTUM_STAMP=1 PYTHONPATH=. ./.venv/bin/python brain_server.py cavern
