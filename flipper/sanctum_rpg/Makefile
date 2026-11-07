# Host test harness for the deterministic core (NOT the .fap build).
#
# The .fap is built with `ufbt` (uses application.fam). This Makefile is
# only for `make test`: it compiles the PLATFORM-INDEPENDENT modules with
# plain host gcc/clang and runs the assertion harness. No Flipper SDK.
#
# Only pure modules go here — anything that includes <furi.h> or
# <storage/storage.h> (save_io.c, deltas.c) is NOT host-compilable until
# its pure logic is split out (planned: serializer split).

CC ?= cc
CFLAGS = -std=c11 -Wall -Wextra -Werror -O0 -g -I. -DSANCTUM_RPG_HOST_TEST

# deeds.c is host-testable via the SANCTUM_RPG_HOST_TEST macro — its
# Flipper-side I/O paths are #ifdef'd out under the host build, leaving
# the pure event-table + axis-rollup logic exposed for assertions.
PURE_SRC = facing.c afflict.c hollow.c cast.c arc.c dead.c corruption.c effort.c ritual.c figure.c pixkit.c terrain.c style.c region.c quirk.c site.c sky.c rng.c world.c loot.c biome.c fov.c creatures.c classes.c recipes.c deeds.c narrative.c pool.c stamps.c compose.c weather.c names.c trade.c bearing.c
TEST_SRC = test/test_main.c $(PURE_SRC)
TEST_BIN = test/run_tests

.PHONY: test clean shots host host-ref host-fixtures game-pure

# Host screenshots: the real renderers against test/shim (a RAM canvas).
# Writes test/shots/*.pbm + test/shots/sheet.png. Not part of `make test`.
SHOT_BIN = test/shot
SHOT_SCENES = 12345678:0:0:a 12345678:1:0:a 12345678:0:1:a CAFEBABE:0:0:a CAFEBABE:2:1:a DEADBEEF:0:0:a DEADBEEF:1:1:a 0BADF00D:0:0:a
shots:
	$(CC) $(CFLAGS) -Itest/shim test/shot.c render_fpv.c $(PURE_SRC) -o $(SHOT_BIN)
	mkdir -p test/shots
	@for s in $(SHOT_SCENES); do \
	  set -- $$(echo $$s | tr ':' ' '); \
	  ./$(SHOT_BIN) fpv $$1 $$2 $$3 $$4 test/shots/fpv_$$1_$$2_$$3_$$4.pbm || exit 1; \
	done
	python3 test/pbm2png.py test/shots/sheet.png test/shots/fpv_*.pbm
	@set -e; for s in 0:0:1:0 3:4:2:3 2:1:2:0 4:7:1:3 1:5:3:1 0:2:2:2; do \
	  set -- $$(echo $$s | tr ':' ' '); \
	  ./$(SHOT_BIN) scene 12345678 $$1 $$2 $$3 $$4 test/shots/scene_$$1_$$2_$$3_$$4.pbm; \
	done
	python3 test/pbm2png.py test/shots/scenes.png test/shots/scene_*.pbm
	rm -f test/shots/terrain_*.pbm
	./$(SHOT_BIN) terrainset test/shots
	python3 test/pbm2png.py test/shots/terrain.png --cols 3 test/shots/terrain_*.pbm
	./$(SHOT_BIN) field 0 test/shots/field_0.pbm
	./$(SHOT_BIN) field 1 test/shots/field_1.pbm
	python3 test/pbm2png.py test/shots/fields.png --cols 1 test/shots/field_*.pbm
	@set -e; for st in 0 1 2 3 4 5 6 7 8 9 10; do ./$(SHOT_BIN) stylefield $$st test/shots/style_$$st.pbm; done
	python3 test/pbm2png.py test/shots/styles.png --cols 1 test/shots/style_*.pbm
	@set -e; for st in 0 2 3 5 6 7 8 9; do for d in 1 2 4; do ./$(SHOT_BIN) wall $$st $$d test/shots/wall_$${st}_$${d}.pbm; done; done
	python3 test/pbm2png.py test/shots/walls.png --cols 3 test/shots/wall_*.pbm
	@set -e; for s in 12345678:4:-2 12345678:7:1 12345678:1:-5 12345678:1:1 12345678:4:1 12345678:7:-5 12345678:7:-8 CAFEBABE:1:-2; do \
	  set -- $$(echo $$s | tr ':' ' '); \
	  ./$(SHOT_BIN) fpv $$1 $$2 $$3 a test/shots/real_$$1_$$2_$$3.pbm; \
	done
	python3 test/pbm2png.py test/shots/real.png --cols 2 test/shots/real_*.pbm
	@set -e; for v in 7:2:1 6:2:1 4:2:1 9:5:0 8:0:2 4:0:1 3:5:1 12:3:3; do \
	  set -- $$(echo $$v | tr ':' ' '); \
	  ./$(SHOT_BIN) span H $$1 $$2 $$3 test/shots/span_$$1_$$2_$$3.pbm; \
	done
	python3 test/pbm2png.py test/shots/spans.png --cols 2 test/shots/span_*.pbm
	@set -e; rm -f test/shots/map_*.pbm; for s in CAFEBABE:0:0 DEADBEEF:0:0 12345678:4:-2 12345678:1:-5 12345678:4:1 12345678:7:-5 12345678:7:-8 00000001:-3:5 12345678:5:-1 CAFEBABE:-7:-5; do \
	  set -- $$(echo $$s | tr ':' ' '); \
	  ./$(SHOT_BIN) map $$1 $$2 $$3 test/shots/map_$$1_$$2_$$3.pbm; \
	done
	python3 test/pbm2png.py test/shots/map.png --cols 2 test/shots/map_*.pbm
	@set -e; rm -f test/shots/gate_*.pbm; for s in 12345678:0:0 12345678:2:0 CAFEBABE:0:2 DEADBEEF:2:2; do \
	  set -- $$(echo $$s | tr ':' ' '); \
	  ./$(SHOT_BIN) gatemap $$1 $$2 $$3 test/shots/gate_map_$$1_$$2_$$3.pbm; \
	 done
	./$(SHOT_BIN) gatefpv 12345678 2 0 1 13 4 test/shots/gate_fpv_a.pbm
	./$(SHOT_BIN) gatefpv DEADBEEF 2 2 1 12 2 test/shots/gate_fpv_b.pbm
	./$(SHOT_BIN) gatefpv DEADBEEF 2 2 2 6 2 test/shots/gate_fpv_c.pbm
	python3 test/pbm2png.py test/shots/gate_map.png --cols 2 test/shots/gate_map_*.pbm
	python3 test/pbm2png.py test/shots/gate_fpv.png --cols 1 test/shots/gate_fpv_*.pbm
	./$(SHOT_BIN) sites test/shots/sites.pbm
	python3 test/pbm2png.py test/shots/sites.png --scale 6 --cols 1 test/shots/sites.pbm
	./$(SHOT_BIN) mouths test/shots/mouths.pbm
	python3 test/pbm2png.py test/shots/mouths.png --scale 4 --cols 1 test/shots/mouths.pbm
	@set -e; for v in 0:0:0:0 1:-1:1:1 2:2:0:2; do set -- $$(echo $$v | tr ':' ' '); \
	  ./$(SHOT_BIN) pocket 12345678 $$1 $$2 0 $$4 test/shots/pocket_$$1_$$2_$$4.pbm; done
	python3 test/pbm2png.py test/shots/pockets.png --scale 3 --cols 1 test/shots/pocket_*.pbm
	@for f in 0 1 2 3 4; do \
	  ./$(SHOT_BIN) lineup $$f test/shots/lineup_$$f.pbm || exit 1; \
	  python3 test/pbm2png.py test/shots/lineup_$$f.png --scale 3 --cols 1 test/shots/lineup_$$f.pbm; \
	done

