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
#include <stdlib.h>
#include <string.h>

#include "../biome.h"
#include "../classes.h"
#include "../creatures.h"
#include "../fov.h"
#include "../pool.h"
#include "../recipes.h"
#include "../loot.h"
#include "../bearing.h"
#include "../names.h"
#include "../trade.h"
#include "../rng.h"
#include "../weather.h"
#include "../world.h"
#include "../region.h"
#include "../quirk.h"
#include "../site.h"
#include "../sky.h"
#include "../stamps.h"
#include "../terrain.h"
#include "../compose.h"
#include "../corruption.h"
#include "../effort.h"
#include "../ritual.h"
#include "../arc.h"
#include "../deeds.h"
#include "../dead.h"
#include "../afflict.h"
#include "../cast.h"

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
    h ^= (uint32_t)w->style;   /* WORLDGEN 2: the region's style is part of the chunk */
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

/* Is the neighbor across `dir` a walled (cavern/room) chunk? */
static bool nbr_walled(uint32_t seed, int cx, int cy, MoveDir dir) {
    int nx = cx, ny = cy;
    switch(dir) {
    case MoveNorth: ny--; break;
    case MoveSouth: ny++; break;
    case MoveWest:  nx--; break;
    case MoveEast:  nx++; break;
    default: break;
    }
    return region_terrain(seed, nx, ny) == TERRAIN_WALLED;
}

/* The shared-edge coherence invariant (spec 50 §R): an edge is walled iff this
 * chunk OR its neighbor across that edge is walled. A walled edge's interior
 * span is all wall except one door at the hashed position; an open edge's span
 * is free of wall/door. Checks the non-corner span only. */
