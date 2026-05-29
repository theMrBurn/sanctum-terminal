/*
 * Host test harness for Sanctum RPG's deterministic core.
 *
 * Compiles the PLATFORM-INDEPENDENT modules (rng, world) with plain
 * host gcc — no Flipper SDK — and asserts the properties the
 * prime-instance contract (spec 43 §14.0) depends on:
 *   - determinism (same seed → same everything)
 *   - the golden-master fingerprints (any drift = breaking world-gen
 *     change, must be caught here before it silently changes players'
 *     worlds OR diverges from the future PC port)
 *
 * Run with `make test` from the sanctum_rpg/ dir.
 *
 * This is the portability insurance the whole "Flipper is prime, PC
 * ports from it" decision rests on. Keep it green.
 */

#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "../biome.h"
#include "../fov.h"
#include "../loot.h"
#include "../rng.h"
#include "../world.h"

static int g_pass = 0;
static int g_fail = 0;

#define CHECK(cond, msg)                                            \
    do {                                                            \
        if(cond) {                                                  \
            g_pass++;                                               \
        } else {                                                    \
            g_fail++;                                               \
            printf("  FAIL: %s  (%s:%d)\n", (msg), __FILE__, __LINE__); \
        }                                                           \
    } while(0)

/* FNV-1a over the chunk tile grid + spawn — the chunk's fingerprint. */
static uint32_t chunk_fingerprint(const World* w) {
    uint32_t h = 2166136261u;
    for(int y = 0; y < WORLD_ROWS; y++) {
        for(int x = 0; x < WORLD_COLS; x++) {
            h ^= (uint8_t)w->tiles[y][x];
            h *= 16777619u;
        }
    }
    h ^= (uint32_t)(w->spawn_x & 0xFF);
    h *= 16777619u;
    h ^= (uint32_t)(w->spawn_y & 0xFF);
    h *= 16777619u;
    h ^= (uint32_t)w->biome;
    h *= 16777619u;
    return h;
}

/* ── rng ─────────────────────────────────────────────────────────── */

static void test_rng_determinism(void) {
    Rng a, b;
    rng_seed(&a, 12345);
    rng_seed(&b, 12345);
    int identical = 1;
    for(int i = 0; i < 1000; i++) {
        if(rng_next(&a) != rng_next(&b)) identical = 0;
    }
    CHECK(identical, "rng: same seed -> identical sequence");

    Rng c;
    rng_seed(&a, 12345);
    rng_seed(&c, 99999);
    int differs = 0;
    for(int i = 0; i < 100; i++) {
        if(rng_next(&a) != rng_next(&c)) differs = 1;
    }
    CHECK(differs, "rng: different seed -> different sequence");

    /* seed 0 must not collapse the generator */
    Rng z;
    rng_seed(&z, 0);
    CHECK(rng_next(&z) != 0, "rng: seed 0 promoted, not stuck");
}

static void test_rng_range_bounds(void) {
    Rng r;
    rng_seed(&r, 7);
    int in_bounds = 1;
    for(int i = 0; i < 100000; i++) {
        uint32_t v = rng_range(&r, 3, 17);
        if(v < 3 || v >= 17) in_bounds = 0;
    }
    CHECK(in_bounds, "rng_range: stays within [lo, hi)");

    rng_seed(&r, 1);
    CHECK(rng_range(&r, 5, 5) == 5, "rng_range: empty range returns lo");
    CHECK(rng_range(&r, 9, 4) == 9, "rng_range: inverted range returns lo");
}

/* chunk_seed must spread adjacent coords (no visible moire at borders) */
static void test_chunk_seed_spread(void) {
    uint32_t s00 = rng_chunk_seed(0xCAFEBABE, 0, 0);
    uint32_t s10 = rng_chunk_seed(0xCAFEBABE, 1, 0);
    uint32_t s01 = rng_chunk_seed(0xCAFEBABE, 0, 1);
    CHECK(s00 != s10 && s00 != s01 && s10 != s01, "chunk_seed: adjacent coords differ");
    CHECK(rng_chunk_seed(0, 0, 0) != 0, "chunk_seed: never returns 0");
}

/* ── world generation ────────────────────────────────────────────── */

static void test_chunk_determinism(void) {
    World a, b;
    world_generate_chunk(0xCAFEBABE, 0, 0, &a);
    world_generate_chunk(0xCAFEBABE, 0, 0, &b);
    CHECK(chunk_fingerprint(&a) == chunk_fingerprint(&b),
          "chunk: same (seed,cx,cy) regenerates byte-identical");

    World c;
    world_generate_chunk(0xCAFEBABE, 1, 0, &c);
    CHECK(chunk_fingerprint(&a) != chunk_fingerprint(&c),
          "chunk: different coords -> different chunk");

    World d;
    world_generate_chunk(0xDEADBEEF, 0, 0, &d);
    CHECK(chunk_fingerprint(&a) != chunk_fingerprint(&d),
          "chunk: different seed -> different chunk");
}

