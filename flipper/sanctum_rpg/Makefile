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
PURE_SRC = rng.c world.c loot.c biome.c fov.c creatures.c classes.c recipes.c deeds.c narrative.c pool.c stamps.c compose.c weather.c names.c trade.c
TEST_SRC = test/test_main.c $(PURE_SRC)
TEST_BIN = test/run_tests

.PHONY: test clean
test:
	$(CC) $(CFLAGS) $(TEST_SRC) -o $(TEST_BIN)
	./$(TEST_BIN)

clean:
	rm -f $(TEST_BIN)