# Render-rule tests: real renderers against the canvas shim (test/shim).
RENDER_TEST_BIN = test/run_render_tests

test:
	$(CC) $(CFLAGS) $(TEST_SRC) -o $(TEST_BIN)
	./$(TEST_BIN)
	$(CC) $(CFLAGS) -Itest/shim test/test_render.c render_fpv.c $(PURE_SRC) -o $(RENDER_TEST_BIN)
	./$(RENDER_TEST_BIN)

# The host reference run: the whole app as the device builds it (the shell
# sanctum_rpg.c, the rules game.c, the screens screens.c, save_io.c,
# deltas.c) built against test/host/shim (a stand-in Flipper SDK:
# an SD card in a folder, a scripted clock, random source and buttons), driven
# by test/host/scripts. Each script writes a trace (every key, every screen,
# a hash of every frame, the player, the world, the files) to build/host/out.
# `make host` checks the traces against test/host/ref.sha256, so a change
# that should not alter play can prove it didn't. `make host-ref` re-records
# the sums after a change that is meant to. Built WITHOUT
# SANCTUM_RPG_HOST_TEST: the deeds' real file I/O runs too.
HOST_CFLAGS = -std=c11 -Wall -Wextra -Werror -Wno-unused-parameter -O0 -g -I. -Itest/host/shim -D_DEFAULT_SOURCE -D_DARWIN_C_SOURCE
HOST_BIN = build/host/sanctum_host
host:
	mkdir -p build/host
	rm -f build/host/sums.txt
	$(MAKE) game-pure
	$(CC) $(HOST_CFLAGS) test/host/host_main.c game.c screens.c save_io.c deltas.c render_fpv.c $(PURE_SRC) -o $(HOST_BIN)
	rm -rf build/host/out
	sh test/host/run.sh $(HOST_BIN) build/host/out
	cd build/host/out && shasum -a 256 *.trace > ../sums.txt
	diff test/host/ref.sha256 build/host/sums.txt && echo "host: every trace matches the reference"
# The rules call no Flipper SDK: game.c compiles with the plain host flags
# and no shim on the include path, so any SDK header it reaches fails here.
game-pure:
	mkdir -p build/host
	$(CC) -std=c11 -Wall -Wextra -Werror -I. -c game.c -o build/host/game_pure.o
	@echo "game-pure: game.c compiles without the Flipper SDK"
host-ref:
	$(MAKE) host || true
	cp build/host/sums.txt test/host/ref.sha256
# The scripts' saves: real places in seed 270369, found by the game's own pure
# code (test/host/find.c). Regenerate after a WORLDGEN change, then host-ref.
HOST_FIXTURES = hollow hollow_skill site rite fight vendor quest forge
host-fixtures:
	mkdir -p build/host
	$(CC) $(CFLAGS) -Wno-unused-parameter test/host/find.c $(PURE_SRC) -o build/host/find
	@for f in $(HOST_FIXTURES); do rm -rf test/host/fixtures/$$f; ./build/host/find $$f 270369 test/host/fixtures/$$f || exit 1; done

clean:
	rm -f $(TEST_BIN) $(SHOT_BIN) $(RENDER_TEST_BIN)
	rm -rf test/shots build/host