static bool edge_is_coherent(const World* w, uint32_t seed, int cx, int cy,
                             MoveDir dir) {
    bool walled = (world_terrain(w) == TERRAIN_WALLED) ||
                  nbr_walled(seed, cx, cy, dir);
    int door = world_edge_door_perp(seed, cx, cy, dir);
    if(dir == MoveNorth || dir == MoveSouth) {
        int row = (dir == MoveNorth) ? 0 : WORLD_ROWS - 1;
        for(int x = 1; x < WORLD_COLS - 1; x++) {
            char t = w->tiles[row][x];
            if(walled) {
                if(x == door) { if(t != TILE_DOOR) return false; }
                else if(t != TILE_WALL && t != TILE_SECRET) return false;
            } else if(t == TILE_WALL || t == TILE_DOOR || t == TILE_SECRET) {
                return false;
            }
        }
    } else {
        int col = (dir == MoveWest) ? 0 : WORLD_COLS - 1;
        for(int y = 1; y < WORLD_ROWS - 1; y++) {
            char t = w->tiles[y][col];
            if(walled) {
                if(y == door) { if(t != TILE_DOOR) return false; }
                else if(t != TILE_WALL && t != TILE_SECRET) return false;
            } else if(t == TILE_WALL || t == TILE_DOOR || t == TILE_SECRET) {
                return false;
            }
        }
    }
    return true;
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
            if(world_terrain(&w) == TERRAIN_WALLED && !found_cave) {
                found_cave = 1;
                /* One door per edge, each at its hashed shared-edge position. */
                int nc = world_edge_door_perp(0x12345678, cx, cy, MoveNorth);
                int sc = world_edge_door_perp(0x12345678, cx, cy, MoveSouth);
                int wr = world_edge_door_perp(0x12345678, cx, cy, MoveWest);
                int er = world_edge_door_perp(0x12345678, cx, cy, MoveEast);
                CHECK(w.tiles[0][nc] == TILE_DOOR &&
                          w.tiles[WORLD_ROWS - 1][sc] == TILE_DOOR &&
                          w.tiles[wr][0] == TILE_DOOR &&
                          w.tiles[er][WORLD_COLS - 1] == TILE_DOOR,
                      "cavern: each edge's door sits at its hashed position");
                /* Exactly one door per edge; every other border tile is wall. */
                int td = 0, bd = 0, ld = 0, rd = 0;
                for(int x = 0; x < WORLD_COLS; x++) {
                    if(w.tiles[0][x] == TILE_DOOR) td++;
                    if(w.tiles[WORLD_ROWS - 1][x] == TILE_DOOR) bd++;
                }
                for(int y = 0; y < WORLD_ROWS; y++) {
                    if(w.tiles[y][0] == TILE_DOOR) ld++;
                    if(w.tiles[y][WORLD_COLS - 1] == TILE_DOOR) rd++;
                }
                CHECK(td == 1 && bd == 1 && ld == 1 && rd == 1,
                      "cavern: exactly one door per edge (rest is wall)");
            }
            if(world_terrain(&w) == TERRAIN_OPEN && !found_out) {
                found_out = 1;
                /* Each edge matches its neighbor: open where the neighbor is
                 * open, wall+door where the neighbor is walled. */
                CHECK(edge_is_coherent(&w, 0x12345678, cx, cy, MoveNorth) &&
                          edge_is_coherent(&w, 0x12345678, cx, cy, MoveSouth) &&
                          edge_is_coherent(&w, 0x12345678, cx, cy, MoveWest) &&
                          edge_is_coherent(&w, 0x12345678, cx, cy, MoveEast),
                      "outdoor: each edge coheres with its neighbor's terrain");
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
/* The generator version these fingerprints were recorded under. Re-record
 * the fingerprints and bump WORLDGEN_VERSION (world.h) TOGETHER, then set
 * this to match — the check below fails if the two drift apart. */
#define GOLDEN_WORLDGEN_VERSION 9

static void test_chunk_golden(void) {
    CHECK(WORLDGEN_VERSION == GOLDEN_WORLDGEN_VERSION,
          "chunk goldens were recorded under the current WORLDGEN_VERSION");
    struct {
        uint32_t seed;
        int cx, cy;
        uint32_t fp;
    } cases[] = {
        /* Re-recorded 2026-06-09 (spec 50 §R world-coherence epic + corner-snap
         * composer). Deliberate generator change across one slice:
         *   - corner-snap stamp composer replaced random placement;
         *   - per-edge doors moved from mid-edge to hashed shared-edge positions;
         *   - open chunks grew wall+door on edges facing walled neighbors;
         *   - rare quest-gated secret passages (TILE_SECRET) added.
         * All four chunks shifted. Prior: 2026-06-03 economy bundle C, etc. */
        /* Re-recorded 2026-10-14, WORLDGEN_VERSION 1 -> 2: regions now have a
         * style (crypt / old mine / forest join cavern / moor), and the style
         * is hashed into the fingerprint. The last three cases were chosen
         * to land IN the new styles, so the goldens cover what changed.
         * Prior (v1): 0x9A4F21E6 0x01821F0D 0xB00E3D15 0xB39F63AE.
         * WORLDGEN 3 (same day): the cavern's stalagmite / column / divider
         * get their own glyphs ('A' '|' 'M', were all '#'). Only the two
         * cavern-style cases move (v2: 0xD0925D12 0x6CD6E177).
         * WORLDGEN 4 (same day): above-ground interiors (manor / keep /
         * abbey) join the surface styles, and caverns gain the glowcap
         * pocket. (-3,5) of seed 1 is now an abbey; DEADBEEF (0,0) stays
         * moor but grew a west wall + door onto the abbey next door.
         * v3: 0x65B1E3F9 0xA52B45BB 0x3A6A267C 0x72E9EC7D.
         * WORLDGEN 5 (same day): floor glyphs that were weather-overlay
         * glyphs in the top-down view move: grass '"'->'`', flagstone
         * '_'->'/', boards '\''->'['. Forest + keep cases move (v4:
         * 0x414E736C 0xDFEE86F4); the crypt and manor cases hold none.
         * WORLDGEN 6 (2026-10-20): the Pool bag is positional — a stamp's
         * primitive is biased by the bag slot at its index in its style's
         * vocabulary (StyleDef.vocab). Before, bag ids were matched against
         * primitive ids and only cavern ids (0..5) were ever in the bag, so
         * no other style was ever biased. Cavern vocab = {0..5}, so both
         * cavern cases hold; the other seven move. v5: 0x07E6DFEC
         * 0xE07A1B4E 0x076874FA 0x24E3D04E 0xAEAD9456 0x6B304778 0xF1B665B4.
         * WORLDGEN 7 (2026-10-21): the burial family (mausoleum, burial
         * mound, burial cavern) joins the style weights, so most regions
         * pick again; graves and altar stones join the older styles; the
         * Pool seeds all 8 bag slots (was 6); the waking region never picks
         * a burial style. The two CAFEBABE cavern cases sit in the waking
         * region, whose choice is unchanged, and hold. The rest moved, and
         * several changed style, so the labels below are new; four cases
         * were added so mausoleum, mound, mine and manor stay covered.
         * v6: 0xF0190C9A 0xD76992DE 0x9284A31F 0xC42D099E 0x8907914B
         * 0xF884806D 0xAFCF19E9.
         * WORLDGEN 8 (same day): each region places 2-3 sites (site.h),
         * one per chunk, last, consuming no RNG. Only the chunks that hold
         * a site move: the burial cavern (1,-5) and the manor (9,-9)
         * (v7: 0x2C560D59 0xD3BD0BFB). The rest are unchanged.
         * WORLDGEN 9 (2026-10-22): two changes, measured apart. (1) The
         * numeraire takes no Pool bias (spec 43 §17.3 #4): alone, it moves
         * exactly the five cavern-biome cases (the shard is cavern-only) and
         * none of the eight outdoor ones. (2) Each region places its
         * rituals' objects (ritual.h region_objects), round-robin over its
         * nine chunks; every region places at least nine, so every chunk
         * holds one and every case moves.
         * v8: 0xAA0B4171 0x0642A257 0x46A72DBF 0xFAAC554E 0xCE03D6D0
         * 0xCA8D0873 0x4E738B0A 0x84B02760 0xFDF54A80 0x2F53AD25 0x093EE793
         * 0xA97EF655 0x94878720. */
        {0xCAFEBABE, 0, 0, 0x5B175E4C},
        {0xCAFEBABE, 1, 0, 0xE93284EB},
        {0xDEADBEEF, 0, 0, 0x3F2E339C},             /* moor */
        {0x00000001, -3, 5, 0xE3AF62B0},            /* forest */
        {0x12345678, 4, -2, 0x2CA5C20B},            /* crypt */
        {0x12345678, 1, -5, 0xCA9B499D},            /* burial cavern */
        {0x12345678, 4, 1, 0x5624B762},             /* keep */
        {0x12345678, 7, -5, 0x0ECBACDA},            /* forest */
        {0x12345678, 7, -8, 0x0E674ED9},            /* abbey */
        {0x12345678, -3, -4, 0xD1194EBB},           /* mausoleum */
        {0x12345678, 3, -7, 0x69EF0A2D},            /* burial mound */
        {0x12345678, 0, 0, 0x2C7B65F6},             /* mine (the waking region) */
        {0x12345678, 9, -9, 0x8B962E7D},            /* manor */
    };
    int n = (int)(sizeof(cases) / sizeof(cases[0]));
    for(int i = 0; i < n; i++) {
        World w;
        world_generate_chunk(cases[i].seed, cases[i].cx, cases[i].cy, &w);
        uint32_t fp = chunk_fingerprint(&w);
        /* Report the BIOME too. The golden set only constrains a world-gen
         * change if it actually covers the biome that change touches — e.g.
         * the §17.3 #4 Pool-bias guard moves cavern chunks only, so a set of
         * all-outdoor goldens would have looked green and proved nothing. */
        printf("  golden[%d] seed=%08lX (%d,%d) biome=%s style=%s -> fp=0x%08lX\n",
               i, (unsigned long)cases[i].seed, cases[i].cx, cases[i].cy,
               w.biome == BIOME_CAVERN ? "cavern" : "outdoor", STYLE_TABLE[w.style].name,
               (unsigned long)fp);
        CHECK(fp == cases[i].fp, "chunk golden-master fingerprint");
    }
}

/* ── styles (SHARED_STATE 2026-10-14, "a region has a style") ───────
 * A region's style is shared by all its chunks, belongs to the chunk's
 * biome, and decides enclosed/open; the generator and the edge logic
 * agree on it. */
static void test_mutation_guard(void) {
    CHECK(world_mutation_applies(TILE_FLOOR, TILE_FLOOR), "deltas: a pickup applies to floor");
    CHECK(world_mutation_applies('*', TILE_FLOOR), "deltas: a pickup applies to a loot tile");
    CHECK(!world_mutation_applies(TILE_WALL, TILE_FLOOR) && !world_mutation_applies(TILE_DOOR, TILE_FLOOR) &&
          !world_mutation_applies(TILE_VENDOR, TILE_FLOOR) && !world_mutation_applies(TILE_VAULT, TILE_FLOOR) &&
          !world_mutation_applies('n', TILE_FLOOR) && !world_mutation_applies(TILE_SECRET, TILE_FLOOR),
          "deltas: a stale pickup never erases structure after a generator bump");
    /* A resting place takes only its own opened form (spec 50 Q1 §Q.1.2):
     * a grave that rose stays open, and nothing else can land on it. */
    CHECK(world_mutation_applies('g', 'G') && world_mutation_applies('n', 'N'),
          "deltas: a risen grave or sarcophagus stays open on reload");
    CHECK(!world_mutation_applies('g', TILE_FLOOR) && !world_mutation_applies('g', 'N') &&
          !world_mutation_applies('n', 'G') && !world_mutation_applies('a', 'G'),
          "deltas: a resting place takes no other change");
}

/* Spec 50 §L: scree costs a fuel tick; a glowcap is harvested for +2. */
static void test_terrain_steps(void) {
    TerrainStep ts;
    CHECK(terrain_step(':', &ts) && ts.fuel == -1 && !ts.consumed, "step: scree costs one fuel");
    CHECK(terrain_step('q', &ts) && ts.fuel == 2 && ts.consumed, "step: a glowcap is harvested for +2 fuel");
    CHECK(!terrain_step('.', &ts) && !terrain_step(',', &ts) && !terrain_step('#', &ts),
          "step: floor, moss and walls do nothing underfoot");
    CHECK(terrain_step_fuel(0, -1, 100) == 0 && terrain_step_fuel(99, 2, 100) == 100 &&
          terrain_step_fuel(50, 2, 100) == 52, "step: fuel clamps to 0..max");
    CHECK(world_mutation_applies('q', TILE_FLOOR), "deltas: a harvested glowcap stays harvested on reload");
    /* Glowcaps are actually placed now (the pocket stamp). */
    int caps = 0;
    for(int cy = -6; cy <= 6; cy++)
        for(int cx = -6; cx <= 6; cx++) {
            World w;
            world_generate_chunk(0xCAFEBABEu, cx, cy, &w);
            for(int y = 0; y < WORLD_ROWS; y++)
                for(int x = 0; x < WORLD_COLS; x++) caps += w.tiles[y][x] == 'q';
        }
    CHECK(caps > 0, "step: glowcaps appear in generated caverns");
}

/* Catalog integrity: every style has stamps, and every glyph a stamp can
 * place has a TERRAIN row — so first-person view knows how to draw it. */
/* Top-down: a floor glyph must not look like weather (grass vs storm). */
static void test_glyphs_vs_weather(void) {
    int clash = 0;
    for(int k = 0; k < WEATHER_KIND_COUNT; k++) {
        char g = weather_overlay_glyph((WeatherKind)k);
        const TerrainDef* d = terrain_def(g);
        if(d && d->form == TF_FLOOR) clash++;
    }
    CHECK(clash == 0, "glyphs: no terrain floor glyph is a weather overlay glyph");
    /* The device applies step effects from world_try_move's dest glyph. */
    World w;
    memset(&w, 0, sizeof(w));
    for(int y = 0; y < WORLD_ROWS; y++)
        for(int x = 0; x < WORLD_COLS; x++) w.tiles[y][x] = TILE_FLOOR;
    w.biome = BIOME_OUTDOOR; w.style = STYLE_MOOR;
    w.tiles[2][3] = ':'; w.tiles[2][4] = 'q';
    int px = 2, py = 2; char dest = 0;
    CHECK(world_try_move(&w, MoveEast, &px, &py, &dest) == MoveOk && dest == ':',
          "step: moving onto scree is MoveOk and reports the glyph");
    CHECK(world_try_move(&w, MoveEast, &px, &py, &dest) == MoveOk && dest == 'q',
          "step: moving onto a glowcap is MoveOk and reports the glyph");
}

static void test_style_catalog(void) {
    for(int st = 0; st < STYLE_COUNT; st++) {
        int n = 0;
        for(int i = 0; i < STAMP_COUNT; i++) n += STAMPS[i].style == st;
        CHECK(n >= 4, "catalog: every style has its own stamps");
    }
    int undrawn = 0;
    for(int i = 0; i < STAMP_COUNT; i++)
        for(int k = 0; k < STAMPS[i].prim_count; k++) {
            const PrimitiveDef* p = primitive_def(STAMPS[i].prims[k].prim_id);
            if(!p || !terrain_def(p->glyph)) undrawn++;
        }
    CHECK(undrawn == 0, "catalog: every stamped glyph has a terrain form");
    for(int i = 0; i < PRIM_COUNT_TOTAL; i++)
        for(int j = 0; j < i; j++)
            CHECK(PRIMITIVES[i].glyph != PRIMITIVES[j].glyph, "catalog: primitive glyphs are unique");
    /* Pool bias is positional (StyleDef.vocab): a primitive missing from its
     * style's vocabulary would silently get no bias. */
    int unbiased = 0, dup = 0, oversize = 0;
    for(int i = 0; i < STAMP_COUNT; i++)
        for(int k = 0; k < STAMPS[i].prim_count; k++)
            if(style_vocab_slot((Style)STAMPS[i].style, STAMPS[i].prims[k].prim_id) < 0) unbiased++;
    for(int st = 0; st < STYLE_COUNT; st++) {
        const StyleDef* d = &STYLE_TABLE[st];
        if(d->vocab_count > STYLE_VOCAB_MAX) oversize++;
        for(int a = 0; a < d->vocab_count; a++)
            for(int b = 0; b < a; b++) dup += d->vocab[a] == d->vocab[b];
    }
    CHECK(unbiased == 0, "catalog: every stamped primitive is in its style's Pool vocabulary");
    CHECK(oversize == 0 && dup == 0, "catalog: style vocabularies fit the seeded bag, no repeats");
    int identity = STYLE_TABLE[STYLE_CAVERN].vocab_count >= PRIM_COUNT_CAVERN;
    for(int k = 0; k < PRIM_COUNT_CAVERN; k++) identity &= STYLE_TABLE[STYLE_CAVERN].vocab[k] == k;
    CHECK(identity, "catalog: cavern vocabulary starts slot = id (its chunks predate the table)");
}

static void test_styles(void) {
    int bad_region = 0, bad_biome = 0, bad_terrain = 0, n = 0;
    static const uint32_t SEEDS[] = {0xCAFEBABEu, 0xDEADBEEFu, 0x00000001u, 0x12345678u};
    for(unsigned k = 0; k < sizeof(SEEDS) / sizeof(SEEDS[0]); k++)
        for(int cy = -7; cy <= 7; cy++)
            for(int cx = -7; cx <= 7; cx++) {
                uint32_t seed = SEEDS[k];
                Style st = style_of(seed, cx, cy);
                int ax = region_of(cx) * 3, ay = region_of(cy) * 3;   /* region anchor */
                if(style_of(seed, ax, ay) != st) bad_region++;
                if(STYLE_TABLE[st].biome != biome_of(seed, cx, cy)) bad_biome++;
                if(((cx + cy) & 7) == 0) {   /* a sample of real chunks */
                    World w;
                    world_generate_chunk(seed, cx, cy, &w);
                    if(w.style != st || world_terrain(&w) != region_terrain(seed, cx, cy)) bad_terrain++;
                    n++;
                }
            }
    CHECK(bad_region == 0, "style: every chunk of a region shares its style");
    CHECK(bad_biome == 0, "style: a region's style belongs to its biome");
    CHECK(n > 0 && bad_terrain == 0, "style: generated chunks carry their region's style + terrain");
    for(int b = 0; b < BIOME_COUNT; b++)
        CHECK(STYLE_TABLE[style_for_biome((Biome)b)].biome == (Biome)b,
              "style: style_for_biome returns a style of that biome");
    CHECK(style_terrain(STYLE_CAVERN) == TERRAIN_WALLED && style_terrain(STYLE_MOOR) == TERRAIN_OPEN,
          "style: the original styles keep their biome's terrain mode");
    CHECK(biome_pool(BIOME_CAVERN) == STAMP_BIOME_CAVERN && biome_pool(BIOME_OUTDOOR) == STAMP_BIOME_OUTDOOR,
          "style: the Pool stays keyed by biome");
    CHECK(region_hash(1, 2, 3) != region_hash(1, -2, -3), "style: region hash has no mirror twins");

    /* The player wakes somewhere neutral (spec 58): over many seeds the
     * waking chunk is never a burial place, and burial places do occur. */
    int woke_in_burial = 0, burial_seen = 0;
    for(uint32_t seed = 1; seed <= 2000; seed++) {
        woke_in_burial += !STYLE_TABLE[style_of(seed, 0, 0)].may_wake;
        burial_seen += !STYLE_TABLE[style_of(seed, 4, 4)].may_wake;
    }
    CHECK(woke_in_burial == 0, "style: the waking region is never a burial place");
    CHECK(burial_seen > 0, "style: burial places still occur away from the waking region");
    int wake_ok[BIOME_COUNT] = {0};
    for(int st = 0; st < STYLE_COUNT; st++)
        if(STYLE_TABLE[st].may_wake && STYLE_TABLE[st].weight) wake_ok[STYLE_TABLE[st].biome]++;
    for(int b = 0; b < BIOME_COUNT; b++)
        CHECK(wake_ok[b] > 0, "style: each realm has a style the player may wake in");
}

/* ── sites (spec 58 §58.5, WORLDGEN 8) ──────────────────────────────
 * Every style allows a site; every region places exactly its count of
 * sites, one per chunk, each of a kind its style allows, standing where it
 * cuts off no door and no ground, with open ground beside it. */
static bool site_has_open_side(const World* w) {
    static const int DX[4] = {1, -1, 0, 0}, DY[4] = {0, 0, 1, -1};
    for(int d = 0; d < 4; d++) {
        int x = w->site_x + DX[d], y = w->site_y + DY[d];
        if(x >= 0 && y >= 0 && x < WORLD_COLS && y < WORLD_ROWS && world_walkable(w, x, y)) return true;
    }
    return false;
}

static void test_sites(void) {
    int no_kind = 0, bad_glyph = 0;
    for(int st = 0; st < STYLE_COUNT; st++) no_kind += STYLE_TABLE[st].site_kinds == 0;
    for(int k = 0; k < SITE_KIND_COUNT; k++) {
        char g = SITE_TABLE[k].glyph;
        if(!terrain_def(g) || !world_is_blocking(g)) bad_glyph++;
    }
    CHECK(no_kind == 0, "sites: every style allows at least one site kind");
    CHECK(bad_glyph == 0, "sites: every site kind is a drawn, blocking terrain");

    static const uint32_t SEEDS[] = {0xCAFEBABEu, 0xDEADBEEFu, 0x00000001u, 0x12345678u,
                                     0x0BADF00Du, 0x7E57AB1Eu, 0xFEEDFACEu, 0x00C0FFEEu};
    int wrong_count = 0, wrong_kind = 0, wrong_tile = 0, cut_off = 0, no_side = 0, disagree = 0, regions = 0;
    for(unsigned s = 0; s < sizeof(SEEDS) / sizeof(SEEDS[0]); s++)
        for(int ry = -4; ry <= 4; ry++)
            for(int rx = -4; rx <= 4; rx++) {
                uint32_t seed = SEEDS[s];
                int placed = 0;
                for(int dy = 0; dy < 3; dy++)
                    for(int dx = 0; dx < 3; dx++) {
                        int cx = rx * 3 + dx, cy = ry * 3 + dy;
                        World w;
                        world_generate_chunk(seed, cx, cy, &w);
                        if(w.site_kind != chunk_site_kind(seed, cx, cy)) disagree++;
                        if(w.site_kind == SITE_NONE) continue;
                        placed++;
                        if(!(STYLE_TABLE[w.style].site_kinds & SITE_BIT(w.site_kind))) wrong_kind++;
                        if(w.tiles[w.site_y][w.site_x] != SITE_TABLE[w.site_kind].glyph) wrong_tile++;
                        if(!world_doors_reachable_from(&w, w.spawn_x, w.spawn_y)) cut_off++;
                        if(!site_has_open_side(&w)) no_side++;
                    }
                if(placed != region_site_count(seed, rx, ry)) wrong_count++;
                regions++;
            }
    printf("  sites: %d regions checked\n", regions);
    CHECK(disagree == 0, "sites: a chunk holds a site exactly when its region put one there");
    CHECK(wrong_count == 0, "sites: every region places exactly its count of sites");
    CHECK(wrong_kind == 0, "sites: every site is a kind its style allows");
    CHECK(wrong_tile == 0, "sites: the site's tile holds its glyph");
    CHECK(cut_off == 0, "sites: no site cuts a door off");
    CHECK(no_side == 0, "sites: every site has open ground beside it");
    int lo = 99, hi = 0;
    for(int ry = -20; ry <= 20; ry++)
        for(int rx = -20; rx <= 20; rx++) {
            int n = region_site_count(0xCAFEBABEu, rx, ry);
            if(n < lo) lo = n;
            if(n > hi) hi = n;
        }
    CHECK(lo == SITES_PER_REGION_MIN && hi == SITES_PER_REGION_MAX, "sites: counts span MIN..MAX");
}

/* ── the sky (spec 50 Q1 §Q.11) ─────────────────────────────────────
 * Real moons land at their phase with full strength; a quarter moon has
 * none; strength waxes and wanes monotonically through each window; night
 * splits at the configured hours. */
static void test_sky(void) {
    static const struct { uint64_t t; MoonPhase p; } MOONS[] = {
        {1706205240ull, MOON_FULL},   /* 2024-01-25 17:54 UTC */
        {1704974220ull, MOON_NEW},    /* 2024-01-11 11:57 UTC */
        {1741935300ull, MOON_FULL},   /* 2025-03-14 06:55 UTC */
        {1743245880ull, MOON_NEW},    /* 2025-03-29 10:58 UTC */
    };
    Sky s;
    int wrong = 0, weak = 0;
    for(unsigned i = 0; i < sizeof(MOONS) / sizeof(MOONS[0]); i++) {
        sky_at(MOONS[i].t, &s);
        if(s.phase != MOONS[i].p) wrong++;
        if(s.moon_strength < MOON_STRENGTH_MAX - 1) weak++;
    }
    CHECK(wrong == 0, "sky: known full and new moons land at their phase");
    CHECK(weak == 0, "sky: a full or new moon is at (near) full strength");
    sky_at(1705549920ull, &s);   /* 2024-01-18 03:52 UTC, first quarter */
    CHECK(s.moon_strength == 0 && s.phase == MOON_WAXING, "sky: a quarter moon has no strength");

    /* Through the window around the 2024-01-25 full moon, hour by hour. A
     * mean month puts real full moons up to ~9 h off (the moon's orbit is
     * not a circle; measured: 8.5 h and 5.75 h early for the two fulls
     * above, under 4 h for the news), so the checks keep a 12 h margin. */
    const int64_t reach = (int64_t)MOON_REACH_DAYS * 86400, slack = 12 * 3600;
    int rises = 0, falls = 0, outside = 0;
    uint8_t prev = 0;
    for(int64_t dt = -reach - 2 * slack; dt <= reach + 2 * slack; dt += 3600) {
        sky_at((uint64_t)(1706205240ll + dt), &s);
        if(dt < -slack && dt > -reach - 2 * slack + 3600 && s.moon_strength < prev) rises++;
        if(dt > slack && s.moon_strength > prev) falls++;
        if((dt < -reach - slack || dt > reach + slack) && s.moon_strength != 0) outside++;
        prev = s.moon_strength;
    }
    CHECK(rises == 0 && falls == 0, "sky: strength waxes to the phase and wanes after it");
    CHECK(outside == 0, "sky: no strength outside MOON_REACH_DAYS");

    const uint64_t day = 1706140800ull;   /* 2024-01-25 00:00 */
    sky_at(day + 19 * 3600 + 3599, &s);
    int dusk_day = !s.night;
    sky_at(day + 20 * 3600, &s);
    int dusk_night = s.night;
    sky_at(day + 5 * 3600 + 3599, &s);
    int dawn_night = s.night;
    sky_at(day + 6 * 3600, &s);
    CHECK(dusk_day && dusk_night && dawn_night && !s.night, "sky: night is 20:00 to 06:00");
    CHECK(sky_night_id(day + 23 * 3600) == sky_night_id(day + 86400 + 2 * 3600) &&
          sky_night_id(day + 23 * 3600) != sky_night_id(day + 86400 + 23 * 3600),
          "sky: the small hours belong to the night before");

    /* The line: only at night, only near full or new, and it fits. */
    sky_at(1706140800ull + 22 * 3600, &s);   /* 2024-01-25 22:00, full */
    const char* full_night = sky_line(&s);
    sky_at(1706140800ull + 12 * 3600, &s);   /* same day, noon */
    const char* full_day = sky_line(&s);
    sky_at(1705549920ull - 3 * 3600 + 22 * 3600, &s);   /* quarter moon, night */
    const char* quarter = sky_line(&s);
    sky_at(1704974220ull - 11 * 3600 + 23 * 3600, &s);   /* 2024-01-11 23:00, new */
    const char* new_night = sky_line(&s);
    CHECK(full_night && new_night && full_night != new_night, "sky: a full and a new moon each have a line at night");
    CHECK(!full_day && !quarter, "sky: no line by day or under a quarter moon");
    CHECK(strlen(full_night) <= 30 && strlen(new_night) <= 30, "sky: the moon lines fit the status bar");
}

/* ── names (procedural place names, slice 2026-06-03c) ──────────────
 *
 * Determinism + cap-handling + biome-distinct dictionaries. */

static void test_names_determinism(void) {
    char a[NAME_MAX_LEN], b[NAME_MAX_LEN];
    name_for_chunk(0xCAFEBABE, 3, -2, BIOME_OUTDOOR, a, sizeof(a));
    name_for_chunk(0xCAFEBABE, 3, -2, BIOME_OUTDOOR, b, sizeof(b));
    CHECK(strcmp(a, b) == 0, "names: deterministic for same inputs");

    char c[NAME_MAX_LEN];
    name_for_chunk(0xCAFEBABE, 3, -1, BIOME_OUTDOOR, c, sizeof(c));
    /* Neighbour chunks should almost-always pick different names. Not a
     * hard guarantee (16x16 = 256 possible names per biome → collisions
     * exist) but should hold for these specific inputs. */
    CHECK(strcmp(a, c) != 0, "names: neighbour chunk gets different name");
}

/* WORLDGEN 6: names by style. Cavern + moor names are pinned byte for byte
 * from v5 (recorded before the change); built places share one name per
 * region; every style's longest name fits without truncation. */
static void test_names_by_style(void) {
    static const struct { uint8_t style; int cx, cy; const char* name; } PIN[] = {
        {STYLE_CAVERN, 0, 0, "Stone Cavern"}, {STYLE_CAVERN, 3, -2, "Deep Pit"},
        {STYLE_CAVERN, -7, 5, "Black Shaft"}, {STYLE_CAVERN, 12, 9, "Deepshaft"},
        {STYLE_MOOR, 0, 0, "Windshore"},      {STYLE_MOOR, 3, -2, "Lorwood"},
        {STYLE_MOOR, -7, 5, "Briar Moor"},    {STYLE_MOOR, 12, 9, "Lordown"},
    };
    char a[NAME_MAX_LEN], b[NAME_MAX_LEN];
    int moved = 0;
    for(unsigned i = 0; i < sizeof(PIN) / sizeof(PIN[0]); i++) {
        name_for_chunk(0xCAFEBABE, PIN[i].cx, PIN[i].cy, PIN[i].style, a, sizeof(a));
        if(strcmp(a, PIN[i].name) != 0) moved++, printf("    %s -> %s\n", PIN[i].name, a);
    }
    CHECK(moved == 0, "names: cavern + moor names unchanged by WORLDGEN 6");

    int split = 0, shared = 0, too_long = 0;
    for(int st = 0; st < STYLE_COUNT; st++) {
        int per_region = STYLE_TABLE[st].name_scope == NAME_SCOPE_REGION;
        for(int cy = -9; cy <= 9; cy++)
            for(int cx = -9; cx <= 9; cx++) {
                char big[64];
                name_for_chunk(0x12345678, cx, cy, (uint8_t)st, big, sizeof(big));
                if(strlen(big) >= NAME_MAX_LEN) too_long++;
                name_for_chunk(0x12345678, cx, cy, (uint8_t)st, a, sizeof(a));
                name_for_chunk(0x12345678, cx + 1, cy, (uint8_t)st, b, sizeof(b));
                int same_region = region_of(cx) == region_of(cx + 1);
                if(per_region && same_region && strcmp(a, b) != 0) split++;
                if(!per_region && strcmp(a, b) == 0) shared++;
            }
    }
    CHECK(split == 0, "names: every chunk of a built place's region shares its name");
    CHECK(shared < 40, "names: wild places still name chunk by chunk");
    CHECK(too_long == 0, "names: every style's names fit NAME_MAX_LEN");
    name_for_chunk(0x12345678, 0, 0, STYLE_KEEP, a, sizeof(a));
    name_for_chunk(0x12345678, 0, 0, STYLE_MANOR, b, sizeof(b));
    CHECK(strcmp(a, b) != 0, "names: a keep and a manor on the same ground are named differently");
}

static void test_names_biome_distinct(void) {
    /* Same seed + coords + different biome → different name (different
     * dictionary). */
    char outdoor[NAME_MAX_LEN], cavern[NAME_MAX_LEN];
    name_for_chunk(0xDEADBEEF, 0, 0, BIOME_OUTDOOR, outdoor, sizeof(outdoor));
    name_for_chunk(0xDEADBEEF, 0, 0, BIOME_CAVERN, cavern, sizeof(cavern));
    CHECK(strcmp(outdoor, cavern) != 0, "names: outdoor vs cavern differ");

    /* And the names produced are non-empty (defensive — earlier bugs in
     * hash digit-mask logic produced empty strings). */
    CHECK(strlen(outdoor) > 0, "names: outdoor name non-empty");
    CHECK(strlen(cavern)  > 0, "names: cavern name non-empty");
}

static void test_names_cap_truncates(void) {
    /* A tiny cap should truncate cleanly, ending in '\0'. */
    char tiny[4];
    name_for_chunk(0xCAFEBABE, 0, 0, BIOME_OUTDOOR, tiny, sizeof(tiny));
    CHECK(tiny[3] == '\0', "names: truncated name is null-terminated");
    CHECK(strlen(tiny) <= 3, "names: truncated within cap");

    /* Cap of 1 is no-op (need at least 2 for empty string). */
    char one[2] = {'?', '?'};
    name_for_chunk(0xCAFEBABE, 0, 0, BIOME_OUTDOOR, one, 1);
    CHECK(one[0] == '?', "names: cap=1 is no-op");
}

static void test_names_distribution(void) {
    /* Sweep many chunks; assert the population uses BOTH halves of each
     * dictionary table — protects against accidental low-bit collisions
     * that would jam the world into 16 names. */
    int prefix_hit[16] = {0};
    int suffix_hit[16] = {0};
    /* Since we can't introspect the chosen index directly, infer by
     * matching the first 4 chars (a unique prefix prefix in the OUT
     * table) — coarse but enough to detect "all hash to slot 0". */
    char buf[NAME_MAX_LEN];
    for(int cx = -16; cx <= 16; cx++) {
        for(int cy = -16; cy <= 16; cy++) {
            name_for_chunk(0xABCDEF12u, cx, cy, BIOME_OUTDOOR, buf, sizeof(buf));
            /* Hash of first char → bin into 16; just a coarse spread check. */
            prefix_hit[(int)buf[0] & 0xF]++;
            size_t l = strlen(buf);
            if(l > 0) suffix_hit[(int)buf[l-1] & 0xF]++;
        }
    }
    int prefix_bins_used = 0, suffix_bins_used = 0;
    for(int i = 0; i < 16; i++) {
        if(prefix_hit[i] > 0) prefix_bins_used++;
        if(suffix_hit[i] > 0) suffix_bins_used++;
    }
    CHECK(prefix_bins_used >= 4,
          "names: hash spreads prefixes across multiple bins");
    CHECK(suffix_bins_used >= 4,
          "names: hash spreads suffixes across multiple bins");
}

/* ── bearing (home-bearing HUD) ──────────────────────────────────────
 *
 * 8-way compass from (cx, cy) to (0, 0); Chebyshev distance. */

static void test_bearing_at_home(void) {
    int8_t sx = 9, sy = 9;
    uint16_t d = 99;
    bearing_to_home(0, 0, &sx, &sy, &d);
    CHECK(sx == 0 && sy == 0, "bearing: (0,0) is the origin");
    CHECK(d == 0, "bearing: distance at home is 0");
    CHECK(bearing_label(0, 0)[0] == '\0',
          "bearing: empty label at origin");
}

static void test_bearing_eight_compass(void) {
    struct { int cx, cy; const char* lbl; uint16_t dist; } cases[] = {
        /* Player south of home → home is north. */
        {  0,  3, "N",  3 },
        /* Player north of home → home is south. */
        {  0, -2, "S",  2 },
        /* Player west of home → home is east. */
        { -4,  0, "E",  4 },
        /* Player east of home → home is west. */
        {  5,  0, "W",  5 },
        /* Diagonals (distance is Chebyshev = max). */
        { -2,  3, "NE", 3 },
        { -3, -1, "SE", 3 },
        {  2,  4, "NW", 4 },
        {  4, -2, "SW", 4 },
    };
    for(int i = 0; i < (int)(sizeof(cases)/sizeof(cases[0])); i++) {
        int8_t sx, sy;
        uint16_t d;
        bearing_to_home(cases[i].cx, cases[i].cy, &sx, &sy, &d);
        const char* got = bearing_label(sx, sy);
        CHECK(strcmp(got, cases[i].lbl) == 0,
              "bearing: 8-compass label matches direction");
        CHECK(d == cases[i].dist,
              "bearing: Chebyshev distance correct");
    }
}

/* ── vault (economy bundle slice C) ─────────────────────────────────
 *
 * The home chunk (0, 0) gets a TILE_VAULT placed after gen + carve so
 * it lands on a tile already in the walkable-connected component. It
 * must be walkable, must not sit on the player spawn, and must NOT
 * appear in non-home chunks. */

static void test_vault_home_chunk_placement(void) {
    /* Multiple seeds — across all of them, chunk (0,0) must carry a
     * TILE_VAULT adjacent or near the spawn, and it must be walkable. */
    uint32_t seeds[] = {
        0xCAFEBABE, 0xDEADBEEF, 0x12345678, 0xFEEDFACE, 0xC0FFEE12u
    };
    for(int i = 0; i < (int)(sizeof(seeds)/sizeof(seeds[0])); i++) {
        World w;
        world_generate_chunk(seeds[i], 0, 0, &w);
        int vx = -1, vy = -1;
        for(int y = 0; y < WORLD_ROWS && vx < 0; y++) {
            for(int x = 0; x < WORLD_COLS; x++) {
                if(w.tiles[y][x] == TILE_VAULT) { vx = x; vy = y; break; }
            }
        }
        CHECK(vx >= 0,
              "vault: home chunk (0,0) carries a TILE_VAULT");
        if(vx >= 0) {
            CHECK(world_walkable(&w, vx, vy),
                  "vault: TILE_VAULT is walkable");
            CHECK(!(vx == w.spawn_x && vy == w.spawn_y),
                  "vault: not placed on the player spawn");
        }
    }
}

static void test_vault_only_at_home(void) {
    /* Sweep a generous box of NON-home chunks — none of them should
     * have a TILE_VAULT (vault is exclusive to (0,0)). */
    for(int cy = -4; cy <= 4; cy++) {
        for(int cx = -4; cx <= 4; cx++) {
            if(cx == 0 && cy == 0) continue;
            World w;
            world_generate_chunk(0xCAFEBABE, cx, cy, &w);
            for(int y = 0; y < WORLD_ROWS; y++) {
                for(int x = 0; x < WORLD_COLS; x++) {
                    CHECK(w.tiles[y][x] != TILE_VAULT,
                          "vault: non-home chunk has no TILE_VAULT");
                }
            }
        }
    }
}

/* ── trade (economy bundle slice B) ─────────────────────────────────
 *
 * Determinism + bounds + the chunk-(0,0)-is-not-vendor invariant + the
 * vendor-placement distribution. */

static void test_trade_determinism(void) {
    /* Same inputs → byte-equal outputs (port stability). */
    int8_t a = chunk_price_delta(0xCAFEBABE, 3, -2, 4);
    int8_t b = chunk_price_delta(0xCAFEBABE, 3, -2, 4);
    CHECK(a == b, "trade: chunk_price_delta deterministic");

    bool va = chunk_has_vendor(0xCAFEBABE, 5, 7);
    bool vb = chunk_has_vendor(0xCAFEBABE, 5, 7);
    CHECK(va == vb, "trade: chunk_has_vendor deterministic");

    int x1, y1, x2, y2;
    vendor_position(0xCAFEBABE, 5, 7, &x1, &y1);
    vendor_position(0xCAFEBABE, 5, 7, &x2, &y2);
    CHECK(x1 == x2 && y1 == y2, "trade: vendor_position deterministic");
}

static void test_trade_home_chunk_not_vendor(void) {
    /* Chunk (0,0) is reserved for the home/vault tile (slice C). It must
     * never get a vendor regardless of seed. */
    uint32_t seeds[] = {0, 0xCAFEBABE, 0xDEADBEEF, 0x12345678, 0xFFFFFFFFu};
    for(int i = 0; i < (int)(sizeof(seeds)/sizeof(seeds[0])); i++) {
        CHECK(!chunk_has_vendor(seeds[i], 0, 0),
              "trade: chunk (0,0) is never a vendor");
    }
}

static void test_trade_delta_bounds(void) {
    /* chunk_price_delta is supposed to stay in [-50, +50]. Sweep widely. */
    int min_d = 127, max_d = -128;
    for(int cy = -8; cy <= 8; cy++) {
        for(int cx = -8; cx <= 8; cx++) {
            for(uint8_t k = 0; k < 16; k++) {
                int8_t d = chunk_price_delta(0xABCDEF12u, cx, cy, k);
                if(d < min_d) min_d = d;
                if(d > max_d) max_d = d;
            }
        }
    }
    CHECK(min_d >= -50, "trade: delta never below -50");
    CHECK(max_d <=  50, "trade: delta never above +50");
}

static void test_trade_vendor_rate(void) {
    /* Spread vendors across many chunks; expect ~1 in 6 chunks (16%).
     * Allow a generous band [10%, 24%]. */
    int hits = 0, total = 0;
    for(int cy = -16; cy <= 16; cy++) {
        for(int cx = -16; cx <= 16; cx++) {
            if(cx == 0 && cy == 0) continue; /* home reserved */
            total++;
            if(chunk_has_vendor(0x12345678u, cx, cy)) hits++;
        }
    }
    int pct = (hits * 100) / total;
    printf("  trade: vendor rate %d/%d = %d%%\n", hits, total, pct);
    CHECK(pct >= 10 && pct <= 24, "trade: ~1-in-6 vendor placement rate");
}

/* A non-numeraire kind id, for every pricing assertion that is about the
 * pricing MATH rather than about the money rule. Kind 6 = chest. */
#define K_TRADEABLE ((uint8_t)6)

static void test_trade_pricing(void) {
    /* Buy ≥ sell at the same delta (spread keeps the vendor's margin). */
    for(int d = -50; d <= 50; d += 10) {
        uint16_t buy  = trade_buy_price(K_TRADEABLE, 100, (int8_t)d);
        uint16_t sell = trade_sell_price(K_TRADEABLE, 100, (int8_t)d);
        CHECK(buy >= sell, "trade: vendor ask >= vendor bid (spread)");
    }
    /* Scrap is half of base, floored at 1. */
    CHECK(trade_scrap_price(K_TRADEABLE, 20) == 10, "trade: scrap = base/2 (20)");
    CHECK(trade_scrap_price(K_TRADEABLE, 1)  == 1,  "trade: scrap floors at 1");

    /* Sanity: surplus chunk (delta -50) cheap to buy from; scarce chunk
     * (delta +50) good to sell to. */
    CHECK(trade_buy_price(K_TRADEABLE, 100, -50)  < 100, "trade: surplus cheap to buy");
    CHECK(trade_sell_price(K_TRADEABLE, 100, +50) > 100, "trade: scarce pays well to sell");

    /* The trade triangle is profitable round-trip: buy at surplus, sell
     * at scarcity. Net should be positive. */
    uint16_t cost = trade_buy_price(K_TRADEABLE, 100, -50);
    uint16_t gain = trade_sell_price(K_TRADEABLE, 100, +50);
    CHECK(gain > cost,
          "trade: surplus→scarcity round-trip is profitable");
}

/* ═══ v0.6.0 — the numeraire is not a commodity (spec 43 §17) ══════════
 *
 * These are GUARD tests. Each one pins a seam where the shard-as-currency
 * pivot would otherwise ship an exploit; the comments record the measured
 * exploit so a future reader knows what the guard is for, not just that it
 * exists. */

static void test_numeraire_excluded_from_pricing(void) {
    /* §17.3 #1. Before the guard, with the shard's catalog value of 5:
     *   trade_scrap_price(5)     = 2  → one shard scraps into TWO shards,
     *                                   from the Bag, no vendor, turn one.
     *   trade_sell_price(5,+50)  = 6  → and a vendor pays six.
     * The fix is EXCLUSION, not delta 0: at delta 0 the shard still scraps
     * 5→2 and sells 5→4. So assert the rejection sentinel, and assert that
     * no delta anywhere in range can talk any pricing path into a number. */
    const KindDef* shard = kind_by_id(0);
    CHECK(shard != NULL, "numeraire: kind 0 exists");
    CHECK(trade_kind_is_numeraire(0), "numeraire: kind 0 IS the numeraire");
    CHECK(!trade_kind_is_numeraire(K_TRADEABLE),
          "numeraire: an ordinary kind is not");

    CHECK(trade_scrap_price(0, shard->value) == TRADE_NO_PRICE,
          "numeraire: scrap rejects kind 0 (the turn-one doubling machine)");
    for(int d = -50; d <= 50; d++) {
        CHECK(trade_buy_price(0, shard->value, (int8_t)d) == TRADE_NO_PRICE,
              "numeraire: buy rejects kind 0 at every delta");
        CHECK(trade_sell_price(0, shard->value, (int8_t)d) == TRADE_NO_PRICE,
              "numeraire: sell rejects kind 0 at every delta");
    }
    /* And the guard must not have silently disarmed pricing in general. */
    CHECK(trade_scrap_price(K_TRADEABLE, 20) == 10,
          "numeraire: ordinary kinds still priced");
}

static void test_numeraire_absent_from_shop_lists(void) {
    /* §17.3 #1, the UI half. `build_sellable_list` / `build_buyable_list`
     * live in sanctum_rpg.c behind the Flipper SDK, so this asserts the
     * PREDICATE they filter on — the same one, at the same source. A shard
     * in the bag must never become a shop row. */
    int listable = 0;
    for(int i = 0; i < KIND_COUNT; i++) {
        const KindDef* k = kind_by_id((uint8_t)i);
        if(!k) continue;
        if(k->value == 0) continue;
        if(!(k->flags & KF_PICKUPABLE)) continue;
        if(trade_kind_is_numeraire((uint8_t)i)) continue;
        listable++;
        CHECK(i != 0, "shop: kind 0 never reaches a shop list");
    }
    CHECK(listable > 0, "shop: the guard did not empty the shop");
}

/* §17.3 #4: the numeraire takes no Pool bias. Landed with WORLDGEN 9 (it
 * moves the cavern goldens, so it needed a generator-version bump). Before
 * it, max bias on the shard took it from ~38% to ~81% of the cavern pool:
 * a Craft-themed cavern was a mint. Now the share must not move at all. */
static void test_pool_numeraire_exposure(void) {
    Pool flat, biased;
    for(int i = 0; i < POOL_LOOT_KINDS; i++) {
        flat.loot_kind_bias[i] = 0;
        biased.loot_kind_bias[i] = 0;
    }
    biased.loot_kind_bias[0] = 56;  /* max bias on the numeraire */

    int same = 1;
    const int N = 20000;
    Rng ra, rb;
    rng_seed(&ra, 0xBEEF0001u);
    rng_seed(&rb, 0xBEEF0001u);
    for(int i = 0; i < N; i++)
        same &= loot_roll_pooled(&ra, BIOME_CAVERN, &flat) == loot_roll_pooled(&rb, BIOME_CAVERN, &biased);
    CHECK(same, "pool: bias on the numeraire changes no roll (spec 43 §17.3 #4)");

    /* Control: bias on an ordinary kind DOES move its share, so the test
     * above is proving exclusion and not a broken bias path. */
    Pool ctrl;
    for(int i = 0; i < POOL_LOOT_KINDS; i++) ctrl.loot_kind_bias[i] = 0;
    ctrl.loot_kind_bias[3] = 56;  /* vial — B_BOTH, so eligible in cavern */
    int flat_vials = 0, ctrl_vials = 0;
    Rng rc, rd;
    rng_seed(&rc, 0xBEEF0002u);
    rng_seed(&rd, 0xBEEF0002u);
    for(int i = 0; i < N; i++) {
        if(loot_roll_pooled(&rc, BIOME_CAVERN, &flat) == 3) flat_vials++;
        if(loot_roll_pooled(&rd, BIOME_CAVERN, &ctrl) == 3) ctrl_vials++;
    }
    CHECK(ctrl_vials > flat_vials,
          "pool: bias still works for ordinary kinds (control)");
}

static void test_recipe_oddment_invariant(void) {
    /* §17.3 #2/#3. The permanent table invariant: a FLOOR pull must always
     * be a NET LOSS, or the Forge is an income verb.
     *
     * This is why the oddment had to stop being currency. As a shard count
     * the invariant was `oddment x 5 < sum(input value)` and ALL THREE rows
     * failed it (3x5=15 vs 10; 2x5=10 vs 6; 5x5=25 vs 7 — the +178% EV
     * §17.3 #2 measured). Forcing them to pass meant clamping every oddment
     * to 1 — and under §17.5a's rounding, a sub-shard payout truncates to
     * ZERO, breaking recipes.h's own "never nothing" contract. As an object
     * the invariant is `value(oddment) < sum(input value)` and holds with no
     * rebalance. */
    for(int i = 0; i < RECIPE_COUNT; i++) {
        const RecipeDef* r = recipe_def((uint8_t)i);
        CHECK(r != NULL, "recipe: row exists");

        const KindDef* odd = kind_by_id(r->oddment_kind);
        CHECK(odd != NULL, "recipe: oddment names a real kind");
        CHECK(!trade_kind_is_numeraire(r->oddment_kind),
              "recipe: the floor never pays currency (#3)");
        CHECK(odd->flags & KF_PICKUPABLE,
              "recipe: the oddment is a thing you can hold");
        CHECK(odd->value > 0, "recipe: the oddment is sellable, never nothing");

        const KindDef* ia = kind_by_id(r->input_kind_a);
        CHECK(ia != NULL, "recipe: input A is a real kind");
        uint32_t in_value = (uint32_t)ia->value * r->input_qty_a;
        if(r->input_kind_b != RECIPE_NO_INPUT) {
            const KindDef* ib = kind_by_id(r->input_kind_b);
            CHECK(ib != NULL, "recipe: input B is a real kind");
            in_value += (uint32_t)ib->value * r->input_qty_b;
        }
        /* A row that can't pull FLOOR (a power recipe) pays no oddment. */
        CHECK(r->weight_floor == 0 || (uint32_t)odd->value < in_value,
              "recipe: FLOOR is a net loss — the Forge is never income");
        CHECK(r->cls == RC_RESTORATIVE || r->weight_floor == 0 || r->cls == RC_DESTRUCTIVE,
              "recipe: a power recipe never pulls FLOOR (found components are never eaten)");
        CHECK(recipe_known((uint8_t)i, 0) == (r->cls == RC_RESTORATIVE) &&
              recipe_known((uint8_t)i, RECIPE_BIT(i)),
              "recipe: restorative rows start known; the others only once learned");

        /* ⚠ RECORDED CONSEQUENCE, not yet a decision. At the current catalog
         * the oddment is worth LESS than one shard, so it cannot be sold at
         * any vendor at any delta — `trade_shards_earned(2)` is 0. It is a
         * real sink (clay pot is an input to Honed Edge), but "sellable
         * oddment" in recipes.h is no longer true in the sense a player can
         * act on. The squeeze is structural, not a bad pick: the invariant
         * caps Fungal Distillate's oddment below 6 value, and every kind
         * under 5 value is sub-shard by construction. Resolving it needs
         * either a cheap kind priced at 5+, or lots-based selling. */
        CHECK(trade_shards_earned(odd->value) == 0,
              "recipe: the oddment is currently sub-shard (recorded, open)");

        /* Weights still sum to 100 — unchanged by the pivot, pinned here so
         * a future oddment edit cannot quietly break the roll. */
        CHECK(r->weight_floor + r->weight_hit + r->weight_jackpot == 100,
              "recipe: tier weights sum to 100");
    }
}

static void test_econ_vendor_golden(void) {
    /* §17.11's v0.6.0 bullet asked for a golden that "FAILS with the
     * trailing-zero mapping removed". MEASURED CORRECTION: there is no such
     * mapping at this call site to remove. The rng_chunk_seed point-symmetry
     * collision (mirrored coords share a trailing-zero count) is a property
     * of rng_chunk_seed, and trade.c does NOT use it — it has its own
     * full-avalanche FNV-1a (`trade_hash32`) mixing all four words. The
     * hazard never applied here.
     *
     * So the honest guard is the OUTCOME the AC wanted: mirrored chunks must
     * be economically distinct. This fails loudly if anyone ever "unifies"
     * trade onto rng_chunk_seed. */
    int differing = 0, total = 0;
    for(int n = 1; n <= 64; n++) {
        for(uint8_t k = 0; k < (uint8_t)KIND_COUNT; k++) {
            int8_t a = chunk_price_delta(0xCAFEBABEu,  n,  n, k);
            int8_t b = chunk_price_delta(0xCAFEBABEu, -n, -n, k);
            total++;
            if(a != b) differing++;
        }
    }
    /* Not "most" — mirrored chunks must be independent draws, so collisions
     * should be at chance (~1/101 per pair), never structural. */
    CHECK(differing > (total * 95) / 100,
          "econ: mirrored chunks (n,n)/(-n,-n) are economically distinct");
    printf("  econ: %d/%d mirrored (chunk,kind) pairs differ\n",
           differing, total);

    /* Deltas stay in the declared range for every kind, mirrored or not. */
    for(int n = -32; n <= 32; n++) {
        for(uint8_t k = 0; k < (uint8_t)KIND_COUNT; k++) {
            int8_t d = chunk_price_delta(0xDEADBEEFu, n, n * 3 - 1, k);
            CHECK(d >= -50 && d <= 50, "econ: delta stays in [-50,+50]");
        }
    }
}

static void test_shard_denomination(void) {
    /* §17.5 + §17.5a rule 1 — truncate toward the PLAYER'S loss. */
    CHECK(trade_shards_earned(0)  == 0, "denom: nothing earns nothing");
    CHECK(trade_shards_earned(4)  == 0, "denom: 4 value earns 0 shards");
    CHECK(trade_shards_earned(5)  == 1, "denom: 5 value earns 1 shard");
    CHECK(trade_shards_earned(9)  == 1, "denom: 9 value earns 1 (remainder lost)");
    CHECK(trade_shards_earned(10) == 2, "denom: 10 value earns 2");

    CHECK(trade_shards_owed(0)  == 0, "denom: nothing owes nothing");
    CHECK(trade_shards_owed(1)  == 1, "denom: 1 value owes a whole shard");
    CHECK(trade_shards_owed(5)  == 1, "denom: 5 value owes 1");
    CHECK(trade_shards_owed(6)  == 2, "denom: 6 value owes 2 (rounds against you)");
    CHECK(trade_shards_owed(10) == 2, "denom: 10 value owes 2");

    /* The rule is only meaningful if it is ASYMMETRIC against the player:
     * you never earn more than you would owe for the same value. */
    for(uint16_t v = 0; v <= 200; v++) {
        CHECK(trade_shards_earned(v) <= trade_shards_owed(v),
              "denom: the remainder is always the player's loss");
    }

    /* §17.5's rejected option, pinned: max bag value must fit uint16, which
     * is what disqualified "shard = 1, rescale the catalog x5". */
    uint32_t max_bag = 0;
    for(int i = 0; i < KIND_COUNT; i++) max_bag += 255u * kind_by_id((uint8_t)i)->value;
    CHECK(max_bag <= 0xFFFFu, "denom: max bag value fits uint16 at 1x scale");
    CHECK(max_bag * 5u > 0xFFFFu, "denom: it would NOT fit rescaled x5");
}

static void test_trade_vendor_placement_walkable(void) {
    /* Across a sweep, generate cavern + outdoor chunks; any vendor that
     * exists must sit on a walkable TILE_VENDOR (not buried by a stamp). */
    int seen = 0;
    for(int cy = -8; cy <= 8; cy++) {
        for(int cx = -8; cx <= 8; cx++) {
            World w;
            world_generate_chunk(0xC0FFEE12u, cx, cy, &w);
            int vx = -1, vy = -1;
            for(int y = 0; y < WORLD_ROWS; y++) {
                for(int x = 0; x < WORLD_COLS; x++) {
                    if(w.tiles[y][x] == TILE_VENDOR) { vx = x; vy = y; }
                }
            }
            if(vx >= 0) {
                seen++;
                CHECK(world_walkable(&w, vx, vy),
                      "trade: vendor tile is walkable in-world");
            }
        }
    }
    CHECK(seen > 0, "trade: sweep observed at least one vendor chunk");
}

/* ── egress (carve_egress anti-trap) ─────────────────────────────────
 *
 * Before the carve, the stamp composer could wall off the spawn from one
 * or all of the 4 cavern doors. The carve guarantees: in every cavern,
 * the spawn shares a 4-connected walkable component with all 4 doors.
 * Test that across a generous sweep — many seeds × many chunks. */

/* 4-connected flood from (sx,sy) over walkable tiles. Returns which of
 * the 4 doors are in the component. */
static int egress_doors_reachable(const World* w, int sx, int sy) {
    if(!world_walkable(w, sx, sy)) return 0;
    uint8_t reach[WORLD_ROWS][WORLD_COLS];
    memset(reach, 0, sizeof(reach));
    int qx[WORLD_ROWS * WORLD_COLS];
    int qy[WORLD_ROWS * WORLD_COLS];
    int head = 0, tail = 0;
    qx[tail] = sx; qy[tail] = sy; tail++;
    reach[sy][sx] = 1;
    const int dx[4] = {0, 0, 1, -1};
    const int dy[4] = {-1, 1, 0, 0};
    while(head < tail) {
        int x = qx[head], y = qy[head]; head++;
        for(int d = 0; d < 4; d++) {
            int nx = x + dx[d], ny = y + dy[d];
            if(nx < 0 || nx >= WORLD_COLS || ny < 0 || ny >= WORLD_ROWS) continue;
            if(reach[ny][nx]) continue;
            if(!world_walkable(w, nx, ny)) continue;
            reach[ny][nx] = 1;
            qx[tail] = nx; qy[tail] = ny; tail++;
        }
    }
    /* Doors sit at hashed per-edge positions now — find the actual TILE_DOOR
     * tiles on the border (seed-agnostic) and count how many are in the
     * spawn's connected component. A cavern has exactly one door per edge. */
    int hits = 0;
    for(int x = 0; x < WORLD_COLS; x++) {
        if(w->tiles[0][x] == TILE_DOOR && reach[0][x]) hits++;
        if(w->tiles[WORLD_ROWS - 1][x] == TILE_DOOR && reach[WORLD_ROWS - 1][x]) hits++;
    }
    for(int y = 0; y < WORLD_ROWS; y++) {
        if(w->tiles[y][0] == TILE_DOOR && reach[y][0]) hits++;
        if(w->tiles[y][WORLD_COLS - 1] == TILE_DOOR && reach[y][WORLD_COLS - 1]) hits++;
    }
    return hits;
}

static void test_cavern_egress_no_trap(void) {
    /* Sweep many (seed, cx, cy) tuples. Every cavern chunk MUST have its
     * spawn reach all 4 doors. The stress sample is generous enough that
     * pre-carve, this test would have caught the playtest 2026-06-03
     * sealed-room bug — we found one sealed chunk in the first ~10 we
     * probed by hand (CAFEBABE 0,0 had its N door isolated). */
    uint32_t seeds[] = {
        0xCAFEBABE, 0xDEADBEEF, 0x12345678, 0x00000001,
        0xFEEDFACE, 0x8BADF00D, 0xBADD1DEA, 0x1337C0DE,
    };
    int n_seeds = (int)(sizeof(seeds) / sizeof(seeds[0]));
    int caverns_seen = 0, traps = 0;
    for(int s = 0; s < n_seeds; s++) {
        for(int cy = -4; cy <= 4; cy++) {
            for(int cx = -4; cx <= 4; cx++) {
                World w;
                world_generate_chunk(seeds[s], cx, cy, &w);
                if(world_terrain(&w) != TERRAIN_WALLED) continue;
                caverns_seen++;
                int reachable = egress_doors_reachable(&w, w.spawn_x, w.spawn_y);
                if(reachable < 4) {
                    traps++;
                    printf("    egress trap: seed=0x%08lX (%d,%d) spawn=(%d,%d) "
                           "doors reachable=%d/4\n",
                           (unsigned long)seeds[s], cx, cy,
                           w.spawn_x, w.spawn_y, reachable);
                }
            }
        }
    }
    printf("  egress: scanned %d cavern chunks across %d seeds, %d traps\n",
           caverns_seen, n_seeds, traps);
    CHECK(caverns_seen > 50, "egress: stress sample large enough");
    CHECK(traps == 0, "egress: zero sealed caverns after carve");
}

/* Specifically the chunks that exhibited the bug pre-fix. Locks in the
 * regression so we know the carve actually neutralised the documented
 * trap, not just statistically. */
static void test_cavern_egress_known_traps(void) {
    struct { uint32_t seed; int cx, cy; } cases[] = {
        /* From the playtest probe — CAFEBABE (0,0) had its N door sealed
         * (approach tile (8,1) was a wall). Post-carve must be all 4. */
        { 0xCAFEBABE, 0, 0 },
        { 0xCAFEBABE, 1, 0 },
    };
    int n = (int)(sizeof(cases) / sizeof(cases[0]));
    for(int i = 0; i < n; i++) {
        World w;
        world_generate_chunk(cases[i].seed, cases[i].cx, cases[i].cy, &w);
        if(world_terrain(&w) != TERRAIN_WALLED) continue;
        int reachable = egress_doors_reachable(&w, w.spawn_x, w.spawn_y);
        CHECK(reachable == 4,
              "egress: previously-sealed chunk now fully connected");
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

/* slice 5 — KF_EQUIP kinds carry an equip_slot and the corresponding
 * bonus column is non-zero; non-equip kinds carry EQ_NONE with zeroed
 * bonus columns. Keeps the data shape honest as new equipment lands. */
static void test_loot_equip_shape(void) {
    int any_weapon = 0;
    for(int i = 0; i < KIND_COUNT; i++) {
        const KindDef* k = &KIND_CATALOG[i];
        if(k->flags & KF_EQUIP) {
            CHECK(k->equip_slot != EQ_NONE,
                  "loot: KF_EQUIP kind must declare an equip_slot");
            switch((EquipSlot)k->equip_slot) {
            case EQ_WEAPON:
                CHECK(k->atk_bonus > 0,
                      "loot: weapon kind contributes positive atk_bonus");
                any_weapon = 1;
                break;
            case EQ_ARMOR:
                CHECK(k->def_bonus > 0,
                      "loot: armor kind contributes positive def_bonus");
                break;
            case EQ_LIGHT:
                CHECK(k->light_bonus > 0,
                      "loot: light kind contributes positive light_bonus");
                break;
            default: break;
            }
        } else {
            CHECK(k->equip_slot == EQ_NONE,
                  "loot: non-equip kind has EQ_NONE slot");
            CHECK(k->atk_bonus == 0 && k->def_bonus == 0 && k->light_bonus == 0,
                  "loot: non-equip kind has zero bonus columns");
        }
    }
    CHECK(any_weapon, "loot: at least one EQ_WEAPON kind in catalog");

    /* The slice-5 tool keeps its v0.4.1 numbers: weapon slot, +2 atk. */
    const KindDef* tool = kind_by_glyph('(');
    CHECK(tool != NULL, "loot: tool glyph still resolves");
    if(tool) {
        CHECK(tool->equip_slot == EQ_WEAPON, "loot: tool routes to weapon");
        CHECK(tool->atk_bonus == 2, "loot: tool atk_bonus == 2");
    }
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

/* ── creatures (spec 45 §4.5-4.9) ───────────────────────────────────── */

static void test_creatures_catalog_integrity(void) {
    CHECK(CREATURE_FAMILY_COUNT > 0, "creatures: families present");
    CHECK(CREATURE_TRAIT_COUNT > 0, "creatures: traits present");
    /* trait[0] is the "plain" no-op adaptation */
    CHECK(CREATURE_TRAITS[0].affix[0] == '\0', "creatures: trait[0] plain (no affix)");
    CHECK(CREATURE_TRAITS[0].d_hp == 0 && CREATURE_TRAITS[0].d_atk == 0 &&
              CREATURE_TRAITS[0].d_def == 0 && CREATURE_TRAITS[0].d_speed == 0,
          "creatures: trait[0] has zero deltas");

    int glyphs_ok = 1, fw_ok = 1, fb_ok = 1;
    for(int i = 0; i < CREATURE_FAMILY_COUNT; i++) {
        /* the dead never spawn by the roll: they only rise (spec 50 Q1 §Q.3) */
        if(CREATURE_FAMILIES[i].weight == 0 && i != FAMILY_DEAD) fw_ok = 0;
        if(CREATURE_FAMILIES[i].biomes == 0) fb_ok = 0;
        for(int j = i + 1; j < CREATURE_FAMILY_COUNT; j++) {
            if(CREATURE_FAMILIES[i].glyph == CREATURE_FAMILIES[j].glyph) glyphs_ok = 0;
        }
    }
    CHECK(glyphs_ok, "creatures: family glyphs distinct");
    CHECK(fw_ok, "creatures: family weights nonzero (but the dead's)");
    CHECK(CREATURE_FAMILIES[FAMILY_DEAD].weight == 0 && CREATURE_FAMILIES[FAMILY_DEAD].glyph == 'D',
          "creatures: the dead (D) never come from the spawn roll");
    CHECK(fb_ok, "creatures: family biome masks nonzero");

    int tw_ok = 1, tb_ok = 1;
    for(int i = 0; i < CREATURE_TRAIT_COUNT; i++) {
        if(CREATURE_TRAITS[i].weight == 0) tw_ok = 0;
        if(CREATURE_TRAITS[i].biome_mask == 0) tb_ok = 0;
    }
    CHECK(tw_ok, "creatures: trait weights nonzero");
    CHECK(tb_ok, "creatures: trait biome masks nonzero");
}

static void test_creature_compose(void) {
    CreatureDef d;
    char name[24];

    /* rat (family 0) + plain (trait 0) */
    creature_compose(0, 0, &d);
    CHECK(d.hp == 3, "compose: plain rat hp=3");
    CHECK(d.element == ELEM_NONE, "compose: plain rat no element");
    CHECK((d.flags & CF_PACK) != 0, "compose: rat is pack");
    creature_name(&d, name, sizeof(name));
    CHECK(strcmp(name, "rat") == 0, "compose: plain rat name 'rat'");

    /* rat + frost (trait 1): +1 hp, ice, +photophobic, -1 speed, keep pack */
    creature_compose(0, 1, &d);
    CHECK(d.hp == 4, "compose: frost rat hp=4");
    CHECK(d.element == ELEM_ICE, "compose: frost rat ice");
    CHECK((d.flags & CF_PHOTOPHOBIC) != 0, "compose: frost adds photophobic");
    CHECK((d.flags & CF_PACK) != 0, "compose: family flags preserved");
    CHECK(d.speed == 13, "compose: frost rat speed 14-1=13");
    creature_name(&d, name, sizeof(name));
    CHECK(strcmp(name, "frost-rat") == 0, "compose: name 'frost-rat'");

    /* bat (family 3) flies */
    creature_compose(3, 0, &d);
    CHECK((d.flags & CF_FLIGHT) != 0, "compose: bat flies");

    /* out-of-range ids fall back to a valid creature, never UB */
    creature_compose(250, 250, &d);
    CHECK(d.hp >= 1, "compose: bad ids clamp to a valid creature");
}

static void test_creature_roll(void) {
    /* determinism: same seed → identical roll sequence (port-ready) */
    Rng a, b;
    rng_seed(&a, 0xBEEF);
    rng_seed(&b, 0xBEEF);
    int identical = 1;
    for(int i = 0; i < 500; i++) {
        uint8_t fa, ta, fb, tb;
        creature_roll(&a, BIOME_CAVERN, &fa, &ta);
        creature_roll(&b, BIOME_CAVERN, &fb, &tb);
        if(fa != fb || ta != tb) identical = 0;
    }
    CHECK(identical, "creatures: same seed -> identical roll sequence");

    /* biome-lock: a trait roll only ever yields a trait legal for the biome */
    Rng r;
    rng_seed(&r, 0x1234);
    int cave_clean = 1, out_clean = 1, fam_clean = 1;
    for(int i = 0; i < 4000; i++) {
        uint8_t t = creature_trait_roll(&r, BIOME_CAVERN);
        if(!(CREATURE_TRAITS[t].biome_mask & BIOME_BIT(BIOME_CAVERN))) cave_clean = 0;
    }
    for(int i = 0; i < 4000; i++) {
        uint8_t t = creature_trait_roll(&r, BIOME_OUTDOOR);
        if(!(CREATURE_TRAITS[t].biome_mask & BIOME_BIT(BIOME_OUTDOOR))) out_clean = 0;
    }
    for(int i = 0; i < 4000; i++) {
        uint8_t f = creature_family_roll(&r, BIOME_OUTDOOR);
        if(!(CREATURE_FAMILIES[f].biomes & BIOME_BIT(BIOME_OUTDOOR))) fam_clean = 0;
    }
    CHECK(cave_clean, "creatures: cavern trait rolls respect biome-lock");
    CHECK(out_clean, "creatures: outdoor trait rolls respect biome-lock");
    CHECK(fam_clean, "creatures: family rolls respect biome affinity");
}

static void test_creatures_populate(void) {
    World w;
    world_generate_chunk(0xCAFEBABE, 0, 0, &w);
    uint32_t cs = rng_chunk_seed(0xCAFEBABE, 0, 0);

    Creature a[CREATURES_MAX], b[CREATURES_MAX];
    int na = creatures_populate(cs, w.biome, &w, w.spawn_x, w.spawn_y, a, CREATURES_MAX);
    int nb = creatures_populate(cs, w.biome, &w, w.spawn_x, w.spawn_y, b, CREATURES_MAX);

    CHECK(na == nb, "populate: deterministic count");
    CHECK(na >= 0 && na <= CREATURES_MAX, "populate: count within cap");
    int same = (na == nb);
    for(int i = 0; i < na && same; i++) {
        if(a[i].x != b[i].x || a[i].y != b[i].y ||
           a[i].family_id != b[i].family_id || a[i].trait_id != b[i].trait_id)
            same = 0;
    }
    CHECK(same, "populate: deterministic placement (same seed)");

    int valid = 1;
    for(int i = 0; i < na; i++) {
        if(!world_walkable(&w, a[i].x, a[i].y)) valid = 0;
        if(a[i].x == (uint8_t)w.spawn_x && a[i].y == (uint8_t)w.spawn_y) valid = 0;
        if(!a[i].alive) valid = 0;
    }
    CHECK(valid, "populate: creatures on walkable, non-spawn tiles");
}

/* ── the light rules (spec 45 §5.5) ──────────────────────────────────────────
 * ⚠️ THESE EXIST BECAUSE THE FLAGS DID NOT. CF_PHOTOPHOBIC and CF_PHOTOPHILIC
 * were authored into the bestiary and read by NOTHING in the app; the only read
 * anywhere was `test_compose`'s CHECK that composing "frost-" SETS the flag —
 * a green assertion whose subject was the assignment, not the behaviour. Every
 * check below asserts on POSITION, never on the flag, so deleting the rule in
 * creatures.c fails here rather than passing on the table that declares it. */
static void test_light_rules(void) {
    World w;
    world_generate_chunk(0xCAFEBABEu, 0, 0, &w);

    /* frost-slime: photophobic via the trait, flee 0 and DISP_PASSIVE via the
     * family — so the flag is the ONLY thing that can make it retreat. */
    const uint8_t F_SLIME = 4, T_FROST = 1, F_BAT = 3, T_PLAIN = 0;
    CreatureDef dbg;
    creature_compose(F_SLIME, T_FROST, &dbg);
    CHECK((dbg.flags & CF_PHOTOPHOBIC) != 0, "light: frost-slime composes photophobic");
    CHECK(dbg.flee == 0, "light: frost-slime has flee 0, so only the flag can move it");
    creature_compose(F_BAT, T_PLAIN, &dbg);
    CHECK((dbg.flags & CF_PHOTOPHILIC) != 0, "light: bat composes photophilic");

    int px = w.spawn_x, py = w.spawn_y;
    #define MKC(fam, tr, ox, oy) { \
        .family_id = (fam), .trait_id = (tr), \
        .x = (uint8_t)(px + (ox)), .y = (uint8_t)(py + (oy)), \
        .state = CR_IDLE, .energy = 0, .aggro = 0, .alive = 1, \
        .spawn_x = (uint8_t)(px + (ox)), .spawn_y = (uint8_t)(py + (oy)) }
    #define CHEB(c) ({ int _dx=(int)(c).x-px, _dy=(int)(c).y-py; \
                       _dx=_dx<0?-_dx:_dx; _dy=_dy<0?-_dy:_dy; _dx>_dy?_dx:_dy; })

    /* 1. IT WILL NOT STAND IN YOUR LIGHT. Asserted as distance GROWING, not as
     *    state == CR_FLEE — a state check passes even if no step is ever taken. */
    {
        Creature c = MKC(F_SLIME, T_FROST, 2, 0);
        int d0 = CHEB(c);
        for(uint32_t t = 1; t <= 6; t++) creatures_tick(&c, 1, &w, px, py, 4, 0xA1u, t, NULL);
        CHECK(CHEB(c) > d0, "light: a photophobic creature retreats out of the lit radius");
    }

    /* 2. ⚠️ BOLDER AS YOUR TORCH DIMS, AND IT IS GEOMETRY RATHER THAN AGGRO.
     *    Same creature, same turns, two torch radii: the bright torch must hold
     *    it further off than the guttering one. This is the assertion that goes
     *    red if the rule stops reading torch_radius and becomes a constant ring. */
    {
        Creature bright = MKC(F_SLIME, T_FROST, 1, 0);
        Creature dim    = MKC(F_SLIME, T_FROST, 1, 0);
        for(uint32_t t = 1; t <= 8; t++) {
            creatures_tick(&bright, 1, &w, px, py, 4, 0xA2u, t, NULL);
            creatures_tick(&dim,    1, &w, px, py, 2, 0xA2u, t, NULL);
        }
        CHECK(CHEB(bright) >= CHEB(dim),
              "light: a bright torch holds a photophobic creature no closer than a dim one");
    }

    /* 3. HOSTILITY OVERRIDES THE LIGHT. Provoked past its threshold it comes
     *    anyway — light never protects you from something you already wronged. */
    {
        Creature c = MKC(F_SLIME, T_FROST, 4, 0);
        CreatureDef d; creature_compose(F_SLIME, T_FROST, &d);
        c.aggro = (uint8_t)(d.provoke > 0 ? d.provoke + 4 : 255);
        int d0 = CHEB(c);
        for(uint32_t t = 1; t <= 6; t++) creatures_tick(&c, 1, &w, px, py, 4, 0xA3u, t, NULL);
        CHECK(CHEB(c) <= d0, "light: a PROVOKED photophobic creature is not held off by the torch");
    }

    /* 4. DRAWN IS NOT HOSTILE — it arrives and it WAITS. Asserted as "never
     *    closer than the standoff", checked every turn, because a creature that
     *    steps in and back out would pass an end-state check. */
    {
        Creature c = MKC(F_BAT, T_PLAIN, 4, 0);
        int closest = CHEB(c), ever_engaged = 0;
        for(uint32_t t = 1; t <= 20; t++) {
            creatures_tick(&c, 1, &w, px, py, 4, 0xA4u, t, NULL);
            int dd = CHEB(c);
            if(dd < closest) closest = dd;
            if(c.state == CR_ENGAGE) ever_engaged = 1;
        }
        CHECK(closest <= 3, "light: a photophilic creature actually crosses toward the light");
        CHECK(closest >= PHOTO_STANDOFF,
              "light: a photophilic creature closed inside the standoff — being drawn became an attack");
        CHECK(!ever_engaged, "light: being drawn to the light turned into an engagement");
    }

    /* 5. ⚠️ WITH THE TORCH NEARLY OUT THERE IS NOTHING TO COME TO — and this
     *    check is placed where the TORCH is the only variable that can decide
     *    it. Distance 5 is OUTSIDE the lit pool at every fuel level (max radius
     *    4) and INSIDE the bat's notice of 6, so `aware` is false in both runs
     *    and the two differ only in torch_radius.
     *
     *    ⚠️ THE FIRST VERSION OF THIS TEST WAS AN ANTI-TEST and mutation testing
     *    is what exposed it: it stood the creature at distance 3 and asserted it
     *    did not approach at radius 1 — which passed because 3 > 1 put it out of
     *    AWARENESS, not because the draw was gated. Deleting the guard entirely
     *    left it green. A check must be sited where the term it names is the
     *    thing that moves the outcome. */
    {
        Creature dead_torch  = MKC(F_BAT, T_PLAIN, 5, 0);
        Creature bright      = MKC(F_BAT, T_PLAIN, 5, 0);
        int approached_dead = 0, approached_bright = 0;
        for(uint32_t t = 1; t <= 12; t++) {
            creatures_tick(&dead_torch, 1, &w, px, py, 1, 0xA5u, t, NULL);
            creatures_tick(&bright,     1, &w, px, py, 4, 0xA5u, t, NULL);
            if(dead_torch.state == CR_APPROACH) approached_dead = 1;
            if(bright.state == CR_APPROACH)     approached_bright = 1;
        }
        CHECK(approached_bright,
              "light: a bright torch did not draw a photophilic creature from beyond its pool — the draw cannot reach past the light and its guard is inert");
        CHECK(!approached_dead,
              "light: a guttering torch still drew a photophilic creature — it is being drawn to YOU, not to light");
    }
    #undef MKC
    #undef CHEB
}

static void test_creatures_tick(void) {
    World w;
    world_generate_chunk(0xCAFEBABE, 0, 0, &w);
    uint32_t cs = rng_chunk_seed(0xCAFEBABE, 0, 0);
    Creature a[CREATURES_MAX], b[CREATURES_MAX];
    int na = creatures_populate(cs, w.biome, &w, w.spawn_x, w.spawn_y, a, CREATURES_MAX);
    int nb = creatures_populate(cs, w.biome, &w, w.spawn_x, w.spawn_y, b, CREATURES_MAX);

    /* two identical runs must stay bit-identical across many turns */
    int px = w.spawn_x, py = w.spawn_y;
    int same = (na == nb);
    for(uint32_t t = 1; t <= 25 && same; t++) {
        creatures_tick(a, na, &w, px, py, 4, cs, t, NULL);
        creatures_tick(b, nb, &w, px, py, 4, cs, t, NULL);
        for(int i = 0; i < na && same; i++) {
            if(a[i].x != b[i].x || a[i].y != b[i].y || a[i].state != b[i].state ||
               a[i].aggro != b[i].aggro)
                same = 0;
        }
    }
    CHECK(same, "tick: deterministic over 25 turns");

    int ok = 1, walls = 1;
    for(int i = 0; i < na; i++) {
        if(a[i].x >= WORLD_COLS || a[i].y >= WORLD_ROWS) ok = 0;
        if(a[i].x == (uint8_t)px && a[i].y == (uint8_t)py) ok = 0; /* never on player */
        CreatureDef d;
        creature_compose(a[i].family_id, a[i].trait_id, &d);
        if(w.tiles[a[i].y][a[i].x] == TILE_WALL && !(d.flags & CF_FLIGHT)) walls = 0;
    }
    CHECK(ok, "tick: creatures in-bounds, off the player tile");
    CHECK(walls, "tick: ground creatures never stand on walls");
}

static void test_creature_scan(void) {
    /* tier: always >= 1; meets diff → 2; +15 margin → 3 */
    CHECK(creature_scan_tier(10, 30) == 1, "scan tier: below diff = basic");
    CHECK(creature_scan_tier(30, 30) == 2, "scan tier: meets diff = full");
    CHECK(creature_scan_tier(45, 30) == 3, "scan tier: +15 margin = deep");
    CHECK(creature_scan_tier(20, 0) == 3, "scan tier: high observe vs trivial = deep");
    CHECK(creature_scan_tier(0, 0) == 2, "scan tier: meets (no margin) = full");

    /* cost positive + monotone in difficulty */
    CHECK(creature_scan_cost(15) >= 1, "scan cost: positive");
    CHECK(creature_scan_cost(30) >= creature_scan_cost(15), "scan cost: harder >= easier");

    /* bestiary: per-family pack/unpack, independent, overwrite, bounds */
    uint16_t b = 0;
    b = creature_bestiary_set(b, 0, 3);
    b = creature_bestiary_set(b, 3, 2);
    CHECK(creature_bestiary_grade(b, 0) == 3, "bestiary: family 0 grade 3");
    CHECK(creature_bestiary_grade(b, 3) == 2, "bestiary: family 3 grade 2");
    CHECK(creature_bestiary_grade(b, 1) == 0, "bestiary: untouched family is 0");
    b = creature_bestiary_set(b, 0, 1);
    CHECK(creature_bestiary_grade(b, 0) == 1, "bestiary: overwrite family 0");
    CHECK(creature_bestiary_grade(b, 3) == 2, "bestiary: neighbour intact");
    CHECK(creature_bestiary_set(b, 99, 3) == b, "bestiary: out-of-range family is no-op");

    /* hostility: innate or provoked-past-threshold */
    CHECK(creature_is_hostile(DISP_HOSTILE, 0, 0), "hostile: innate hostile");
    CHECK(!creature_is_hostile(DISP_PASSIVE, 10, 5), "hostile: below provoke = calm");
    CHECK(creature_is_hostile(DISP_PASSIVE, 10, 10), "hostile: aggro>=provoke = hostile");
    CHECK(!creature_is_hostile(DISP_PASSIVE, 0, 99), "hostile: provoke 0 non-hostile stays calm");
}

static void test_creatures_aggro(void) {
    /* all-floor arena so movement is unconstrained */
    World w;
    memset(&w, 0, sizeof(w));
    for(int y = 0; y < WORLD_ROWS; y++)
        for(int x = 0; x < WORLD_COLS; x++) w.tiles[y][x] = TILE_FLOOR;
    w.biome = BIOME_CAVERN;
    w.style = style_for_biome(BIOME_CAVERN);
    w.spawn_x = 0;
    w.spawn_y = 0;

    /* a passive beetle (family 1, provoke 10) one tile from the player: dist 1
     * → ENGAGE (holds), but aware + in-notice → aggro climbs until it crosses
     * provoke and turns hostile (a reported contact). */
    Creature c;
    memset(&c, 0, sizeof(c));
    c.family_id = 1; /* beetle */
    c.x = 5;
    c.y = 3;
    c.alive = 1;
    int px = 5, py = 4;

    uint8_t start = c.aggro;
    int turned_hostile = 0;
    for(uint32_t t = 1; t <= 20; t++) {
        if(creatures_tick(&c, 1, &w, px, py, 4, 0xABCDu, t, NULL) > 0) turned_hostile = 1;
    }
    CHECK(c.aggro > start, "aggro: crowding a creature raises its aggression");
    CHECK(turned_hostile, "aggro: a crowded passive creature turns hostile");

    /* it calms once you leave its awareness (player off in the void) */
    uint8_t high = c.aggro;
    for(uint32_t t = 21; t <= 80; t++) {
        creatures_tick(&c, 1, &w, 50, 50, 4, 0xABCDu, t, NULL);
    }
    CHECK(c.aggro < high, "aggro: decays when you leave its awareness");
}

/* ── weather × creatures (slice 2026-06-03b) ────────────────────────
 *
 * Make weather strategic: HUD glyph + creature AI weather-aware. The
 * rules under test:
 *   STORM / DUST_STORM grounds flyers (CF_FLIGHT cleared this turn)
 *   FOG extends stealth-affinity notice by +1 (spiders + bats)
 *   HEAT dampens aggro rise by 1 (floored at 0)
 *   RAIN doubles aggro decay for ELEM_FIRE trait creatures
 *
 * Each test isolates ONE rule by holding everything else constant
 * across a CLEAR control and a non-CLEAR test condition. */

static void test_weather_hud_glyph(void) {
    Weather clear = { .kind = WEATHER_CLEAR };
    Weather fog   = { .kind = WEATHER_FOG };
    Weather rain  = { .kind = WEATHER_RAIN };
    Weather storm = { .kind = WEATHER_STORM };
    Weather heat  = { .kind = WEATHER_HEAT };
    Weather dust  = { .kind = WEATHER_DUST_STORM };
    CHECK(weather_hud_glyph(&clear) == '\0', "hud: clear has no glyph");
    CHECK(weather_hud_glyph(&fog)   == '~',  "hud: fog is wave");
    CHECK(weather_hud_glyph(&rain)  == '\'', "hud: rain is drop");
    CHECK(weather_hud_glyph(&storm) == '*',  "hud: storm is chaos");
    CHECK(weather_hud_glyph(&heat)  == '^',  "hud: heat rises");
    CHECK(weather_hud_glyph(&dust)  == '_',  "hud: dust blows low");
    CHECK(weather_hud_glyph(NULL)   == '\0', "hud: null weather is silent");
}

/* Bat (family 3, CF_FLIGHT) wants to approach the player but a TILE_ROCK
 * sits between them. CLEAR weather: CF_FLIGHT lets the bat overfly the
 * rock — it advances. STORM weather: the wind grounds it — CF_FLIGHT is
 * cleared for the turn, the bat is stopped at the rock. */
static void test_creatures_storm_grounds_flyers(void) {
    World w;
    memset(&w, 0, sizeof(w));
    for(int y = 0; y < WORLD_ROWS; y++)
        for(int x = 0; x < WORLD_COLS; x++) w.tiles[y][x] = TILE_FLOOR;
    w.tiles[2][5] = TILE_ROCK; /* obstacle between bat and player */
    w.biome = BIOME_OUTDOOR;
    w.style = style_for_biome(BIOME_OUTDOOR);

    Creature c_clear;
    memset(&c_clear, 0, sizeof(c_clear));
    c_clear.family_id = 3; /* bat */
    c_clear.x = 5; c_clear.y = 3; c_clear.alive = 1;
    Creature c_storm = c_clear;

    Weather clear = { .kind = WEATHER_CLEAR };
    Weather storm = { .kind = WEATHER_STORM };
    int px = 5, py = 0; /* north of the bat, behind the rock */

    creatures_tick(&c_clear, 1, &w, px, py, 4, 0xAAAAu, 1, &clear);
    creatures_tick(&c_storm, 1, &w, px, py, 4, 0xAAAAu, 1, &storm);

    CHECK(c_clear.y < 3, "storm-grounds: CLEAR — bat overflies the rock toward player");
    CHECK(c_storm.x == 5 && c_storm.y == 3,
          "storm-grounds: STORM — bat held at the rock (flight suppressed)");
}

/* Spider (family 2, notice=4) standing exactly one tile beyond its
 * normal awareness. CLEAR: dist > notice → aggro never rises. FOG:
 * notice extends to 5; dist ≤ notice → aggro accumulates. */
static void test_creatures_fog_extends_stealth_notice(void) {
    World w;
    memset(&w, 0, sizeof(w));
    for(int y = 0; y < WORLD_ROWS; y++)
        for(int x = 0; x < WORLD_COLS; x++) w.tiles[y][x] = TILE_FLOOR;
    w.biome = BIOME_CAVERN;
    w.style = style_for_biome(BIOME_CAVERN);

    Creature c_clear;
    memset(&c_clear, 0, sizeof(c_clear));
    c_clear.family_id = 2; /* spider, notice=4 */
    c_clear.x = 0; c_clear.y = 0; c_clear.alive = 1;
    Creature c_fog = c_clear;

    Weather clear = { .kind = WEATHER_CLEAR };
    Weather fog   = { .kind = WEATHER_FOG };
    /* Player at (5, 0): Chebyshev dist = 5 from spider. Spider notice
     * is 4 normally; fog extends to 5. torch_radius=6 so aware=true. */
    int px = 5, py = 0;

    creatures_tick(&c_clear, 1, &w, px, py, 6, 0xBBBBu, 1, &clear);
    creatures_tick(&c_fog,   1, &w, px, py, 6, 0xBBBBu, 1, &fog);

    CHECK(c_clear.aggro == 0,
          "fog-notice: CLEAR — spider outside notice radius stays unprovoked");
    CHECK(c_fog.aggro > 0,
          "fog-notice: FOG — spider stalks one tile further into mist");
}

/* Beetle (family 1, flee=1, provoke=10) standing adjacent to the player.
 * Energy mechanics: beetle speed=8, threshold=12 — it acts roughly every
 * other turn. Aggro rise per ACT: 1 base + 1 flee-bubble bonus = 2.
 * Over 20 turns CLEAR easily crosses provoke (matches the baseline
 * test_creatures_aggro). HEAT subtracts 1 from rise (floored at 0) so
 * each act rises by 1 — significantly slower aggression. The control
 * vs heat delta is the rule under test. */
static void test_creatures_heat_dampens_aggro(void) {
    World w;
    memset(&w, 0, sizeof(w));
    for(int y = 0; y < WORLD_ROWS; y++)
        for(int x = 0; x < WORLD_COLS; x++) w.tiles[y][x] = TILE_FLOOR;
    w.biome = BIOME_OUTDOOR;
    w.style = style_for_biome(BIOME_OUTDOOR);

    Creature c_clear;
    memset(&c_clear, 0, sizeof(c_clear));
    c_clear.family_id = 1; /* beetle */
    c_clear.x = 5; c_clear.y = 4; c_clear.alive = 1;
    Creature c_heat = c_clear;

    Weather clear = { .kind = WEATHER_CLEAR };
    Weather heat  = { .kind = WEATHER_HEAT };
    int px = 5, py = 5; /* adjacent — ENGAGE state, no movement, aggro accumulates */

    for(uint32_t t = 1; t <= 20; t++) {
        creatures_tick(&c_clear, 1, &w, px, py, 4, 0xCCCCu, t, &clear);
        creatures_tick(&c_heat,  1, &w, px, py, 4, 0xCCCCu, t, &heat);
    }
    CHECK(c_heat.aggro < c_clear.aggro,
          "heat-dampens: aggro accumulates slower in the summer air");
    CHECK(c_clear.aggro >= 10,
          "heat-dampens: CLEAR baseline crosses provoke (sanity)");
}

/* Rat with ember- trait (family 0, trait 4 — ELEM_FIRE), preset aggro
 * 50, player off the grid (out of awareness). Decay branch fires every
 * turn. CLEAR: decay 2/turn → after 10 turns aggro = 30. RAIN: decay
 * 4/turn → after 10 turns aggro = 10. */
static void test_creatures_rain_pacifies_fire(void) {
    World w;
    memset(&w, 0, sizeof(w));
    for(int y = 0; y < WORLD_ROWS; y++)
        for(int x = 0; x < WORLD_COLS; x++) w.tiles[y][x] = TILE_FLOOR;
    w.biome = BIOME_OUTDOOR;
    w.style = style_for_biome(BIOME_OUTDOOR);

    Creature c_clear;
    memset(&c_clear, 0, sizeof(c_clear));
    c_clear.family_id = 0; /* rat */
    c_clear.trait_id = 4;  /* ember- → ELEM_FIRE */
    c_clear.x = 5; c_clear.y = 3; c_clear.alive = 1;
    c_clear.aggro = 50;
    Creature c_rain = c_clear;

    Weather clear = { .kind = WEATHER_CLEAR };
    Weather rain  = { .kind = WEATHER_RAIN };
    /* Player way off the grid — out of awareness; decay branch dominates. */
    int px = 50, py = 50;

    for(uint32_t t = 1; t <= 10; t++) {
        creatures_tick(&c_clear, 1, &w, px, py, 4, 0xDDDDu, t, &clear);
        creatures_tick(&c_rain,  1, &w, px, py, 4, 0xDDDDu, t, &rain);
    }
    CHECK(c_rain.aggro < c_clear.aggro,
          "rain-pacify: fire-affinity rat calms faster in rain");
}

static void test_creatures_kill_persistence(void) {
    World w;
    world_generate_chunk(0xCAFEBABE, 0, 0, &w);
    uint32_t cs = rng_chunk_seed(0xCAFEBABE, 0, 0);
    Creature a[CREATURES_MAX];
    int na = creatures_populate(cs, w.biome, &w, w.spawn_x, w.spawn_y, a, CREATURES_MAX);
    if(na == 0) {
        CHECK(1, "kill-persistence: (no creatures, skipped)");
        return;
    }

    /* Capture creature 0's spawn position and mark it dead via the helper. */
    uint8_t sx = a[0].spawn_x, sy = a[0].spawn_y;
    creatures_mark_dead_at_spawn(a, na, sx, sy);
    CHECK(!a[0].alive, "kill-persistence: matching spawn marked dead");
    int others_alive = 1;
    for(int i = 1; i < na; i++) {
        if(!a[i].alive) {
            others_alive = 0;
            break;
        }
    }
    CHECK(others_alive, "kill-persistence: non-matching creatures stay alive");

    /* Re-populate (same seed) and re-apply — creature 0 stays dead. */
    Creature b[CREATURES_MAX];
    int nb = creatures_populate(cs, w.biome, &w, w.spawn_x, w.spawn_y, b, CREATURES_MAX);
    CHECK(nb == na, "kill-persistence: re-populate count unchanged");
    creatures_mark_dead_at_spawn(b, nb, sx, sy);
    CHECK(!b[0].alive, "kill-persistence: kill survives re-populate");

    /* Bogus spawn pos = no-op, no crash. */
    creatures_mark_dead_at_spawn(b, nb, 99, 99);
    CHECK(1, "kill-persistence: out-of-range spawn is a no-op");
}

static void test_classes(void) {
    /* Catalog has all four classes, none NULL. */
    CHECK(class_def(CLASS_WANDERER) != NULL, "classes: Wanderer exists");
    CHECK(class_def(CLASS_ROGUE) != NULL, "classes: Rogue exists");
    CHECK(class_def(CLASS_MONK) != NULL, "classes: Monk exists");
    CHECK(class_def(CLASS_PHILOSOPHER) != NULL, "classes: Philosopher exists");
    CHECK(class_def(CLASS_COUNT) == NULL, "classes: out-of-range is NULL");
    CHECK(class_def(255) == NULL, "classes: 255 is NULL");

    /* PC classes (rogue/monk/philosopher) all sum to 66; Wanderer = 60 baseline. */
    CHECK(class_stats_sum(class_def(CLASS_WANDERER)) == 60,
          "classes: Wanderer sums to 60 (baseline 10×6)");
    CHECK(class_stats_sum(class_def(CLASS_ROGUE)) == 66,
          "classes: Rogue sums to 66");
    CHECK(class_stats_sum(class_def(CLASS_MONK)) == 66, "classes: Monk sums to 66");
    CHECK(class_stats_sum(class_def(CLASS_PHILOSOPHER)) == 66,
          "classes: Philosopher sums to 66");

    /* Starting verbs: OBSERVE | MARK | PARLEY | REMEMBER for every class. */
    for(int i = 0; i < CLASS_COUNT; i++) {
        const ClassDef* c = class_def((uint8_t)i);
        CHECK(c->verbs_mask == VERBS_STARTING_MASK,
              "classes: every class has the 4 starting verbs");
    }

    /* Spot-check the role identities — same values as slice 1c, axis labels
     * renamed in slice 48.F1: DEX→CRAFT, STR→BODY, WIS→SIGHT, CON→WILL.
     * Rogue: CRAFT > BODY (was DEX > STR). Philosopher: SIGHT > BODY (was
     * WIS > STR). Monk: WILL ≥ 12 (was CON ≥ 12 — Monk's defensive bent). */
    CHECK(class_def(CLASS_ROGUE)->craft > class_def(CLASS_ROGUE)->body,
          "classes: Rogue has CRAFT > BODY");
    CHECK(class_def(CLASS_PHILOSOPHER)->sight > class_def(CLASS_PHILOSOPHER)->body,
          "classes: Philosopher has SIGHT > BODY");
    CHECK(class_def(CLASS_MONK)->will >= 12, "classes: Monk has solid WILL");
}

/* ─── Pool tests (slice 50.F0) ──────────────────────────────────────
 * The world character Pool is a state-propagating Tier 2 struct that walks
 * with the player. Per spec 50: same (prime_seed, biome, x, y) → byte-equal
 * Pool. Vocabulary is universal; per-save initial bag is hashed from
 * prime_seed so every save's drift trajectory differs. */
static void test_pool_prime_determinism(void) {
    Pool a, b;
    pool_at_prime(0xCAFEBABE, 0, &a);
    pool_at_prime(0xCAFEBABE, 0, &b);
    CHECK(pool_equal(&a, &b), "pool: same prime+biome → byte-equal");

    Pool c;
    pool_at_prime(0xCAFEBABE, 1, &c);
    CHECK(!pool_equal(&a, &c), "pool: cavern prime ≠ outdoor prime");

    Pool d;
    pool_at_prime(0xDEADBEEF, 0, &d);
    CHECK(!pool_equal(&a, &d), "pool: different prime_seed → different Pool");
}

static void test_pool_at_determinism(void) {
    Pool a, b;
    pool_at(0xCAFEBABE, 0,  5,  3, &a);
    pool_at(0xCAFEBABE, 0,  5,  3, &b);
    CHECK(pool_equal(&a, &b), "pool: same (prime, biome, x, y) → byte-equal");

    Pool prime, near, far;
    pool_at(0xCAFEBABE, 0, 0, 0, &prime);
    pool_at(0xCAFEBABE, 0, 1, 0, &near);
    pool_at(0xCAFEBABE, 0, 32, 32, &far);
    CHECK(!pool_equal(&prime, &near), "pool: (0,0) ≠ (1,0) — one step drifts");
    CHECK(!pool_equal(&prime, &far),  "pool: (0,0) ≠ (32,32) — far drift");
    CHECK(!pool_equal(&near, &far),   "pool: near drift ≠ far drift");
}

static void test_pool_intensity_grows(void) {
    Pool prime, mid, far;
    pool_at(0xCAFEBABE, 0,  0,  0, &prime);
    pool_at(0xCAFEBABE, 0,  4,  3, &mid);   /* 7 steps from prime */
    pool_at(0xCAFEBABE, 0, 16, 16, &far);   /* 32 steps from prime */
    CHECK(prime.intensity == 0,
          "pool: intensity at prime is zero");
    CHECK(mid.intensity == 7,
          "pool: intensity = |x| + |y| (X-first-Y canonical walk)");
    CHECK(far.intensity == 32,
          "pool: intensity grows linearly with manhattan distance");
}

static void test_pool_canonical_path(void) {
    /* Walking back to the prime regenerates the prime's Pool exactly. */
    Pool prime, walked, back;
    pool_at(0xCAFEBABE, 0, 0, 0, &prime);
    pool_at(0xCAFEBABE, 0, 7, 5, &walked);
    pool_at(0xCAFEBABE, 0, 0, 0, &back);
    CHECK(pool_equal(&prime, &back),
          "pool: walking back to prime regenerates prime Pool");
    CHECK(!pool_equal(&prime, &walked),
          "pool: walked Pool ≠ prime Pool");
}

static void test_pool_save_uniqueness(void) {
    /* Per the user steer: vocabulary is universal but per-save starting
     * bag is unique. Confirm two different prime_seeds yield different
     * starting bags even at biome and chunk identity equal. */
    Pool a, b;
    pool_at(0xAAAAAAAA, 0, 0, 0, &a);
    pool_at(0xBBBBBBBB, 0, 0, 0, &b);
    int diffs = 0;
    for(int s = 0; s < POOL_BAG_SLOTS; s++) {
        if(a.primitive_bag[s][1] != b.primitive_bag[s][1]) diffs++;
    }
    CHECK(diffs > 0,
          "pool: per-save bag weights differ from a different prime_seed");
    /* But the VOCABULARY (which primitive IDs are in the bag) should be
     * identical across saves — that's the "universal" part. */
    int vocab_match = 1;
    for(int s = 0; s < POOL_BAG_SLOTS; s++) {
        if(a.primitive_bag[s][0] != b.primitive_bag[s][0]) vocab_match = 0;
    }
    CHECK(vocab_match,
          "pool: vocabulary (primitive IDs in bag) is universal across saves");
}

static void test_pool_theme_weights_packed(void) {
    /* 16 themes × 4 bits each = 8 bytes. Read/write round-trips. */
    Pool p;
    memset(&p, 0, sizeof(p));
    for(int t = 0; t < POOL_THEMES; t++) {
        CHECK(pool_theme_weight(&p, t) == 0,
              "pool: zeroed Pool reads zero theme weight");
    }
    /* Out-of-range reads return 0, not crash. */
    CHECK(pool_theme_weight(&p, -1) == 0, "pool: oob low theme reads 0");
    CHECK(pool_theme_weight(&p, 16) == 0, "pool: oob high theme reads 0");
    CHECK(pool_theme_weight(NULL, 0) == 0, "pool: NULL Pool reads 0 safely");
}

/* Regression test for spec 50 addendum §F1.A.1 drain-cascade bug.
 * The shipped lowest-index tiebreaker would converge one slot to 0
 * within ~30 steps. After the F1.A fix (hashed rotor + weight floor
 * + anti-recurrence), the bag should NOT have any zero-weight slot
 * after a long walk, and no slot should drop two steps in a row. */
static void test_pool_bag_no_drain_cascade(void) {
    Pool p;
    pool_at_prime(0xCAFEBABE, 0, &p);

    int zero_seen = 0;
    int recurrence_seen = 0;
    uint8_t prev_drop = 0xFF;

    /* Walk 1000 steps; track invariants. */
    for(int step = 0; step < 1000; step++) {
        uint8_t before_drop = p.last_drop_slot;
        pool_step(&p, 0xCAFEBABE, step & 3);
        uint8_t after_drop = p.last_drop_slot;

        /* A "drop happened" iff last_drop_slot changed value. Track only
         * actual successive drops; a no-drop step keeps prev_drop intact
         * (so the next real drop is still compared against the most
         * recent drop, not an intervening unchanged read). */
        if(after_drop != before_drop && after_drop != 0xFFu) {
            if(prev_drop != 0xFFu && after_drop == prev_drop) {
                recurrence_seen++;
            }
            prev_drop = after_drop;
        }

        /* Floor: no occupied slot's weight should drop below BAG_WEIGHT_FLOOR. */
        for(int s = 0; s < POOL_BAG_SLOTS; s++) {
            if(p.primitive_bag[s][0] == 0xFF) continue;
            if(p.primitive_bag[s][1] < BAG_WEIGHT_FLOOR) zero_seen++;
        }
    }

    CHECK(zero_seen == 0,
          "pool: weight floor holds — no occupied slot drops below BAG_WEIGHT_FLOOR over 1000 steps");
    CHECK(recurrence_seen == 0,
          "pool: anti-recurrence holds — same slot never drops two steps in a row");
}

static void test_pool_bias_queries(void) {
    Pool p;
    pool_at_prime(0xCAFEBABE, 0, &p);
    /* Family + loot biases stay in valid ranges. */
    for(int f = 0; f < POOL_FAMILIES; f++) {
        CHECK(pool_family_bias(&p, (uint8_t)f) <= 15,
              "pool: family bias within bounds");
    }
    for(int k = 0; k < POOL_LOOT_KINDS; k++) {
        CHECK(pool_loot_kind_bias(&p, (uint8_t)k) <= 15,
              "pool: loot bias within bounds");
    }
    /* OOB queries return 0 safely. */
    CHECK(pool_family_bias(&p, 99) == 0, "pool: oob family bias = 0");
    CHECK(pool_loot_kind_bias(&p, 99) == 0, "pool: oob loot bias = 0");
}

/* ─── Pool-consumer tests (slice 50.F2/F3/F4) ──────────────────────── */
static void test_pool_consumers_no_bias_matches_legacy(void) {
    /* NULL pool through the _pooled variants must produce byte-equal
     * behavior to the legacy functions. The compatibility contract. */
    Rng a, b;
    rng_seed(&a, 12345);
    rng_seed(&b, 12345);
    int same_loot = 1;
    for(int i = 0; i < 100; i++) {
        if(loot_roll(&a, BIOME_CAVERN) !=
           loot_roll_pooled(&b, BIOME_CAVERN, NULL)) {
            same_loot = 0;
            break;
        }
    }
    CHECK(same_loot, "F3: loot_roll_pooled(NULL) ≡ loot_roll");

    rng_seed(&a, 54321);
    rng_seed(&b, 54321);
    int same_fam = 1;
    for(int i = 0; i < 100; i++) {
        if(creature_family_roll(&a, BIOME_OUTDOOR) !=
           creature_family_roll_pooled(&b, BIOME_OUTDOOR, NULL)) {
            same_fam = 0;
            break;
        }
    }
    CHECK(same_fam, "F2: creature_family_roll_pooled(NULL) ≡ creature_family_roll");
}

static void test_pool_consumers_bias_shifts_distribution(void) {
    /* With Pool bias, the roll distribution must shift toward biased
     * slots. Sanity check: a pool with all family_bias = 0 except slot 0
     * (heavily upweighted) makes family 0 dominate among eligible picks. */
    Pool p;
    pool_at_prime(0xCAFEBABE, 0, &p);
    /* Crank family 0 to max bias to make it dominate. */
    p.family_bias[0] = 56;
    for(int s = 1; s < POOL_FAMILIES; s++) p.family_bias[s] = 0;

    Rng r;
    rng_seed(&r, 42);
    int fam0_count = 0;
    int total = 500;
    for(int i = 0; i < total; i++) {
        uint8_t f = creature_family_roll_pooled(&r, BIOME_CAVERN, &p);
        if(f == 0) fam0_count++;
    }
    /* Without bias, fam 0's share would be its base weight fraction.
     * With max bias, its share should be substantially elevated. */
    CHECK(fam0_count > total / 3,
          "F2: Pool family_bias shifts distribution toward biased slot");
}

/* ─── Weather tests (atmosphere slice) ──────────────────────────────── */
static void test_weather_determinism(void) {
    Weather a, b;
    weather_at(0xCAFEBABE, 3, -2, 19500, 1, &a);
    weather_at(0xCAFEBABE, 3, -2, 19500, 1, &b);
    CHECK(a.kind == b.kind, "weather: kind deterministic");
    CHECK(a.intensity == b.intensity, "weather: intensity deterministic");
    CHECK(a.pedigree == b.pedigree, "weather: pedigree deterministic");

    /* Different day → different weather pattern (very likely; not strictly
     * guaranteed by hash collision math but should hold for these inputs). */
    Weather c;
    weather_at(0xCAFEBABE, 3, -2, 19501, 1, &c);
    /* Either kind or intensity should differ — but we only need ONE to differ
     * for the test to assert "day advances change the weather." */
    CHECK(a.kind != c.kind || a.intensity != c.intensity,
          "weather: day advance changes pattern");
}

static void test_weather_indoor_attenuation(void) {
    Weather outdoor, indoor;
    weather_at(0xCAFEBABE, 0, 0, 19500, 1, &outdoor); /* outdoor */
    weather_at(0xCAFEBABE, 0, 0, 19500, 0, &indoor);  /* cavern */
    CHECK(indoor.indoor_attenuated == 1,
          "weather: cavern flagged as indoor_attenuated");
    CHECK(outdoor.indoor_attenuated == 0,
          "weather: outdoor flagged not attenuated");
    /* Indoor intensity should be HALF of outdoor for the same (seed, xy, day). */
    CHECK(indoor.intensity == (uint8_t)(outdoor.intensity / 2u),
          "weather: indoor intensity halves outdoor");
}

static void test_weather_fov_cap(void) {
    Weather clear = { .kind = WEATHER_CLEAR, .fov_cap_delta = 0 };
    Weather storm = { .kind = WEATHER_STORM, .fov_cap_delta = 3 };
    CHECK(weather_apply_fov(&clear, 5) == 5,
          "weather: clear leaves FOV untouched");
    CHECK(weather_apply_fov(&storm, 5) == 2,
          "weather: storm caps FOV by delta");
    CHECK(weather_apply_fov(&storm, 1) == 1,
          "weather: FOV never drops below 1");
}

static void test_weather_biome_temperature(void) {
    /* Cavern is cool, outdoor temperate, future arid hot. The mapping is
     * the contract — biome IDs must align with stamps.h's STAMP_BIOME_*. */
    CHECK(biome_temperature(0) == BIOME_TEMP_COOL,
          "weather: cavern (id 0) maps to COOL");
    CHECK(biome_temperature(1) == BIOME_TEMP_TEMPERATE,
          "weather: outdoor (id 1) maps to TEMPERATE");
    CHECK(biome_temperature(2) == BIOME_TEMP_HOT,
          "weather: arid (id 2; reserved) maps to HOT");
    CHECK(biome_temperature(99) == BIOME_TEMP_TEMPERATE,
          "weather: unknown biome defaults to TEMPERATE");
}

static void test_weather_hot_biome_distribution(void) {
    /* Hot biomes get HEAT/DUST_STORM far more than other kinds. Sample
     * 500 chunks under hot biome; HEAT+DUST_STORM should dominate. */
    int hot_count = 0;
    int total = 500;
    for(int day = 19500; day < 19500 + total; day++) {
        Weather w;
        weather_at(0xCAFEBABE, day, 0, (uint32_t)day, 2, &w); /* biome=2 = HOT */
        if(w.kind == WEATHER_HEAT || w.kind == WEATHER_DUST_STORM) hot_count++;
    }
    /* Hot biome distribution: HEAT 35% + DUST_STORM 15% = 50% baseline.
     * Sampling noise should keep this above 30%. */
    CHECK(hot_count > total * 30 / 100,
          "weather: hot biome produces majority heat/dust over time");
}

static void test_weather_overlay_density(void) {
    /* Storm overlay density > rain overlay density; both biome-attenuated. */
    Weather rain  = { .kind = WEATHER_RAIN,  .indoor_attenuated = 0, .pedigree = 0xDEADBEEF };
    Weather storm = { .kind = WEATHER_STORM, .indoor_attenuated = 0, .pedigree = 0xDEADBEEF };
    Weather clear = { .kind = WEATHER_CLEAR, .indoor_attenuated = 0, .pedigree = 0xDEADBEEF };

    int rain_hits = 0, storm_hits = 0, clear_hits = 0;
    for(int y = 0; y < 16; y++) {
        for(int x = 0; x < 16; x++) {
            if(weather_tile_has_overlay(&rain,  100, x, y)) rain_hits++;
            if(weather_tile_has_overlay(&storm, 100, x, y)) storm_hits++;
            if(weather_tile_has_overlay(&clear, 100, x, y)) clear_hits++;
        }
    }
    CHECK(clear_hits == 0, "weather: clear has no overlay");
    CHECK(rain_hits > 0, "weather: rain produces overlay cells");
    CHECK(storm_hits > rain_hits, "weather: storm denser than rain");
}

static void test_recipes(void) {
    CHECK(RECIPE_COUNT > 0, "recipes: catalog has entries");
    /* every recipe sums to 100 + has a valid name */
    for(int i = 0; i < RECIPE_COUNT; i++) {
        const RecipeDef* r = recipe_def((uint8_t)i);
        CHECK(r != NULL, "recipes: each id valid");
        uint32_t total = (uint32_t)r->weight_floor + r->weight_hit + r->weight_jackpot;
        CHECK(total == 100, "recipes: weights sum to 100");
        CHECK(r->name && r->name[0] != '\0', "recipes: name non-empty");
    }
    CHECK(recipe_def(RECIPE_COUNT) == NULL, "recipes: out-of-range = NULL");

    /* craftable: Crystal Brew needs 2 crystal */
    const RecipeDef* cb = recipe_def(0);
    uint8_t inv0[8] = {0, 0, 0, 0, 0, 0, 0, 0};
    uint8_t inv1[8] = {1, 0, 0, 0, 0, 0, 0, 0};
    uint8_t inv2[8] = {2, 0, 0, 0, 0, 0, 0, 0};
    CHECK(!recipe_craftable(cb, inv0, 8), "craftable: 0 crystal → no");
    CHECK(!recipe_craftable(cb, inv1, 8), "craftable: 1 crystal → no");
    CHECK(recipe_craftable(cb, inv2, 8), "craftable: 2 crystal → yes");

    /* craftable: Honed Edge needs 1 crystal + 1 clay pot */
    const RecipeDef* he = recipe_def(2);
    uint8_t inv_cr[8] = {1, 0, 0, 0, 0, 0, 0, 0};
    uint8_t inv_cl[8] = {0, 0, 1, 0, 0, 0, 0, 0};
    uint8_t inv_both[8] = {1, 0, 1, 0, 0, 0, 0, 0};
    CHECK(!recipe_craftable(he, inv_cr, 8), "craftable: missing clay → no");
    CHECK(!recipe_craftable(he, inv_cl, 8), "craftable: missing crystal → no");
    CHECK(recipe_craftable(he, inv_both, 8), "craftable: both inputs → yes");

    /* pull determinism: same seed → same tier sequence */
    Rng a, b;
    rng_seed(&a, 0xCAFE);
    rng_seed(&b, 0xCAFE);
    int same = 1;
    for(int i = 0; i < 50; i++) {
        if(recipe_pull(&a, cb) != recipe_pull(&b, cb)) same = 0;
    }
    CHECK(same, "pull: same seed → same tier");

    /* pull distribution: Crystal Brew is 40/55/5 — verify FLOOR most, JACKPOT least */
    Rng dist;
    rng_seed(&dist, 0xBEEF);
    int floor_n = 0, hit_n = 0, jack_n = 0;
    for(int i = 0; i < 1000; i++) {
        switch(recipe_pull(&dist, cb)) {
        case PULL_FLOOR:   floor_n++; break;
        case PULL_HIT:     hit_n++; break;
        case PULL_JACKPOT: jack_n++; break;
        }
    }
    CHECK(hit_n > floor_n, "pull: HIT more common than FLOOR (55 vs 40)");
    CHECK(floor_n > jack_n, "pull: FLOOR more common than JACKPOT (40 vs 5)");
    CHECK(jack_n > 10 && jack_n < 120, "pull: JACKPOT in expected range");
}

/* ─── Corner-snap stamp composer (spec 50 §R) ──────────────────────────────
 * These test the new PLACEMENT strategy in isolation — calling the composer
 * directly on a hand-built chunk shell, before world.c's scatter_items /
 * find_spawn / carve_egress passes run. They pin the invariants the §R
 * algorithm guarantees: deterministic, interior-only, prime-safe,
 * non-floor-preserving, and the corner math pair. */

/* Pre-compose CAVERN shell: walled border + 4 mid-edge doors, floor interior
 * (mirrors gen_cavern_stamped's state at the compose call). */
static void build_cavern_shell(World* w) {
    for(int y = 0; y < WORLD_ROWS; y++) {
        for(int x = 0; x < WORLD_COLS; x++) {
            bool border = (y == 0 || y == WORLD_ROWS - 1 ||
                           x == 0 || x == WORLD_COLS - 1);
            w->tiles[y][x] = border ? TILE_WALL : TILE_FLOOR;
        }
    }
    int mc = WORLD_COLS / 2, mr = WORLD_ROWS / 2;
    w->tiles[0][mc] = TILE_DOOR;
    w->tiles[WORLD_ROWS - 1][mc] = TILE_DOOR;
    w->tiles[mr][0] = TILE_DOOR;
    w->tiles[mr][WORLD_COLS - 1] = TILE_DOOR;
}

static int interior_nonfloor_count(const World* w) {
    int n = 0;
    for(int y = 1; y < WORLD_ROWS - 1; y++) {
        for(int x = 1; x < WORLD_COLS - 1; x++) {
            if(w->tiles[y][x] != TILE_FLOOR) n++;
        }
    }
    return n;
}

/* The determinism keystone for door=door coherence (spec 50 §R world-
 * coherence): both chunks sharing an edge must derive the SAME door position
 * with no persistence and no entry-direction dependence. */
static void test_edge_door_agreement(void) {
    uint32_t seed = 0xC0FFEE11u;
    bool ew_ok = true, ns_ok = true, range_ok = true;
    for(int cy = -3; cy <= 3; cy++) {
        for(int cx = -3; cx <= 3; cx++) {
            int e = world_edge_door_perp(seed, cx, cy, MoveEast);
            int w = world_edge_door_perp(seed, cx + 1, cy, MoveWest);
            if(e != w) ew_ok = false;
            int s = world_edge_door_perp(seed, cx, cy, MoveSouth);
            int n = world_edge_door_perp(seed, cx, cy + 1, MoveNorth);
            if(s != n) ns_ok = false;
            /* E/W doors are rows; N/S doors are columns. Both stay off corners. */
            if(e < 1 || e > WORLD_ROWS - 2) range_ok = false;
            if(s < 1 || s > WORLD_COLS - 2) range_ok = false;
        }
    }
    CHECK(ew_ok, "edge door: east door row == east-neighbor's west door row (door=door)");
    CHECK(ns_ok, "edge door: south door col == south-neighbor's north door col (door=door)");
    CHECK(range_ok, "edge door: positions stay off the corners (in range)");
}

/* Slice 2: every generated chunk's four edges cohere with their neighbors —
 * open↔open seams stay open, any edge touching a walled chunk becomes
 * wall+door on BOTH sides at the agreed hashed position. This is the
 * end-to-end "no phasing through walls" guarantee in the generated tiles. */
static void test_edge_walls_match_neighbors(void) {
    uint32_t seeds[] = {0x5EED5EEDu, 0xCAFEBABEu, 0x12345678u};
    int n_seeds = (int)(sizeof(seeds) / sizeof(seeds[0]));
    bool all_coherent = true;
    int open_edges = 0, walled_edges = 0;
    for(int s = 0; s < n_seeds; s++) {
        for(int cy = -3; cy <= 3; cy++) {
            for(int cx = -3; cx <= 3; cx++) {
                World w;
                world_generate_chunk(seeds[s], cx, cy, &w);
                const MoveDir dirs[4] = {MoveNorth, MoveSouth, MoveWest, MoveEast};
                for(int d = 0; d < 4; d++) {
                    if(!edge_is_coherent(&w, seeds[s], cx, cy, dirs[d])) {
                        all_coherent = false;
                    }
                    bool walled = (world_terrain(&w) == TERRAIN_WALLED) ||
                                  nbr_walled(seeds[s], cx, cy, dirs[d]);
                    if(walled) walled_edges++; else open_edges++;
                }
            }
        }
    }
    CHECK(all_coherent,
          "edges: every chunk edge coheres with its neighbor (no phase-through)");
    CHECK(open_edges > 0 && walled_edges > 0,
          "edges: sample exercised both open and walled seams");
}

/* Slice 3: with walls as real tiles, the move layer already enforces
 * door=door / wall=wall. On an open chunk's walled edge, walking at the wall
 * is blocked (no phase-through) and only the door tile transitions. No new
 * move-time code — this just pins the emergent behavior. */
static void test_transition_walls_block_open_chunk(void) {
    uint32_t seed = 0xCAFEBABEu;
    const MoveDir dirs[4] = {MoveNorth, MoveSouth, MoveWest, MoveEast};
    int fcx = 0, fcy = 0;
    MoveDir fdir = MoveNorth;
    bool found = false;
    for(int cy = -5; cy <= 5 && !found; cy++) {
        for(int cx = -5; cx <= 5 && !found; cx++) {
            if(biome_terrain(biome_of(seed, cx, cy)) != TERRAIN_OPEN) continue;
            for(int d = 0; d < 4; d++) {
                if(nbr_walled(seed, cx, cy, dirs[d])) {
                    found = true; fcx = cx; fcy = cy; fdir = dirs[d]; break;
                }
            }
        }
    }
    CHECK(found, "transition: found an open chunk with a walled edge");
    if(!found) return;

    World w;
    world_generate_chunk(seed, fcx, fcy, &w);
    int door = world_edge_door_perp(seed, fcx, fcy, fdir);
    int wall_perp = (door == 1) ? 2 : 1; /* a non-door span position */

    int wpx, wpy, dpx, dpy;
    switch(fdir) {
    case MoveNorth: wpx = wall_perp; wpy = 1;              dpx = door; dpy = 1;              break;
    case MoveSouth: wpx = wall_perp; wpy = WORLD_ROWS - 2; dpx = door; dpy = WORLD_ROWS - 2; break;
    case MoveWest:  wpx = 1;              wpy = wall_perp; dpx = 1;              dpy = door; break;
    case MoveEast:  wpx = WORLD_COLS - 2; wpy = wall_perp; dpx = WORLD_COLS - 2; dpy = door; break;
    default:        wpx = wpy = dpx = dpy = 1; break;
    }

    char dd;
    int px = wpx, py = wpy;
    CHECK(world_try_move(&w, fdir, &px, &py, &dd) == MoveBlockedByWall,
          "transition: walking at the wall on a walled edge is blocked (no phase-through)");
    px = dpx; py = dpy;
    CHECK(world_try_move(&w, fdir, &px, &py, &dd) == MoveSteppedOnDoor,
          "transition: walking at the door on a walled edge steps onto the door");
}

/* Slice 4: secret passages. Geometry is deterministic + both neighbors agree
 * (the crossing/unlock check lives in sanctum_rpg.c and is verified on device).
 * Here: position + gating-quest agreement, and that a secret reads/stays as a
 * sealed wall that the move layer reports distinctly. */
static void test_secret_edge_agreement(void) {
    uint32_t seed = 0xBEEF1234u;
    bool ew_ok = true, ns_ok = true, q_ok = true;
    int secrets = 0;
    for(int cy = -4; cy <= 4; cy++) {
        for(int cx = -4; cx <= 4; cx++) {
            int e = world_edge_secret_perp(seed, cx, cy, MoveEast);
            int w = world_edge_secret_perp(seed, cx + 1, cy, MoveWest);
            if(e != w) ew_ok = false;
            if(e >= 0) secrets++;
            int s = world_edge_secret_perp(seed, cx, cy, MoveSouth);
            int n = world_edge_secret_perp(seed, cx, cy + 1, MoveNorth);
            if(s != n) ns_ok = false;
            if(world_edge_secret_axis(seed, cx, cy, MoveEast, 6) !=
               world_edge_secret_axis(seed, cx + 1, cy, MoveWest, 6)) q_ok = false;
        }
    }
    CHECK(ew_ok, "secret: east/west neighbors agree on secret presence + position");
    CHECK(ns_ok, "secret: north/south neighbors agree on secret presence + position");
    CHECK(q_ok, "secret: neighbors agree on the gating growth axis");
    CHECK(secrets > 0, "secret: rarity gate yields some secrets in the sample");
}

static void test_secret_sealed_blocks(void) {
    uint32_t seed = 0xBEEF1234u;
    World w;
    bool found = false;
    int sx = -1, sy = -1;
    MoveDir into = MoveNorth;
    for(int cy = -6; cy <= 6 && !found; cy++) {
        for(int cx = -6; cx <= 6 && !found; cx++) {
            world_generate_chunk(seed, cx, cy, &w);
            for(int x = 1; x < WORLD_COLS - 1 && !found; x++) {
                if(w.tiles[0][x] == TILE_SECRET) { found = true; sx = x; sy = 0; into = MoveNorth; }
                else if(w.tiles[WORLD_ROWS - 1][x] == TILE_SECRET) { found = true; sx = x; sy = WORLD_ROWS - 1; into = MoveSouth; }
            }
            for(int y = 1; y < WORLD_ROWS - 1 && !found; y++) {
                if(w.tiles[y][0] == TILE_SECRET) { found = true; sx = 0; sy = y; into = MoveWest; }
                else if(w.tiles[y][WORLD_COLS - 1] == TILE_SECRET) { found = true; sx = WORLD_COLS - 1; sy = y; into = MoveEast; }
            }
        }
    }
    CHECK(found, "secret: at least one secret tile generated in the sample");
    if(!found) return;
    CHECK(world_is_blocking(TILE_SECRET), "secret: reads as a wall (blocking)");
    CHECK(!world_walkable(&w, sx, sy), "secret: tile is sealed (not walkable)");
    CHECK(w.tiles[sy][sx] == TILE_SECRET, "secret: carve_egress left it sealed");

    int ax = sx, ay = sy;
    switch(into) {
    case MoveNorth: ay = 1;              break;
    case MoveSouth: ay = WORLD_ROWS - 2; break;
    case MoveWest:  ax = 1;              break;
    case MoveEast:  ax = WORLD_COLS - 2; break;
    default: break;
    }
    char dd;
    int px = ax, py = ay;
    CHECK(world_try_move(&w, into, &px, &py, &dd) == MoveBlockedBySecret,
          "secret: walking at it reports MoveBlockedBySecret (not a plain wall)");
}

static void test_compose_corner_roundtrip(void) {
    CHECK(compose_selftest_corner_roundtrip(),
          "compose: box_corner / place_for_anchor are exact inverses (coord pair)");
}

static void test_compose_determinism(void) {
    Pool pc;
    pool_at_prime(0xCAFEBABE, STAMP_BIOME_CAVERN, &pc);
    World a, b;
    Rng r;
    build_cavern_shell(&a);
    build_cavern_shell(&b);
    rng_seed(&r, 0x1234u);
    compose_stamps_into_interior(&r, &pc, STAMP_BIOME_CAVERN, &a);
    rng_seed(&r, 0x1234u);
    compose_stamps_into_interior(&r, &pc, STAMP_BIOME_CAVERN, &b);
    CHECK(memcmp(a.tiles, b.tiles, sizeof(a.tiles)) == 0,
          "compose: same rng+pool → byte-equal placement (deterministic)");

    /* A different rng stream should (almost always) diverge. */
    World c;
    build_cavern_shell(&c);
    rng_seed(&r, 0x9999u);
    compose_stamps_into_interior(&r, &pc, STAMP_BIOME_CAVERN, &c);
    CHECK(memcmp(a.tiles, c.tiles, sizeof(a.tiles)) != 0,
          "compose: a different rng stream produces a different chunk");
}

static void test_compose_interior_only(void) {
    Pool p;
    pool_at_prime(0xBEEFu, STAMP_BIOME_CAVERN, &p);
    World w;
    Rng r;
    build_cavern_shell(&w);
    rng_seed(&r, 0x777u);
    compose_stamps_into_interior(&r, &p, STAMP_BIOME_CAVERN, &w);

    /* The biome owns the edge — the composer must never write a stamp glyph
     * onto the border. Every border tile stays wall or door. */
    bool border_ok = true;
    for(int x = 0; x < WORLD_COLS; x++) {
        char top = w.tiles[0][x], bot = w.tiles[WORLD_ROWS - 1][x];
        if(top != TILE_WALL && top != TILE_DOOR) border_ok = false;
        if(bot != TILE_WALL && bot != TILE_DOOR) border_ok = false;
    }
    for(int y = 0; y < WORLD_ROWS; y++) {
        char lft = w.tiles[y][0], rgt = w.tiles[y][WORLD_COLS - 1];
        if(lft != TILE_WALL && lft != TILE_DOOR) border_ok = false;
        if(rgt != TILE_WALL && rgt != TILE_DOOR) border_ok = false;
    }
    CHECK(border_ok, "compose: never writes a stamp glyph onto the chunk border");

    /* The central prime is the spawn safe-area — reserved in occupancy, never
     * buried. Its center tile stays floor. */
    CHECK(w.tiles[WORLD_ROWS / 2][WORLD_COLS / 2] == TILE_FLOOR,
          "compose: central prime stays floor (spawn safe-area reserved)");

    /* The 4 mid-edge doors survive (the composer respects them). */
    int mc = WORLD_COLS / 2, mr = WORLD_ROWS / 2;
    CHECK(w.tiles[0][mc] == TILE_DOOR && w.tiles[WORLD_ROWS - 1][mc] == TILE_DOOR &&
          w.tiles[mr][0] == TILE_DOOR && w.tiles[mr][WORLD_COLS - 1] == TILE_DOOR,
          "compose: the 4 mid-edge doors are preserved");
}

static void test_compose_places_something(void) {
    /* Across a handful of seeds the composer should put down at least one
     * stamp (it is not a no-op). Pool intensity 0 still has common stamps. */
    Pool p;
    pool_at_prime(0xABCDu, STAMP_BIOME_CAVERN, &p);
    int total = 0;
    for(uint32_t s = 1; s <= 5; s++) {
        World w;
        Rng r;
        build_cavern_shell(&w);
        rng_seed(&r, s * 2654435761u);
        compose_stamps_into_interior(&r, &p, STAMP_BIOME_CAVERN, &w);
        total += interior_nonfloor_count(&w);
    }
    CHECK(total > 0, "compose: places at least one stamp across seeds (not a no-op)");
}

static void test_compose_preserves_nonfloor(void) {
    /* A non-floor tile placed before compose (e.g. a vendor) is seeded into
     * the occupancy mask and is never overwritten. */
    Pool p;
    pool_at_prime(0xFEEDu, STAMP_BIOME_CAVERN, &p);
    World w;
    Rng r;
    build_cavern_shell(&w);
    w.tiles[2][4] = TILE_VENDOR;
    rng_seed(&r, 0x4242u);
    compose_stamps_into_interior(&r, &p, STAMP_BIOME_CAVERN, &w);
    CHECK(w.tiles[2][4] == TILE_VENDOR,
          "compose: never overwrites a pre-placed non-floor tile (vendor)");
}

/* ── region tree (spec 58 §58.3) ─────────────────────────────────── */
static void test_region_tree(void) {
    static const uint32_t SEEDS[] = {0x12345678u, 0xCAFEBABEu, 0xDEADBEEFu, 1u};
    int bad_step = 0, bad_root = 0, bad_card = 0;
    for(unsigned k = 0; k < sizeof(SEEDS) / sizeof(SEEDS[0]); k++)
        for(int ry = -8; ry <= 8; ry++)
            for(int rx = -8; rx <= 8; rx++) {
                uint32_t seed = SEEDS[k];
                int d = region_depth(seed, rx, ry);
                if(d == 0) continue;
                int ix, iy;
                region_inward(seed, rx, ry, &ix, &iy);
                if(abs(ix - rx) + abs(iy - ry) != 1) bad_card++;          /* one cardinal step */
                if(region_depth(seed, ix, iy) != d - 1) bad_step++;       /* one step closer */
                int x = rx, y = ry, guard = 0;                            /* inward reaches the root */
                while(region_depth(seed, x, y) > 0 && guard++ < 64) region_inward(seed, x, y, &x, &y);
                if(region_depth(seed, x, y) != 0) bad_root++;
            }
    CHECK(bad_card == 0, "region: the way inward is one cardinal step");
    CHECK(bad_step == 0, "region: the way inward is one ring closer to the origin");
    CHECK(bad_root == 0, "region: following inward always reaches the origin");
    int ox, oy;
    region_origin(0x12345678u, &ox, &oy);
    CHECK(ox == region_of(0) && oy == region_of(0), "region: the origin holds the waking chunk");
    int ix, iy;
    region_inward(0x12345678u, 3, 0, &ix, &iy);
    CHECK(ix == 2 && iy == 0, "region: on an axis, inward is straight toward the origin");

    /* A diagonal region's inward choice varies (the hash picks an axis). */
    int via_x = 0, via_y = 0;
    for(int ry = 1; ry <= 8; ry++)
        for(int rx = 1; rx <= 8; rx++) {
            region_inward(0xCAFEBABEu, rx, ry, &ix, &iy);
            if(ix != rx) via_x++; else via_y++;
        }
    CHECK(via_x > 8 && via_y > 8, "region: diagonal regions turn inward both ways");
}

static void test_region_gates(void) {
    uint32_t seed = 0x12345678u;
    RegionRituals r;
    region_rituals_clear(&r);
    CHECK(region_open(seed, &r, 0, 0), "region gate: the origin is open");
    CHECK(!region_open(seed, &r, 1, 0) && !region_open(seed, &r, 0, -1),
          "region gate: ring 1 is closed until the origin's ritual");
    CHECK(!region_edge_closed(seed, &r, 0, 0, MoveEast) && !region_edge_closed(seed, &r, 1, 1, MoveSouth),
          "region gate: crossings inside a region are never closed");
    CHECK(region_edge_closed(seed, &r, 2, 0, MoveEast) && region_edge_closed(seed, &r, 0, 0, MoveWest),
          "region gate: crossing into a closed region is refused");
    region_mark_ritual(&r, 0, 0);
    int opened = 0;
    for(int ry = -1; ry <= 1; ry++)
        for(int rx = -1; rx <= 1; rx++)
            if(region_depth(seed, rx, ry) == 1) opened += region_open(seed, &r, rx, ry);
    CHECK(opened == 4, "region gate: the origin's ritual opens all of ring 1");
    int ring2_open = 0, ring2 = 0;
    for(int ry = -2; ry <= 2; ry++)
        for(int rx = -2; rx <= 2; rx++)
            if(region_depth(seed, rx, ry) == 2) ring2++, ring2_open += region_open(seed, &r, rx, ry);
    CHECK(ring2 == 8 && ring2_open == 0, "region gate: ring 2 stays closed");
    /* Going back inward is never refused: every open region's inward is open. */
    region_mark_ritual(&r, 1, 0);
    int back_closed = 0;
    for(int ry = -3; ry <= 3; ry++)
        for(int rx = -3; rx <= 3; rx++) {
            if(!region_open(seed, &r, rx, ry) || region_depth(seed, rx, ry) == 0) continue;
            int ix, iy;
            region_inward(seed, rx, ry, &ix, &iy);
            if(!region_open(seed, &r, ix, iy)) back_closed++;
        }
    CHECK(back_closed == 0, "region gate: the way back toward the origin is always open");

    /* Save round trip; tolerant of junk. */
    char buf[REGION_DONE_TEXT_MAX];
    region_rituals_format(&r, buf, sizeof(buf));
    RegionRituals q;
    region_rituals_parse(buf, &q);
    CHECK(q.count == 2 && region_ritual_done(&q, 0, 0) && region_ritual_done(&q, 1, 0),
          "region save: rituals survive a round trip");
    region_rituals_parse("v9\n0 0\n", &q);
    CHECK(q.count == 0, "region save: an unknown version loads as none");
    region_rituals_parse("v1\n0 0\nnonsense\n-2 3\n0 0\n", &q);
    CHECK(q.count == 2 && region_ritual_done(&q, -2, 3), "region save: bad lines skipped, repeats merged");
    RegionRituals full;
    region_rituals_clear(&full);
    int ok = 1;
    for(int i = 0; i < REGION_DONE_MAX; i++) ok &= region_mark_ritual(&full, i, 100);
    CHECK(ok && !region_mark_ritual(&full, -1, -1), "region save: the set refuses past REGION_DONE_MAX");
    /* A save from before the gates, standing deep in a closed region:
     * every crossing is allowed until it's back inside the tree. From an
     * open region, the border still refuses. */
    {
        RegionRituals none;
        region_rituals_clear(&none);
        uint32_t seed = 0x12345678u;
        int deep_cx = 3 * BIOME_REGION + 1, deep_cy = 1;   /* region (3, 0): depth 3 */
        int stuck = 0;
        MoveDir dirs[4] = {MoveNorth, MoveSouth, MoveWest, MoveEast};
        for(int d = 0; d < 4; d++) stuck += region_edge_closed(seed, &none, deep_cx, deep_cy, dirs[d]);
        CHECK(!region_open(seed, &none, 3, 0) && stuck == 0,
              "gates: a player stranded in a closed region may walk anywhere (old saves)");
        CHECK(region_edge_closed(seed, &none, BIOME_REGION - 1, 0, MoveEast),
              "gates: from the open waking region, the border still refuses");
    }
}

/* ── quirks: the cave-in (spec 50 Q1 §Q.1.1) ─────────────────────── */

/* Find a mine chunk with a timber prop that has open floor beside it. */
static bool find_timber(uint32_t seed, World* w, int* cx, int* cy, int* tx, int* ty) {
    for(int y0 = -10; y0 <= 10; y0++)
        for(int x0 = -10; x0 <= 10; x0++) {
            if(style_of(seed, x0, y0) != STYLE_MINE) continue;
            world_generate_chunk(seed, x0, y0, w);
            for(int y = 1; y < WORLD_ROWS - 1; y++)
                for(int x = 1; x < WORLD_COLS - 1; x++)
                    if(w->tiles[y][x] == 'l') { *cx = x0; *cy = y0; *tx = x; *ty = y; return true; }
        }
    return false;
}

static void test_quirk_cave_in(void) {
    /* The roll: about 1 in 64, and a pure function of its inputs. */
    int fired = 0, n = 0;
    for(uint32_t turn = 0; turn < 20000; turn++) {
        QuirkPending p = {0};
        fired += quirk_fire(0x12345678u, 1, -5, turn, QUIRK_CAVE_IN, 5, 3, QUIRK_BY_CHANCE, &p);
        n++;
    }
    CHECK(fired > n / 64 * 7 / 10 && fired < n / 64 * 13 / 10, "cave-in: fires on about 1 in 64 steps");
    QuirkPending a = {0}, b = {0};
    bool fa = false, fb = false;
    for(uint32_t t = 0; t < 500 && !fa; t++) {
        fa = quirk_fire(0xCAFEBABEu, 3, 3, t, QUIRK_CAVE_IN, 4, 2, QUIRK_BY_CHANCE, &a);
        fb = quirk_fire(0xCAFEBABEu, 3, 3, t, QUIRK_CAVE_IN, 4, 2, QUIRK_BY_CHANCE, &b);
    }
    CHECK(fa && fb && a.due_turn == b.due_turn, "cave-in: the same inputs replay the same roll");

    /* The trigger path skips the roll but keeps one pending at a time. */
    QuirkPending p = {0};
    CHECK(quirk_fire(1, 0, 0, 7, QUIRK_CAVE_IN, 3, 3, QUIRK_BY_TRIGGER, &p) && p.due_turn == 8,
          "cave-in: a trigger arms it without a roll, due next turn");
    CHECK(!quirk_fire(1, 0, 0, 7, QUIRK_CAVE_IN, 4, 4, QUIRK_BY_TRIGGER, &p), "cave-in: only one pending at a time");

    /* Tell, then land a turn later; never on the player; never cuts a door off. */
    World w;
    int cx, cy, tx, ty;
    bool have = find_timber(0x12345678u, &w, &cx, &cy, &tx, &ty);
    CHECK(have, "cave-in: a generated mine has a timber prop");
    int on_player = 0, sealed = 0, placed = 0, hits = 0, misses = 0, early = 0, scenes = 0;
    static const uint32_t SEEDS[] = {0x12345678u, 0xCAFEBABEu, 0xDEADBEEFu, 1u, 0x0BADF00Du};
    for(unsigned k = 0; k < sizeof(SEEDS) / sizeof(SEEDS[0]); k++) {
        if(!find_timber(SEEDS[k], &w, &cx, &cy, &tx, &ty)) continue;
        for(int dy = -1; dy <= 1; dy++)
            for(int dx = -1; dx <= 1; dx++) {
                int px = tx + dx, py = ty + dy;
                if((dx == 0 && dy == 0) || !world_walkable(&w, px, py)) continue;
                for(int stay = 0; stay < 2; stay++) {
                    World t = w;
                    QuirkPending q = {0};
                    QuirkOutcome o;
                    quirk_fire(SEEDS[k], cx, cy, 100, QUIRK_CAVE_IN, tx, ty, QUIRK_BY_TRIGGER, &q);
                    quirk_step(SEEDS[k], cx, cy, 100, &t, px, py, &q, &o);
                    if(o.landed) early++;                         /* same turn: must not land yet */
                    int ex = px, ey = py;
                    if(!stay) {                                   /* step away from the timber */
                        for(int ay = -1; ay <= 1 && ex == px && ey == py; ay++)
                            for(int ax = -1; ax <= 1; ax++) {
                                int nx = px + ax, ny = py + ay;
                                int fdx = nx - tx, fdy = ny - ty;
                                if(world_walkable(&t, nx, ny) && (fdx * fdx > 1 || fdy * fdy > 1)) { ex = nx; ey = ny; break; }
                            }
                        if(ex == px && ey == py) continue;        /* nowhere to step away to */
                    }
                    quirk_step(SEEDS[k], cx, cy, 101, &t, ex, ey, &q, &o);
                    scenes++;
                    if(!o.landed || q.active) early++;
                    if(o.placed) {
                        placed++;
                        if(o.rx == ex && o.ry == ey) on_player++;
                        if(t.tiles[o.ry][o.rx] != CAVE_IN_RUBBLE) on_player++;
                    }
                    if(!world_doors_reachable_from(&t, ex, ey)) sealed++;
                    if(o.damage) hits++; else misses++;
                    if(stay && !o.damage) early++;
                }
            }
    }
    CHECK(scenes > 10 && early == 0, "cave-in: the tell comes one turn before it lands");
    CHECK(placed > 0 && on_player == 0, "cave-in: rubble lands next to the timber, never on the player");
    CHECK(sealed == 0, "cave-in: rubble never cuts the player off from a door");
    CHECK(hits > 0 && misses > 0, "cave-in: staying by the timber hurts, stepping away doesn't");

    /* By chance: a step next to a timber eventually tells. */
    if(have && find_timber(0x12345678u, &w, &cx, &cy, &tx, &ty)) {
        World t = w;
        int px = -1, py = -1;
        for(int dy = -1; dy <= 1 && px < 0; dy++)
            for(int dx = -1; dx <= 1; dx++)
                if((dx || dy) && world_walkable(&t, tx + dx, ty + dy)) { px = tx + dx; py = ty + dy; break; }
        QuirkPending q = {0};
        QuirkOutcome o;
        int told = 0;
        for(uint32_t turn = 0; turn < 2000 && !told; turn++) {
            quirk_step(0x12345678u, cx, cy, turn, &t, px, py, &q, &o);
            if(o.told) told = (o.message && strcmp(o.message, QUIRK_TABLE[QUIRK_CAVE_IN].tell) == 0) ? 1 : -1;
        }
        CHECK(told == 1, "cave-in: standing by a timber, the timbers eventually groan");
    }
}

/* ── the corruption arc (spec 58 steps 5-7) ─────────────────────────── */

/* Every glyph means one thing: a tile is read back as loot by
 * kind_by_glyph, so a kind must never share a glyph with terrain, a
 * primitive, a fixed tile or a creature. */
static void test_glyphs_unique_across_tables(void) {
    char fixed[] = {TILE_FLOOR, TILE_WALL, TILE_ROCK, TILE_DOOR, TILE_STAIRS_UP, TILE_STAIRS_DOWN,
                    TILE_VENDOR, TILE_VAULT, TILE_SECRET, '@'};
    int clashes = 0;
    for(int i = 0; i < KIND_COUNT; i++) {
        char g = KIND_CATALOG[i].glyph;
        for(size_t f = 0; f < sizeof(fixed); f++) clashes += (g == fixed[f]);
        for(int t = 0; t < terrain_count(); t++) clashes += (g == terrain_at(t)->glyph);
        for(int c = 0; c < CREATURE_FAMILY_COUNT; c++) clashes += (g == CREATURE_FAMILIES[c].glyph);
        for(int p = 0; p < PRIM_COUNT_TOTAL; p++) clashes += (g == PRIMITIVES[p].glyph);
    }
    CHECK(clashes == 0, "glyphs: no item shares a glyph with terrain, a tile or a creature");
}

/* The wave (§58.3.1): the origin is calm, values stay in range, and both
 * the peaks and the valleys grow with depth. */
static void test_corruption_wave(void) {
    const uint32_t seeds[] = {0x12345678u, 0xCAFEBABEu, 0xDEADBEEFu, 0x0BADF00Du};
    int ok_origin = 1, ok_range = 1, ok_dead = 1;
    for(size_t s = 0; s < sizeof(seeds) / sizeof(seeds[0]); s++) {
        ok_origin &= corruption_intensity(seeds[s], 0, 0) == 0;
        for(int ry = -6; ry <= 6; ry++)
            for(int rx = -6; rx <= 6; rx++) {
                int v = corruption_intensity(seeds[s], rx, ry);
                int d = corruption_dead_count(seeds[s], rx, ry);
                ok_range &= v >= 0 && v <= INTENSITY_MAX;
                ok_dead &= d >= DEAD_PER_REGION_MIN && d <= DEAD_PER_REGION_MAX;
            }
    }
    CHECK(ok_origin, "wave: the waking region is calm");
    CHECK(ok_range, "wave: intensity stays in 0..INTENSITY_MAX");
    CHECK(ok_dead, "wave: every region holds DEAD_PER_REGION_MIN..MAX dead");
    /* Along one axis, without jitter's help: each period's valley and peak
     * beat the previous period's. */
    int prev_lo = -1, prev_hi = -1, grows = 1;
    for(int p = 1; p <= 3; p++) {
        int lo = INTENSITY_MAX, hi = 0;
        for(int d = p * WAVE_PERIOD; d < (p + 1) * WAVE_PERIOD; d++) {
            int v = corruption_intensity(0x12345678u, d, 0) -
                    (int)(region_hash(0x12345678u ^ 0xC0EE7A11u, d, 0) % (WAVE_JITTER + 1));
            if(v < lo) lo = v;
            if(v > hi) hi = v;
        }
        if(prev_lo >= 0) grows &= lo > prev_lo && hi > prev_hi;
        prev_lo = lo;
        prev_hi = hi;
    }
    CHECK(grows, "wave: each period's valley and peak are higher than the last");
}

/* The region book round-trips, tolerates junk, and keeps one record per
 * region (§58.10). */
static void test_region_book(void) {
    RegionBook b;
    region_book_clear(&b);
    CHECK(region_book_get(&b, 0, 0) == NULL, "book: an untouched region has no record");
    RegionRecord* r = region_book_touch(&b, -2, 3);
    r->sealed = 5;
    r->pieces = 3;
    r->destroyed = 7;
    r->flags = RR_FOUND;
    CHECK(region_book_touch(&b, -2, 3) == r && b.count == 1, "book: touching twice keeps one record");
    region_book_touch(&b, 4, 0)->destroyed = 255;
    char buf[REGION_BOOK_TEXT_MAX];
    region_book_format(&b, buf, sizeof(buf));
    RegionBook q;
    region_book_parse(buf, &q);
    const RegionRecord* g = region_book_get(&q, -2, 3);
    CHECK(q.count == 2 && g && g->sealed == 5 && g->pieces == 3 && g->destroyed == 7 &&
          g->flags == RR_FOUND && region_book_get(&q, 4, 0)->destroyed == 255,
          "book: format then parse round-trips every field");
    region_book_parse("v9\n0 0 1 1 1 1\n", &q);
    CHECK(q.count == 0, "book: an unknown version loads empty");
    region_book_parse("v1\n0 0 1 0 0 1\nnonsense\n1 1 2 0 0 0\n", &q);
    CHECK(q.count == 2 && region_book_get(&q, 1, 1)->sealed == 2, "book: a bad line is skipped");
    RegionBook full;
    region_book_clear(&full);
    for(int i = 0; i < REGION_BOOK_MAX; i++) region_book_touch(&full, i, 0);
    CHECK(region_book_touch(&full, 99, 99) == NULL && region_book_get(&full, 5, 0) != NULL,
          "book: a full book refuses a new region and keeps the old");
    char big[REGION_BOOK_TEXT_MAX];
    for(int i = 0; i < REGION_BOOK_MAX; i++) {
        RegionRecord* w = region_book_touch(&full, i, 0);
        w->rx = -32000; w->ry = -32000; w->sealed = w->pieces = w->destroyed = w->flags = 255;
    }
    size_t n = region_book_format(&full, big, sizeof(big));
    CHECK(n < sizeof(big) - 1, "book: the widest full book fits REGION_BOOK_TEXT_MAX");
}

/* Effort (§58.7.5): one function, the same inputs give the same outcome,
 * the odds the player is told are the outcome they get, skill lowers the
 * drain, and effort alone never empties health. */
static uint16_t run_effort(const EffortTask* t, EffortBody* b, EffortState* end) {
    EffortRun r;
    effort_begin(&r, t, b);
    EffortState st = EFFORT_GOING;
    int guard = 0;
    while(st == EFFORT_GOING && guard++ < 300) st = effort_turn(&r, b);
    *end = st;
    return r.paid;
}

static void test_effort(void) {
    int told_true = 1, floors = 1, same = 1, cases = 0;
    for(int fuel = 0; fuel <= 120; fuel += 7)
        for(int hp = 1; hp <= 20; hp += 3)
            for(int axis = 4; axis <= 22; axis += 3)
                for(int turns = 1; turns <= 8; turns++)
                    for(int diff = 1; diff <= 16; diff += 3) {
                        EffortTask t = {(uint8_t)turns, (uint8_t)diff, 0};
                        EffortBody b = {(uint16_t)fuel, (uint16_t)hp, (uint8_t)axis};
                        bool can = effort_can(&t, &b);
                        EffortBody b1 = b, b2 = b;
                        EffortState e1, e2;
                        run_effort(&t, &b1, &e1);
                        run_effort(&t, &b2, &e2);
                        same &= e1 == e2 && b1.hp == b2.hp && b1.fuel == b2.fuel;
                        told_true &= can == (e1 == EFFORT_DONE);
                        floors &= b1.hp >= (hp < EFFORT_HP_FLOOR ? hp : EFFORT_HP_FLOOR) && b1.hp >= 1;
                        floors &= b1.fuel >= (fuel < EFFORT_FUEL_FLOOR ? fuel : EFFORT_FUEL_FLOOR);
                        cases++;
                    }
    CHECK(cases > 1000 && same, "effort: the same inputs give the same outcome");
    CHECK(told_true, "effort: the task succeeds exactly when the odds said it would");
    CHECK(floors, "effort: health never drops to zero, fuel never below its floor");
    /* Skill lowers the drain: more skill, never more taken from the body,
     * and strictly less while the body is still paying. */
    int lowers = 1;
    EffortTask t = {6, 8, 0};
    int prev = 1 << 30;
    for(int axis = EFFORT_SKILL_BASE; axis <= EFFORT_SKILL_BASE + 14; axis++) {
        EffortBody b = {100, 20, (uint8_t)axis};
        EffortState e;
        run_effort(&t, &b, &e);
        int drain = (100 - b.fuel) + (20 - b.hp);
        if(prev > 0) lowers &= drain < prev;
        else lowers &= drain == 0;
        prev = drain;
    }
    CHECK(lowers, "effort: more skill strictly lowers what the body pays");
    EffortTask big = {8, 16, 0};
    EffortBody tired = {10, 3, 10}, rested = {100, 10, 20};
    CHECK(strcmp(effort_odds_line(&big, &tired), "you are too tired for this.") == 0 &&
          strcmp(effort_odds_line(&big, &rested), "your hands are steady.") == 0,
          "effort: the odds are told in words");
    /* A failed task stops where the body runs out and keeps what it spent. */
    EffortBody b = {20, 5, 8};
    EffortState e;
    uint16_t paid = run_effort(&big, &b, &e);
    CHECK(e == EFFORT_SPENT && b.fuel == EFFORT_FUEL_FLOOR && b.hp == EFFORT_HP_FLOOR &&
          paid == (20 - EFFORT_FUEL_FLOOR) + (5 - EFFORT_HP_FLOOR),
          "effort: failure spends the body down to its floors, no further");
}

/* Solvable by construction (§58.10, §58.17): for many seeds and every
 * region out to radius 3, everything WORLDGEN 9 set aside is really placed,
 * inside the region; there's an artifact for every site and the words for
 * every kind of site; and the easiest way is open to any fresh character
 * (an axis as low as Profile Review allows, 8, and no deeds), with everything it needs placed. The waking
 * region is checked like the rest: gates only ever open outward from it. */
static void test_rituals_solvable(void) {
    const uint32_t seeds[] = {0x12345678u, 0xCAFEBABEu, 0xDEADBEEFu, 0x0BADF00Du, 0x00000001u, 0x7FFFFFFFu};
    int placed_all = 1, inside = 1, enough_art = 1, words = 1, easy = 1, needs = 1, min_objs = 1, payable = 1;
    int regions = 0;
    for(size_t si = 0; si < sizeof(seeds) / sizeof(seeds[0]); si++) {
        uint32_t seed = seeds[si];
        for(int ry = -3; ry <= 3; ry++)
            for(int rx = -3; rx <= 3; rx++) {
                regions++;
                ArcObject objs[ARC_OBJECTS_MAX];
                int n = region_objects(seed, rx, ry, objs);
                min_objs &= n >= BIOME_REGION * BIOME_REGION;
                int found[ARC_KIND_COUNT] = {0}, art_by_kind[SITE_KIND_COUNT] = {0};
                uint8_t sources = 0;
                int got = 0;
                for(int s = 0; s < BIOME_REGION * BIOME_REGION; s++) {
                    int cx = rx * BIOME_REGION + s % BIOME_REGION, cy = ry * BIOME_REGION + s / BIOME_REGION;
                    World w;
                    world_generate_chunk(seed, cx, cy, &w);
                    for(int a = 0; a < w.arc_count; a++) {
                        got++;
                        found[w.arc[a].what]++;
                        if(w.arc[a].what == ARC_ARTIFACT) art_by_kind[w.arc[a].arg]++;
                        if(w.arc[a].what == ARC_SOURCE) sources |= SITE_BIT(w.arc[a].arg);
                        inside &= region_of(cx) == rx && region_of(cy) == ry;
                        char t = w.tiles[w.arc[a].y][w.arc[a].x];
                        placed_all &= t != TILE_FLOOR && world_walkable(&w, w.arc[a].x, w.arc[a].y);
                    }
                }
                placed_all &= got == n;
                RegionSite sites[SITES_PER_REGION_MAX];
                int ns = region_sites(seed, rx, ry, sites);
                int need[SITE_KIND_COUNT] = {0};
                for(int i = 0; i < ns; i++) need[sites[i].kind]++;
                for(int k = 0; k < SITE_KIND_COUNT; k++) {
                    enough_art &= art_by_kind[k] >= need[k];
                    if(need[k]) words &= (sources & SITE_BIT(k)) != 0;
                }
                RegionRite rite;
                region_rite(seed, rx, ry, &rite);
                easy &= (rite.ways & WAY_BIT(rite.easiest)) && rite.threshold[rite.easiest] <= 8;
                int ways = 0;
                for(int w = 0; w < WAY_COUNT; w++) ways += (rite.ways >> w) & 1;
                easy &= ways >= 2;
                switch(rite.easiest) {
                case WAY_SPOKEN: needs &= found[ARC_PIECE] == rite.pieces && rite.pieces >= 2; break;
                case WAY_MADE:   needs &= found[ARC_MADE_TOME] == 1 && found[ARC_COMPONENT] == 2; break;
                case WAY_KEPT:   needs &= found[ARC_FOCUS] == 3; break;
                case WAY_SEEN:   needs &= found[ARC_CLUE] == rite.runes; break;
                }
                EffortTask t = ritual_task(&rite, (RitualWay)rite.easiest);
                EffortBody fresh = {TORCH_FUEL_MAX, 10, 8};   /* the weakest fresh axis */
                payable &= effort_can(&t, &fresh);
            }
    }
    printf("  rituals: %d regions checked\n", regions);
    CHECK(min_objs, "rituals: every region sets aside at least one object per chunk");
    CHECK(placed_all, "rituals: everything a region sets aside is placed, on walkable ground");
    CHECK(inside, "rituals: every object lies inside its own region");
    CHECK(enough_art, "rituals: there is an artifact for every site");
    CHECK(words, "rituals: the words for every kind of site are in the region");
    CHECK(easy, "rituals: the easiest of 2-4 ways asks no more skill than a fresh character has");
    CHECK(needs, "rituals: everything the easiest way needs is placed");
    CHECK(payable, "rituals: a fresh character can pay the easiest rite's effort");
}

/* The seen puzzle: its own answer solves it, a start position isn't the
 * answer, and no two runes (at any turn) look alike, nor does a rune look
 * like itself turned, so the clue's turn is readable. */
static void test_runes(void) {
    uint8_t icons[RUNE_SHAPES][4][8];
    for(int s = 0; s < RUNE_SHAPES; s++)
        for(int t = 0; t < 4; t++) rune_icon((uint8_t)s, (uint8_t)t, icons[s][t]);
    int distinct = 1;
    for(int a = 0; a < RUNE_SHAPES * 4; a++)
        for(int b = a + 1; b < RUNE_SHAPES * 4; b++)
            distinct &= memcmp(icons[a / 4][a % 4], icons[b / 4][b % 4], 8) != 0;
    CHECK(distinct, "runes: every shape at every turn looks different");
    int solves = 1, starts_wrong = 1, kinds[3] = {0};
    for(uint32_t seed = 1; seed < 40; seed++)
        for(int r = -2; r <= 2; r++) {
            RunePuzzle p;
            rune_puzzle(seed * 0x9E3779B9u, r, -r, &p);
            kinds[p.kind]++;
            solves &= rune_answer(&p, p.turn, p.order);
            if(p.kind != PUZZLE_ORDER) starts_wrong &= !rune_answer(&p, p.start, p.order);
            uint8_t seen = 0;
            for(int i = 0; i < p.count; i++) seen |= (uint8_t)(1u << p.order[i]);
            solves &= seen == (uint8_t)((1u << p.count) - 1u) && p.count >= RUNES_MIN && p.count <= RUNES_MAX;
        }
    CHECK(solves, "runes: the answer solves the puzzle, and the order is a permutation");
    CHECK(starts_wrong, "runes: a turning puzzle never starts solved");
    CHECK(kinds[0] && kinds[1] && kinds[2], "runes: all three kinds of puzzle occur");
}

/* The arc's verbs, end to end in pure logic (§58.5, §58.7): in every region
 * out to radius 2, a fresh character who picks up everything the region
 * placed and steps on every carving can seal every site, finds the region
 * cleansed, and has the easiest way both open and ready, with the effort to
 * pay for it. Only what the region itself placed is used. */
static void test_arc_route1(void) {
    const uint32_t seeds[] = {0x12345678u, 0xCAFEBABEu, 0xDEADBEEFu, 0x0BADF00Du};
    int sealed_all = 1, cleansed = 1, open = 1, ready = 1, refuse = 1, regions = 0;
    for(size_t si = 0; si < sizeof(seeds) / sizeof(seeds[0]); si++) {
        uint32_t seed = seeds[si];
        for(int ry = -2; ry <= 2; ry++)
            for(int rx = -2; rx <= 2; rx++) {
                regions++;
                CharacterState c;
                memset(&c, 0, sizeof(c));
                c.hp = 10; c.torch_fuel = TORCH_FUEL_MAX;
                RegionBook book;
                region_book_clear(&book);
                for(int s = 0; s < BIOME_REGION * BIOME_REGION; s++) {
                    int cx = rx * BIOME_REGION + s % BIOME_REGION, cy = ry * BIOME_REGION + s / BIOME_REGION;
                    World w;
                    world_generate_chunk(seed, cx, cy, &w);
                    for(int a = 0; a < w.arc_count; a++) {
                        int x = w.arc[a].x, y = w.arc[a].y;
                        char t = w.tiles[y][x];
                        if(t == TILE_CARVING) {
                            ArcStep st;
                            arc_step(seed, cx, cy, &w, x, y, 10, &book, &st);
                        } else {
                            const KindDef* k = kind_by_glyph(t);
                            arc_pickup(&w, x, y, &c);
                            if(k) c.inv_qty[k->id]++;
                        }
                    }
                }
                /* the made way: craft the ward at the forge if taught */
                const RecipeDef* ward = recipe_def(ARC_RECIPE_WARD);
                if(recipe_known(ARC_RECIPE_WARD, c.recipes_known) &&
                   recipe_craftable(ward, c.inv_qty, SAVE_INV_KINDS_MAX)) {
                    c.inv_qty[ward->input_kind_a]--;
                    c.inv_qty[ward->input_kind_b]--;
                    c.inv_qty[ward->output_kind]++;
                }
                RegionRite rite;
                region_rite(seed, rx, ry, &rite);
                uint8_t axes[DEED_AXIS_COUNT] = {8, 8, 8, 8, 8, 8};   /* the floor of Profile Review */
                /* Not before it is cleansed: nothing is sealed yet. */
                refuse &= !arc_region_cleansed(seed, rx, ry, &book);
                RegionSite sites[SITES_PER_REGION_MAX];
                int ns = region_sites(seed, rx, ry, sites);
                for(int k = 0; k < ns; k++)
                    sealed_all &= arc_seal(rx, ry, k, sites[k].kind, &c, &book) == ARC_SEALED;
                cleansed &= arc_region_cleansed(seed, rx, ry, &book);
                open &= (arc_ways_open(seed, rx, ry, axes) & WAY_BIT(rite.easiest)) != 0;
                ready &= arc_way_ready(seed, rx, ry, (RitualWay)rite.easiest, &c, &book);
            }
    }
    CHECK(regions == 100, "arc: 4 seeds x 25 regions walked");
    CHECK(refuse, "arc: a region with nothing sealed is not cleansed");
    CHECK(sealed_all, "arc: every site seals with only what its region placed");
    CHECK(cleansed, "arc: a region with every site sealed is cleansed (route 1)");
    CHECK(open, "arc: the easiest way is open to a fresh character");
    CHECK(ready, "arc: after gathering, the easiest way is ready");
}

/* Sealing's refusals, and what it spends. */
static void test_arc_seal_rules(void) {
    CharacterState c;
    memset(&c, 0, sizeof(c));
    RegionBook b;
    region_book_clear(&b);
    CHECK(arc_seal(0, 0, 0, SITE_GRAVE, &c, &b) == ARC_NEED_WORDS, "seal: without the words, no");
    c.words_known = (uint8_t)SITE_BIT(SITE_GRAVE);
    CHECK(arc_seal(0, 0, 0, SITE_GRAVE, &c, &b) == ARC_NEED_ARTIFACT, "seal: without the artifact, no");
    c.inv_qty[arc_artifact_kind(SITE_TOMB)] = 1;
    CHECK(arc_seal(0, 0, 0, SITE_GRAVE, &c, &b) == ARC_NEED_ARTIFACT, "seal: the wrong artifact won't do");
    c.inv_qty[arc_artifact_kind(SITE_GRAVE)] = 2;
    CHECK(arc_seal(0, 0, 0, SITE_GRAVE, &c, &b) == ARC_SEALED &&
          c.inv_qty[arc_artifact_kind(SITE_GRAVE)] == 1 && c.inv_qty[arc_artifact_kind(SITE_TOMB)] == 1,
          "seal: one artifact of the site's kind is spent");
    CHECK(arc_seal(0, 0, 0, SITE_GRAVE, &c, &b) == ARC_ALREADY &&
          c.inv_qty[arc_artifact_kind(SITE_GRAVE)] == 1, "seal: a sealed site takes nothing more");
    CHECK(region_book_get(&b, 0, 0)->flags & RR_FOUND, "seal: sealing finds the region's rot");
    /* The kinds the arc names are the catalog's. */
    CHECK(strcmp(kind_by_id(ARC_KIND_WARD)->true_name, "ward") == 0 &&
          strcmp(kind_by_id(ARC_KIND_CANDLE)->true_name, "candle") == 0 &&
          strcmp(kind_by_id(arc_artifact_kind(SITE_GRAVE))->true_name, "grave-seal") == 0 &&
          recipe_def(ARC_RECIPE_WARD)->output_kind == ARC_KIND_WARD,
          "arc: its kind and recipe ids match the catalogs");
    /* Spending: only what the way consumes, never on failure (the caller
     * calls it only on success). */
    c.inv_qty[ARC_KIND_CANDLE] = c.inv_qty[ARC_KIND_SALT] = c.inv_qty[ARC_KIND_RELIC] = 1;
    arc_way_spend(WAY_KEPT, &c);
    CHECK(!c.inv_qty[ARC_KIND_CANDLE] && !c.inv_qty[ARC_KIND_SALT] && !c.inv_qty[ARC_KIND_RELIC],
          "arc: a kept vigil spends its focus objects");
}

/* The dead's kinds belong to the dead (spec 50 Q1 §Q.3): an ordinary roll
 * never returns one, and adding them changed no ordinary roll; a roll for
 * the dead returns only theirs, all seven reachable. */
static void test_dead_traits(void) {
    /* The ordinary roll, replayed against the pre-dead table: the eight
     * original traits are rows 0..7 and their weights are unchanged, so
     * the same stream must land on the same rows. */
    static const uint8_t W_CAVE[8] = {50, 10, 9, 8, 0, 0, 0, 4}, W_OUT[8] = {50, 0, 0, 0, 10, 9, 8, 4};
    int same = 1, never = 1;
    for(int b = 0; b < 2; b++) {
        const uint8_t* w = b ? W_OUT : W_CAVE;
        Rng r1, r2;
        rng_seed(&r1, 0x5EED0000u + (uint32_t)b);
        rng_seed(&r2, 0x5EED0000u + (uint32_t)b);
        uint32_t total = 0;
        for(int i = 0; i < 8; i++) total += w[i];
        for(int n = 0; n < 4000; n++) {
            uint8_t got = creature_trait_roll(&r1, b ? BIOME_OUTDOOR : BIOME_CAVERN);
            uint32_t pick = rng_range(&r2, 0, total), acc = 0;
            int want = 0;
            for(int i = 0; i < 8; i++) { acc += w[i]; if(w[i] && pick < acc) { want = i; break; } }
            same &= got == want;
            never &= CREATURE_TRAITS[got].family_mask == 0;
        }
    }
    CHECK(same, "dead: adding the seven kinds changed no ordinary trait roll");
    CHECK(never, "dead: an ordinary creature never takes a dead kind");
    int seen = 0, only = 1;
    Rng r;
    rng_seed(&r, 0xDEAD0001u);
    for(int n = 0; n < 4000; n++) {
        uint8_t t = creature_trait_roll_family(&r, n & 1 ? BIOME_OUTDOOR : BIOME_CAVERN, FAMILY_DEAD);
        only &= (CREATURE_TRAITS[t].family_mask & FAMILY_BIT(FAMILY_DEAD)) != 0;
        seen |= 1 << t;
    }
    int kinds = 0;
    for(int i = 0; i < CREATURE_TRAIT_COUNT; i++) kinds += (seen >> i) & 1;
    CHECK(only && kinds == 7, "dead: a rising picks among exactly the dead's seven kinds");
}

/* Route 2 closes (§58.6, §58.10): disturbing a region's sites over and
 * over raises exactly its dead count in all, destroying them all cleanses
 * it, and calmed dead return to the pool and still count. Route 1 holds:
 * with every site sealed nothing is restless. */
static void test_dead_routes(void) {
    const uint32_t seeds[] = {0x12345678u, 0xCAFEBABEu, 0xDEADBEEFu};
    int closes = 1, cleansed = 1, calm = 1, route1 = 1, rite = 1, regions = 0;
    for(size_t si = 0; si < 3; si++)
        for(int ry = -1; ry <= 1; ry++)
            for(int rx = -1; rx <= 1; rx++) {
                uint32_t seed = seeds[si];
                regions++;
                RegionBook book;
                RisenBook rb;
                RegionRituals rit;
                region_book_clear(&book);
                risen_book_clear(&rb);
                region_rituals_clear(&rit);
                int want = corruption_dead_count(seed, rx, ry);
                RegionSite sites[SITES_PER_REGION_MAX];
                int ns = region_sites(seed, rx, ry, sites);
                int raised = 0, destroyed = 0, guard = 0;
                /* calm: raise once, leave the region, the pool is whole again */
                {
                    World w;
                    world_generate_chunk(seed, sites[0].cx, sites[0].cy, &w);
                    Creature cs[CREATURES_MAX];
                    int n = 0;
                    int up = dead_raise(seed, sites[0].cx, sites[0].cy, &w, -1, -1, w.site_x, w.site_y, &book, &rb, cs, &n, CREATURES_MAX);
                    calm &= up > 0 && dead_dormant(seed, rx, ry, &book, &rb) == want - up;
                    calm &= dead_calm_outside(&rb, rx + 5, ry) && dead_dormant(seed, rx, ry, &book, &rb) == want;
                }
                while(dead_restless(seed, rx, ry, &book, &rit) && guard++ < 64) {
                    const RegionSite* s = &sites[guard % ns];
                    World w;
                    world_generate_chunk(seed, s->cx, s->cy, &w);
                    Creature cs[CREATURES_MAX];
                    int n = 0;
                    int up = dead_raise(seed, s->cx, s->cy, &w, -1, -1, w.site_x, w.site_y, &book, &rb, cs, &n, CREATURES_MAX);
                    raised += up;
                    for(int i = 0; i < n; i++) {
                        dead_destroyed(seed, s->cx, s->cy, cs[i].trait_id, &rb, &book);
                        destroyed++;
                    }
                }
                closes &= raised == want && destroyed == want && dead_dormant(seed, rx, ry, &book, &rb) == 0;
                cleansed &= arc_region_cleansed(seed, rx, ry, &book) && !dead_restless(seed, rx, ry, &book, &rit);
                /* route 1 on a fresh book */
                RegionBook b1;
                region_book_clear(&b1);
                route1 &= dead_restless(seed, rx, ry, &b1, &rit);
                region_book_touch(&b1, rx, ry)->sealed = (uint8_t)((1u << ns) - 1u);
                route1 &= !dead_restless(seed, rx, ry, &b1, &rit);
                RegionBook b2;
                region_book_clear(&b2);
                RegionRituals r2;
                region_rituals_clear(&r2);
                region_mark_ritual(&r2, rx, ry);
                rite &= !dead_restless(seed, rx, ry, &b2, &r2);
            }
    CHECK(regions == 27, "dead: 3 seeds x 9 regions");
    CHECK(calm, "dead: calmed dead return to the pool and still count");
    CHECK(closes, "dead: disturbing the sites raises exactly the region's dead, no more");
    CHECK(cleansed, "dead: destroying them all cleanses the region (route 2), and it goes quiet");
    CHECK(route1, "dead: with every site sealed, nothing is restless (route 1 holds)");
    CHECK(rite, "dead: once the rite takes hold, nothing is restless");
}

/* The moon's odds (spec 50 Q1 §Q.1.2): none without a moon, about
 * strength / (DEAD_RISE_ODDS * MOON_STRENGTH_MAX) with one; the reach of a
 * disturbance grows with the moon; hordes and loners as the kinds say. */
static void test_dead_chance(void) {
    int none = 0, full = 0;
    const int N = 200000;
    for(int i = 0; i < N; i++) {
        none += dead_chance(0x12345678u, 3, -2, i % 16, i % 6, (uint32_t)i, 0);
        full += dead_chance(0x12345678u, 3, -2, i % 16, i % 6, (uint32_t)i, MOON_STRENGTH_MAX);
    }
    int expect = N / DEAD_RISE_ODDS;
    CHECK(none == 0, "dead: no moon, no chance rising");
    CHECK(full > expect * 3 / 4 && full < expect * 5 / 4, "dead: about 1 in 64 at the full moon");
    CHECK(dead_disturb_radius(0) == DISTURB_RADIUS_MIN && dead_disturb_radius(MOON_STRENGTH_MAX) == DISTURB_RADIUS_MAX &&
          dead_disturb_radius(8) > DISTURB_RADIUS_MIN && dead_disturb_radius(8) < DISTURB_RADIUS_MAX,
          "dead: the stronger the moon, the wider the disturbance");
    int hordes = 0, alone = 0;
    for(int t = 0; t < CREATURE_TRAIT_COUNT; t++)
        if(creature_trait_fits(FAMILY_DEAD, (uint8_t)t)) { if(dead_is_horde((uint8_t)t)) hordes++; else alone++; }
    CHECK(hordes == 3 && alone == 4, "dead: ghoulish, feeding, bleeding are hordes; the other four come alone");
    CHECK(dead_resting_place('g') && dead_resting_place('n') && !dead_resting_place('G') && !dead_resting_place('a'),
          "dead: graves and sarcophagi are resting places; opened ones aren't");
    RisenBook rb, q;
    risen_book_clear(&rb);
    RisenRecord r = {-4, 7, 3, 2, 10, 3};
    rb.rec[rb.count++] = r;
    char buf[RISEN_TEXT_MAX];
    risen_book_format(&rb, buf, sizeof(buf));
    risen_book_parse(buf, &q);
    CHECK(q.count == 1 && q.rec[0].cx == -4 && q.rec[0].cy == 7 && q.rec[0].x == 3 && q.rec[0].trait == 10 &&
          q.rec[0].count == 3, "dead: the risen records round-trip");
    risen_book_parse("v1\n0 0 3 2 0 2\n", &q);
    CHECK(q.count == 0, "dead: a record of a kind that isn't the dead's is dropped");
}

/* The destructive tree (spec 50 Q1 §Q.10.5) and the corrupted kinds. */
static void test_dark_tree(void) {
    int corrupt_restorative = 0, hidden = 1, branch_rooted = 1, branches = 0;
    for(int i = 0; i < RECIPE_COUNT; i++) {
        const RecipeDef* r = recipe_def((uint8_t)i);
        const KindDef* a = kind_by_id(r->input_kind_a);
        const KindDef* b = r->input_kind_b == RECIPE_NO_INPUT ? NULL : kind_by_id(r->input_kind_b);
        bool corrupt_in = (a->flags & KF_CORRUPTED) || (b && (b->flags & KF_CORRUPTED));
        if(r->cls == RC_RESTORATIVE && corrupt_in) corrupt_restorative++;
        if(r->cls == RC_DESTRUCTIVE) {
            hidden &= !recipe_known((uint8_t)i, 0);
            if(!corrupt_in) {   /* a branch: fed by the tree, not by rot */
                branches++;
                int fed = 0;
                for(int j = 0; j < RECIPE_COUNT; j++) {
                    const RecipeDef* q = recipe_def((uint8_t)j);
                    if(q->cls == RC_DESTRUCTIVE &&
                       (q->output_kind == r->input_kind_a || q->output_kind == r->input_kind_b)) fed = 1;
                }
                branch_rooted &= fed;
            }
        }
    }
    CHECK(corrupt_restorative == 0, "dark: no corrupted kind is an input to a restorative recipe");
    CHECK(hidden, "dark: every destructive recipe starts undiscovered");
    CHECK(branches == 1 && branch_rooted, "dark: the branch (Blight) takes the roots' outputs, so it can't be skipped");
    int corrupt_ok = 1, corrupt_n = 0;
    for(int k = 0; k < KIND_COUNT; k++) {
        if(!(KIND_CATALOG[k].flags & KF_CORRUPTED)) continue;
        corrupt_n++;
        int fresh = 0;
        for(int f = 0; f < KIND_COUNT; f++) fresh |= afflict_spoils_into((uint8_t)f) == k;
        corrupt_ok &= KIND_CATALOG[k].weight == 0 && KIND_CATALOG[k].heal == 0 &&
                      !(KIND_CATALOG[k].flags & KF_CONSUMABLE) && fresh;
    }
    CHECK(corrupt_n == 2 && corrupt_ok, "dark: each corrupted kind never drops, heals nothing, and rot makes it");
    /* Discovery: experimenting, reading. */
    CharacterState c;
    memset(&c, 0, sizeof(c));
    CHECK(afflict_experiment(&c) == -1 && c.recipes_known == 0, "dark: experimenting with nothing teaches nothing");
    c.inv_qty[AF_KIND_ROTCAP] = 2;
    CHECK(afflict_carries_corrupted(&c), "dark: a rotted cap is corrupted");
    CHECK(afflict_experiment(&c) == AF_RECIPE_TINCTURE && recipe_known(AF_RECIPE_TINCTURE, c.recipes_known) &&
          c.inv_qty[AF_KIND_ROTCAP] == 2, "dark: experimenting finds what the bag can make, and spends nothing");
    CHECK(afflict_experiment(&c) == -1, "dark: nothing is found twice");
    CharacterState d;
    memset(&d, 0, sizeof(d));
    int root = afflict_read('}', 0x12345678u, 2, 3, 4, 1, &d);
    CHECK((root == AF_RECIPE_TINCTURE || root == AF_RECIPE_DRAUGHT) && afflict_read('{', 0, 0, 0, 1, 1, &d) == AF_RECIPE_BLIGHT &&
          afflict_read('?', 0, 0, 0, 1, 1, &d) == -1, "dark: a book teaches a root, a tome the branch, a scroll neither");
}

/* The seven kinds' effects (spec 50 Q1 §Q.3, §Q.4). */
static Creature dead_at(uint8_t effect, int x, int y) {
    Creature c;
    memset(&c, 0, sizeof(c));
    c.family_id = FAMILY_DEAD;
    for(int t = 0; t < CREATURE_TRAIT_COUNT; t++)
        if(CREATURE_TRAITS[t].family_mask && CREATURE_TRAITS[t].effect == effect) c.trait_id = (uint8_t)t;
    c.x = (uint8_t)x; c.y = (uint8_t)y; c.alive = 1;
    return c;
}

static void test_dead_effects(void) {
    Creature cs[6];
    AreaFelt a;
    cs[0] = dead_at(TE_WITHER, 5, 2);
    afflict_area(cs, 1, 7, 2, &a);
    CHECK(a.wither && !a.chill && !a.rot, "effects: within reach, a withered one burns your light");
    afflict_area(cs, 1, 8, 2, &a);
    CHECK(!a.wither, "effects: beyond AREA_RADIUS, nothing");
    cs[0].family_id = 0;
    afflict_area(cs, 1, 6, 2, &a);
    CHECK(!a.wither, "effects: only the dead carry them");
    /* a ghoulish horde flanks: each other one beside you adds to the attack */
    cs[0] = dead_at(TE_FLANK, 4, 2);
    cs[1] = dead_at(TE_FLANK, 6, 2);
    cs[2] = dead_at(TE_FLANK, 5, 1);
    cs[3] = dead_at(TE_FLANK, 8, 2);   /* not beside you */
    CHECK(afflict_foe_bonus(cs, 4, 0, 5, 2, 10, 10) == 2 * HORDE_FLANK_ATK, "effects: a horde flanks you");
    cs[0] = dead_at(TE_FEED, 4, 2);
    CHECK(afflict_foe_bonus(cs, 1, 0, 5, 2, 4, 10) == FEED_ATK && afflict_foe_bonus(cs, 1, 0, 5, 2, 6, 10) == 0,
          "effects: a feeder is stronger once you're below half");
    CharacterState c;
    memset(&c, 0, sizeof(c));
    c.hp = 10;
    uint16_t fhp = 3;
    afflict_foe_hit(cs[0].trait_id, &c, &fhp, 4);
    afflict_foe_hit(cs[0].trait_id, &c, &fhp, 4);
    CHECK(fhp == 4, "effects: a feeder heals on a hit, up to its health");
    Creature bl = dead_at(TE_BLEED, 0, 0);
    afflict_foe_hit(bl.trait_id, &c, &fhp, 4);
    afflict_foe_hit(bl.trait_id, &c, &fhp, 4);
    CHECK(c.bleed == 2 * BLEED_TURNS, "effects: bleeds stack per hit");
    int lost = 0;
    while(afflict_bleed_tick(&c)) lost++;
    CHECK(lost == 2 * BLEED_TURNS && c.hp == 10 - lost && c.bleed == 0, "effects: a bleed costs 1 HP a turn while it runs");
    /* the bloated leave a foul patch that fades */
    FoulField f;
    foul_clear(&f);
    Creature bo = dead_at(TE_FOUL, 0, 0);
    afflict_foe_died(bo.trait_id, 5, 3, 100, &f);
    afflict_foe_died(bl.trait_id, 9, 3, 100, &f);
    CHECK(f.n == 1 && foul_step(&f, 6, 4, 101) == FOUL_DAMAGE && foul_step(&f, 7, 3, 101) == 0,
          "effects: a bloated one's death fouls its tile and the next ones (only the bloated's)");
    CHECK(foul_step(&f, 5, 3, 100 + FOUL_TURNS) == 0 && f.n == 0, "effects: the patch is gone after FOUL_TURNS");
    /* rot spoils, about 1 in ROT_ODDS turns, only what it can */
    CharacterState r;
    memset(&r, 0, sizeof(r));
    r.inv_qty[AF_KIND_FUNGUS] = 200;
    r.inv_qty[AF_KIND_VIAL] = 200;
    int spoiled = 0;
    for(uint32_t t = 0; t < 800; t++) spoiled += afflict_rot(0xCAFEBABEu, 1, 2, t, &r) != 0xFFu;
    CHECK(spoiled > 60 && spoiled < 140 && r.inv_qty[AF_KIND_ROTCAP] + r.inv_qty[AF_KIND_SOURVIAL] == spoiled &&
          r.inv_qty[AF_KIND_FUNGUS] + r.inv_qty[AF_KIND_VIAL] == 400 - spoiled,
          "effects: rot spoils about 1 in 8 turns, a cap or a vial into its corrupted kind");
    CharacterState e;
    memset(&e, 0, sizeof(e));
    int none = 0;
    for(uint32_t t = 0; t < 200; t++) none += afflict_rot(1, 0, 0, t, &e) != 0xFFu;
    CHECK(none == 0, "effects: rot spoils nothing when you carry nothing it can spoil");
    /* the spectral phase through walls, never onto a door: a wall across
     * the room, the player on the far side; a spectral crosses it, an
     * ordinary dead one can't, and neither ever stands on the door. */
    World w;
    world_starter_room(&w);
    for(int y = 0; y < WORLD_ROWS; y++)
        for(int x = 0; x < WORLD_COLS; x++) w.tiles[y][x] = TILE_FLOOR;
    for(int y = 0; y < WORLD_ROWS; y++) w.tiles[y][6] = TILE_WALL;
    w.tiles[0][6] = TILE_DOOR;
    Creature two[2];
    two[0] = dead_at(TE_CHILL, 4, 3);
    two[1] = dead_at(TE_WITHER, 4, 1);
    int crossed = 0, held = 1, on_door = 0;
    for(uint32_t t = 1; t <= 12; t++) {
        creatures_tick(two, 2, &w, 10, 3, 6, 0x5EEDu, t, NULL);
        on_door |= (two[0].y == 0 && two[0].x == 6) || (two[1].y == 0 && two[1].x == 6);
        crossed |= two[0].x > 6;
        held &= two[1].x < 6;
    }
    CHECK(crossed, "effects: the spectral walks through a wall to you");
    CHECK(held, "effects: the other dead are stopped by it");
    CHECK(!on_door, "effects: nothing phases onto a door");
}

/* Whoever may take the seen way can read its clues (spec 58 §58.7.2): at
 * the way's threshold a clue shows its rune; below, a worn mark. */
static void test_clues_readable(void) {
    int checked = 0, ok = 1;
    const uint32_t seed = 0xCAFEBABEu;
    for(int ry = -2; ry <= 2; ry++)
        for(int rx = -2; rx <= 2; rx++) {
            RegionRite rite;
            region_rite(seed, rx, ry, &rite);
            if(!(rite.ways & WAY_BIT(WAY_SEEN))) continue;
            for(int s = 0; s < BIOME_REGION * BIOME_REGION; s++) {
                int cx = rx * BIOME_REGION + s % BIOME_REGION, cy = ry * BIOME_REGION + s / BIOME_REGION;
                World w;
                world_generate_chunk(seed, cx, cy, &w);
                for(int a = 0; a < w.arc_count; a++) {
                    if(w.arc[a].what != ARC_CLUE) continue;
                    RegionBook b;
                    region_book_clear(&b);
                    ArcStep at, below;
                    arc_step(seed, cx, cy, &w, w.arc[a].x, w.arc[a].y, rite.threshold[WAY_SEEN], &b, &at);
                    arc_step(seed, cx, cy, &w, w.arc[a].x, w.arc[a].y, (uint8_t)(rite.threshold[WAY_SEEN] - 1), &b, &below);
                    ok &= at.rune && !below.rune && strcmp(below.line, ARC_LINE_WORN) == 0;
                    checked++;
                }
            }
        }
    CHECK(checked > 0 && ok, "rituals: the seen way's clues are readable exactly at its threshold");
    /* The arc's status lines fit the status bar (about 30 characters). */
    const char* lines[] = {ARC_LINE_READ, ARC_LINE_SEAL, ARC_LINE_RITE, ARC_LINE_CORRUPT, ARC_LINE_SEALED,
                           ARC_LINE_ENTER, ARC_LINE_REFUSED, ARC_LINE_NO_WORDS, ARC_LINE_NO_ARTIFACT,
                           ARC_LINE_CARVED, ARC_LINE_WORN, ARC_LINE_RUNE, ARC_LINE_MISSING, ARC_LINE_FAILED,
                           ARC_LINE_VIGIL, ARC_LINE_BROKEN, DEAD_LINE_GRAVE, DEAD_LINE_TOMB, AF_LINE_NOTHING,
                           AF_LINE_DARK, AF_LINE_COATED};
    int fit = 1;
    for(size_t i = 0; i < sizeof(lines) / sizeof(lines[0]); i++) fit &= strlen(lines[i]) <= 30;
    char spoil[48];
    snprintf(spoil, sizeof(spoil), AF_LINE_SPOIL, "soured vial");
    CHECK(fit && strlen(spoil) <= 30, "copy: every arc line fits the status bar");
}

/* The ranged scanner (spec 46 §5.1, the user's calls 2026-10-22): scan,
 * then fire once its kind is read; casts are earned by deep scans only;
 * MP pays and comes back slowly. */
static void test_ranged_scanner(void) {
    /* rat: scan_diff 15. OBSERVE 20 reads it at tier 2. */
    CHECK(!cast_fires(20, 15, 0, 0) && !cast_fires(20, 15, 3, 0),
          "cast: with no cast known the reticle only scans (earned only)");
    CHECK(!cast_fires(20, 15, 0, CAST_BIT(CAST_REACH)) && !cast_fires(20, 15, 1, CAST_BIT(CAST_REACH)),
          "cast: while a scan would still teach something, OK scans");
    CHECK(cast_fires(20, 15, 2, CAST_BIT(CAST_REACH)) && cast_fires(40, 15, 3, CAST_BIT(CAST_REACH)),
          "cast: once its kind is read as far as you can, OK fires");
    CHECK(!cast_fires(40, 15, 2, CAST_BIT(CAST_REACH)),
          "cast: more OBSERVE means more to learn: it scans again first");
    CHECK(cast_taught_by(ELEM_NONE) == CAST_REACH && cast_taught_by(ELEM_FIRE) == CAST_SPARK &&
          cast_taught_by(ELEM_ICE) == CAST_CHILL, "cast: each element's deep read teaches its cast");
    CHECK(cast_pick(0, 9) == -1 && cast_pick(CAST_BIT(CAST_REACH), 1) == -1 &&
          cast_pick(CAST_BIT(CAST_REACH), 2) == CAST_REACH &&
          cast_pick(CAST_BIT(CAST_REACH) | CAST_BIT(CAST_SPARK), 5) == CAST_SPARK &&
          cast_pick(CAST_BIT(CAST_REACH) | CAST_BIT(CAST_SPARK), 2) == CAST_REACH,
          "cast: the strongest known cast MP can pay for fires");
    CHECK(cast_damage(CAST_REACH, 10, 14) == 2 + 10 / CAST_MIND_DIV - 14 / 8 && cast_damage(CAST_REACH, 0, 200) == 1,
          "cast: damage = power + MIND/4 - def/8, at least 1 (spec 46 §5.1)");
    uint16_t mp = 0;
    for(uint32_t t = 1; t <= 60; t++) mp = cast_mp_regen(mp, 5, t);
    CHECK(mp == 5 && cast_mp_regen(3, 5, MP_REGEN_TURNS) == 4 && cast_mp_regen(3, 5, MP_REGEN_TURNS + 1) == 3,
          "cast: MP comes back one point every MP_REGEN_TURNS, up to its max");
    /* A fresh character can earn one: some family's deep read is within reach. */
    int reachable = 0;
    for(int f = 0; f < CREATURE_FAMILY_COUNT; f++)
        if(CREATURE_FAMILIES[f].weight && creature_scan_tier(20 + 8 + 3, CREATURE_FAMILIES[f].scan_diff) == 3) reachable++;
    CHECK(reachable > 0, "cast: a few scans grow OBSERVE enough to read some family deeply");
}

int main(void) {
    printf("Sanctum RPG — deterministic core tests\n");
    test_fov();
    test_rng_determinism();
    test_rng_range_bounds();
    test_chunk_seed_spread();
    test_loot_catalog_integrity();
    test_loot_equip_shape();
    test_loot_roll_determinism();
    test_loot_roll_distribution();
    test_biome();
    test_chunk_determinism();
    test_chunk_invariants();
    test_chunk_golden();
    test_styles();
    test_sites();
    test_sky();
    test_mutation_guard();
    test_terrain_steps();
    test_style_catalog();
    test_glyphs_vs_weather();
    test_names_determinism();
    test_names_biome_distinct();
    test_names_by_style();
    test_region_tree();
    test_region_gates();
    test_quirk_cave_in();
    test_names_cap_truncates();
    test_names_distribution();
    test_trade_determinism();
    test_trade_home_chunk_not_vendor();
    test_trade_delta_bounds();
    test_trade_vendor_rate();
    test_trade_pricing();
    test_numeraire_excluded_from_pricing();
    test_numeraire_absent_from_shop_lists();
    test_pool_numeraire_exposure();
    test_recipe_oddment_invariant();
    test_econ_vendor_golden();
    test_shard_denomination();
    test_trade_vendor_placement_walkable();
    test_vault_home_chunk_placement();
    test_vault_only_at_home();
    test_bearing_at_home();
    test_bearing_eight_compass();
    test_cavern_egress_known_traps();
    test_cavern_egress_no_trap();
    test_creatures_catalog_integrity();
    test_creature_compose();
    test_creature_roll();
    test_creatures_populate();
    test_creatures_tick();
    test_light_rules();
    test_creature_scan();
    test_creatures_aggro();
    test_creatures_kill_persistence();
    test_classes();
    test_pool_prime_determinism();
    test_pool_at_determinism();
    test_pool_intensity_grows();
    test_pool_canonical_path();
    test_pool_save_uniqueness();
    test_pool_theme_weights_packed();
    test_pool_bag_no_drain_cascade();
    test_pool_bias_queries();
    test_pool_consumers_no_bias_matches_legacy();
    test_pool_consumers_bias_shifts_distribution();
    test_edge_door_agreement();
    test_edge_walls_match_neighbors();
    test_transition_walls_block_open_chunk();
    test_secret_edge_agreement();
    test_secret_sealed_blocks();
    test_compose_corner_roundtrip();
    test_compose_determinism();
    test_compose_interior_only();
    test_compose_places_something();
    test_compose_preserves_nonfloor();
    test_weather_determinism();
    test_weather_indoor_attenuation();
    test_weather_fov_cap();
    test_weather_overlay_density();
    test_weather_biome_temperature();
    test_weather_hot_biome_distribution();
    test_weather_hud_glyph();
    test_creatures_storm_grounds_flyers();
    test_creatures_fog_extends_stealth_notice();
    test_creatures_heat_dampens_aggro();
    test_creatures_rain_pacifies_fire();
    test_recipes();
    test_glyphs_unique_across_tables();
    test_corruption_wave();
    test_region_book();
    test_effort();
    test_rituals_solvable();
    test_runes();
    test_arc_route1();
    test_arc_seal_rules();
    test_dead_traits();
    test_dead_routes();
    test_dead_chance();
    test_dark_tree();
    test_dead_effects();
    test_clues_readable();
    test_ranged_scanner();
    printf("\n%d passed, %d failed\n", g_pass, g_fail);
    return g_fail == 0 ? 0 : 1;
}
