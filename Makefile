.PHONY: clean factory test test-unit test-quest seed-db meshes brain brain-cavern brain-vector brain-workroom brain-volley vector terminal terminal-inline godot-export godot-export-cavern godot-meshes

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

# ── Run ───────────────────────────────────────────────────────────────────────
# Legacy Panda3D-era targets (run, lab, room, creation, theater, dungeon,
# shadowbox, cavern, viewer, trunk-check) removed 2026-05-07 audit A14
# — their entry-point scripts (cavern.py, creation_lab.py, dungeon.py,
# FirstLight.py, main.py, room_lab.py, shadowbox_dungeon.py,
# simulation_theater.py, SimulationRunner.py, template_viewer.py) are
# archived under docs/archive/panda3d/top_level/. The live pipeline runs
# brain + vector terminal exclusively.

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

# Brain for vector_terminal use — same stamp_world mode as brain-cavern but
# skips the meshes prereq since vector_terminal renders wireframes from
# kind_config bounds, never loads GLB meshes. Pair with `make vector`.
brain-vector:
	SANCTUM_STAMP=1 PYTHONPATH=. ./.venv/bin/python brain_server.py cavern

# Brain for the vector-workroom authoring sandbox. Per
# `.claude/feature/feat_vector-workroom.md`. Empty procedural pool,
# flat 1m grid floor; world_seeds placed via BUILD mode are the only
# content. Pair with `make vector`.
brain-workroom:
	SANCTUM_STAMP=1 PYTHONPATH=. ./.venv/bin/python brain_server.py workroom

# Brain for make-brain-ping_pong V1 — clean-room arcade volley chamber.
# Per `.claude/feature/feat_make-brain-ping-pong.md`. 12×12×12 cube
# wireframe room, vault-backed profile/run telemetry, keyboard console
# for live tuning. Pair with `make vector`.
brain-volley:
	SANCTUM_STAMP=1 PYTHONPATH=. ./.venv/bin/python brain_server.py volley_chamber

# Launch the vector_terminal client (assumes a brain is already up on :9877).
vector:
	PYTHONPATH=. ./.venv/bin/python -m clients.vector_terminal.main
