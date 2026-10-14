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
PURE_SRC = rng.c world.c loot.c biome.c fov.c creatures.c classes.c recipes.c deeds.c narrative.c pool.c stamps.c compose.c weather.c names.c trade.c bearing.c
TEST_SRC = test/test_main.c $(PURE_SRC)
TEST_BIN = test/run_tests

.PHONY: test clean shots

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
	python3 test/pbm2png.py test/shots/sheet.png test/shots/*.pbm

# Render-rule tests: real renderers against the canvas shim (test/shim).
RENDER_TEST_BIN = test/run_render_tests

test:
	$(CC) $(CFLAGS) $(TEST_SRC) -o $(TEST_BIN)
	./$(TEST_BIN)
	$(CC) $(CFLAGS) -Itest/shim test/test_render.c render_fpv.c $(PURE_SRC) -o $(RENDER_TEST_BIN)
	./$(RENDER_TEST_BIN)

clean:
	rm -f $(TEST_BIN) $(SHOT_BIN) $(RENDER_TEST_BIN)
	rm -rf test/shots