static void test_chunk_invariants(void) {
    /* Find one cavern + one outdoor chunk and assert per-biome invariants.
     * Spawn-walkable must hold for both. */
    int found_cave = 0, found_out = 0;
    for(int cy = 0; cy < 16 && (!found_cave || !found_out); cy++) {
        for(int cx = 0; cx < 16 && (!found_cave || !found_out); cx++) {
            World w;
            world_generate_chunk(0x12345678, cx, cy, &w);
            CHECK(world_walkable(&w, w.spawn_x, w.spawn_y), "chunk: spawn walkable");
            int mc = WORLD_COLS / 2, mr = WORLD_ROWS / 2;
            if(biome_terrain(w.biome) == TERRAIN_WALLED && !found_cave) {
                found_cave = 1;
                CHECK(w.tiles[0][mc] == TILE_DOOR && w.tiles[WORLD_ROWS - 1][mc] == TILE_DOOR
                          && w.tiles[mr][0] == TILE_DOOR && w.tiles[mr][WORLD_COLS - 1] == TILE_DOOR,
                      "cavern: four edge-midpoint doors present");
                CHECK(w.tiles[0][1] == TILE_WALL, "cavern: top border is wall");
            }
            if(biome_terrain(w.biome) == TERRAIN_OPEN && !found_out) {
                found_out = 1;
                CHECK(w.tiles[0][1] != TILE_WALL && w.tiles[WORLD_ROWS - 1][1] != TILE_WALL,
                      "outdoor: edges open (no border wall)");
            }
        }
    }
    CHECK(found_cave, "chunk: found a cavern chunk in the sample");
    CHECK(found_out, "chunk: found an outdoor chunk in the sample");
}

/* GOLDEN MASTER — recorded fingerprints. If any of these change, the
 * world generator changed: a player's existing worlds would shift and
 * the future PC port would diverge. Such a change is allowed ONLY with
 * a deliberate generator-version bump (spec 43 §14.0). Re-record these
 * values intentionally, never to "make the test pass". */
static void test_chunk_golden(void) {
    struct {
        uint32_t seed;
        int cx, cy;
        uint32_t fp;
    } cases[] = {
        /* Re-recorded for v0.3.5a (torch kind added to the loot table
         * shifted loot_roll distribution — a deliberate gen-version change). */
        {0xCAFEBABE, 0, 0, 0x5F11BA1C},
        {0xCAFEBABE, 1, 0, 0xD9828F02},
        {0xDEADBEEF, 0, 0, 0x694D3DB9},
        {0x00000001, -3, 5, 0xC0CA4E2B},
    };
    int n = (int)(sizeof(cases) / sizeof(cases[0]));
    for(int i = 0; i < n; i++) {
        World w;
        world_generate_chunk(cases[i].seed, cases[i].cx, cases[i].cy, &w);
        uint32_t fp = chunk_fingerprint(&w);
        printf("  golden[%d] seed=%08lX (%d,%d) -> fp=0x%08lX\n",
               i, (unsigned long)cases[i].seed, cases[i].cx, cases[i].cy,
               (unsigned long)fp);
        CHECK(fp == cases[i].fp, "chunk golden-master fingerprint");
    }
}

/* ── loot ────────────────────────────────────────────────────────── */

static void test_loot_catalog_integrity(void) {
    /* glyphs distinct; id == index; kind_by_glyph round-trips */
    int distinct = 1;
    for(int i = 0; i < KIND_COUNT; i++) {
        CHECK(KIND_CATALOG[i].id == (uint8_t)i, "loot: id == index");
        const KindDef* byg = kind_by_glyph(KIND_CATALOG[i].glyph);
        CHECK(byg == &KIND_CATALOG[i], "loot: kind_by_glyph round-trips");
        for(int j = i + 1; j < KIND_COUNT; j++) {
            if(KIND_CATALOG[i].glyph == KIND_CATALOG[j].glyph) distinct = 0;
        }
    }
    CHECK(distinct, "loot: all glyphs distinct");
    CHECK(kind_by_glyph('#') == NULL, "loot: wall is not a kind");
    CHECK(loot_is_item_glyph('.') == 0, "loot: floor is not an item");
    CHECK(loot_is_item_glyph('*') == 1, "loot: crystal is an item");
}

static void test_loot_roll_determinism(void) {
    Rng a, b;
    rng_seed(&a, 4242);
    rng_seed(&b, 4242);
    int same = 1;
    for(int i = 0; i < 500; i++) {
        if(loot_roll(&a, BIOME_CAVERN) != loot_roll(&b, BIOME_CAVERN)) same = 0;
    }
    CHECK(same, "loot_roll: deterministic for a given seed");
}

static void test_loot_roll_distribution(void) {
    /* Deterministic (fixed seed) so this is repeatable, not flaky.
     * Tests cavern distribution AND that biome-excluded kinds (fungus)
     * are never rolled in cavern. */
    enum { N = 20000 };
    const Biome biome = BIOME_CAVERN;
    const uint8_t bbit = BIOME_BIT(biome);
    int counts[KIND_COUNT];
    for(int i = 0; i < KIND_COUNT; i++) counts[i] = 0;
    uint32_t total_w = 0;
    for(int i = 0; i < KIND_COUNT; i++) {
        if(KIND_CATALOG[i].biomes & bbit) total_w += KIND_CATALOG[i].weight;
    }
    Rng r;
    rng_seed(&r, 13579);
    for(int i = 0; i < N; i++) {
        uint8_t id = loot_roll(&r, biome);
        CHECK(id < (uint8_t)KIND_COUNT, "loot_roll: id in range");
        counts[id]++;
    }
    for(int i = 0; i < KIND_COUNT; i++) {
        if(KIND_CATALOG[i].biomes & bbit) {
            double expected = (double)N * KIND_CATALOG[i].weight / (double)total_w;
            double dev = (double)counts[i] - expected;
            if(dev < 0) dev = -dev;
            CHECK(dev < expected * 0.15 + 50.0, "loot_roll: distribution matches weights");
        } else {
            CHECK(counts[i] == 0, "loot_roll: biome-excluded kind never rolled");
        }
    }
}

static void test_biome(void) {
    CHECK(biome_of(0xABCD, 5, 5) == biome_of(0xABCD, 5, 5), "biome_of deterministic");
    /* region coherence: chunks 3,3 / 4,3 / 3,4 / 5,5 are all in region (1,1) */
    Biome b = biome_of(0xABCD, 3, 3);
    CHECK(biome_of(0xABCD, 4, 3) == b && biome_of(0xABCD, 3, 4) == b
              && biome_of(0xABCD, 5, 5) == b,
          "biome: region is contiguous (3x3)");
    CHECK(biome_terrain(BIOME_CAVERN) == TERRAIN_WALLED, "biome: cavern is walled");
    CHECK(biome_terrain(BIOME_OUTDOOR) == TERRAIN_OPEN, "biome: outdoor is open");
    /* outdoor must never roll a cavern-only kind */
    Rng r;
    rng_seed(&r, 24680);
    int saw_crystal = 0;
    for(int i = 0; i < 5000; i++) {
        if(loot_glyph(loot_roll(&r, BIOME_OUTDOOR)) == '*') saw_crystal = 1;
    }
    CHECK(!saw_crystal, "biome: outdoor never rolls cavern-only crystal");
}

static void test_fov(void) {
    /* fuel → radius bands */
    CHECK(fov_radius_for_fuel(TORCH_FUEL_MAX) == 4, "fov: full fuel -> radius 4");
    CHECK(fov_radius_for_fuel(60) == 4, "fov: 60 -> 4");
    CHECK(fov_radius_for_fuel(59) == 3, "fov: 59 -> 3");
    CHECK(fov_radius_for_fuel(30) == 3, "fov: 30 -> 3");
    CHECK(fov_radius_for_fuel(10) == 2, "fov: 10 -> 2");
    CHECK(fov_radius_for_fuel(9) == 1, "fov: 9 -> 1");
    CHECK(fov_radius_for_fuel(0) == 1, "fov: empty -> radius 1 (never blind)");

    /* lit bounds: chebyshev <= r is lit, r+1 is not */
    CHECK(fov_is_lit(5, 3, 8, 3, 3), "fov: chebyshev==r is lit");
    CHECK(!fov_is_lit(5, 3, 9, 3, 3), "fov: chebyshev==r+1 is dark");
    CHECK(fov_is_lit(5, 3, 5, 3, 0), "fov: own tile always lit");

    /* symmetry: lit(a,b,c,d) == lit(c,d,a,b) */
    int sym = 1;
    for(int r = 0; r <= 4; r++) {
        if(fov_is_lit(2, 1, 7, 4, r) != fov_is_lit(7, 4, 2, 1, r)) sym = 0;
        if(fov_is_lit(0, 0, 3, 2, r) != fov_is_lit(3, 2, 0, 0, r)) sym = 0;
    }
    CHECK(sym, "fov: is_lit is symmetric");
}

int main(void) {
    printf("Sanctum RPG — deterministic core tests\n");
    test_fov();
    test_rng_determinism();
    test_rng_range_bounds();
    test_chunk_seed_spread();
    test_loot_catalog_integrity();
    test_loot_roll_determinism();
    test_loot_roll_distribution();
    test_biome();
    test_chunk_determinism();
    test_chunk_invariants();
    test_chunk_golden();
    printf("\n%d passed, %d failed\n", g_pass, g_fail);
    return g_fail == 0 ? 0 : 1;
}
