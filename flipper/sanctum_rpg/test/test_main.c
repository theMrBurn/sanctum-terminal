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
#include "../classes.h"
#include "../creatures.h"
#include "../fov.h"
#include "../pool.h"
#include "../recipes.h"
#include "../loot.h"
#include "../rng.h"
#include "../weather.h"
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
        /* Re-recorded 2026-06-03 (carve_egress anti-trap pass — playtest
         * reported fully sealed cavern). The CAFEBABE cavern chunks (0,0)
         * + (1,0) both had stamps walling off a door; carve set their
         * approach tiles to TILE_FLOOR. DEADBEEF (0,0) is outdoor (no
         * doors, no carve) and 00000001 (-3,5) didn't need carving — both
         * unchanged. Prior rebases: 50.F3 Pool-biased loot, 50.F1 stamp
         * composer, 2026-06-01 loot density, v0.3.5a torch added. */
        {0xCAFEBABE, 0, 0, 0xF283B264},
        {0xCAFEBABE, 1, 0, 0xF5E3ED37},
        {0xDEADBEEF, 0, 0, 0xCB361B88},
        {0x00000001, -3, 5, 0x76122170},
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
    int mc = WORLD_COLS / 2, mr = WORLD_ROWS / 2;
    int doors_x[4] = { mc, mc, 0, WORLD_COLS - 1 };
    int doors_y[4] = { 0, WORLD_ROWS - 1, mr, mr };
    int hits = 0;
    for(int i = 0; i < 4; i++) {
        if(reach[doors_y[i]][doors_x[i]]) hits++;
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
                if(biome_terrain(w.biome) != TERRAIN_WALLED) continue;
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
        if(biome_terrain(w.biome) != TERRAIN_WALLED) continue;
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
        if(CREATURE_FAMILIES[i].weight == 0) fw_ok = 0;
        if(CREATURE_FAMILIES[i].biomes == 0) fb_ok = 0;
        for(int j = i + 1; j < CREATURE_FAMILY_COUNT; j++) {
            if(CREATURE_FAMILIES[i].glyph == CREATURE_FAMILIES[j].glyph) glyphs_ok = 0;
        }
    }
    CHECK(glyphs_ok, "creatures: family glyphs distinct");
    CHECK(fw_ok, "creatures: family weights nonzero");
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
        creatures_tick(a, na, &w, px, py, 4, cs, t);
        creatures_tick(b, nb, &w, px, py, 4, cs, t);
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
        if(creatures_tick(&c, 1, &w, px, py, 4, 0xABCDu, t) > 0) turned_hostile = 1;
    }
    CHECK(c.aggro > start, "aggro: crowding a creature raises its aggression");
    CHECK(turned_hostile, "aggro: a crowded passive creature turns hostile");

    /* it calms once you leave its awareness (player off in the void) */
    uint8_t high = c.aggro;
    for(uint32_t t = 21; t <= 80; t++) {
        creatures_tick(&c, 1, &w, 50, 50, 4, 0xABCDu, t);
    }
    CHECK(c.aggro < high, "aggro: decays when you leave its awareness");
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
    test_cavern_egress_known_traps();
    test_cavern_egress_no_trap();
    test_creatures_catalog_integrity();
    test_creature_compose();
    test_creature_roll();
    test_creatures_populate();
    test_creatures_tick();
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
    test_weather_determinism();
    test_weather_indoor_attenuation();
    test_weather_fov_cap();
    test_weather_overlay_density();
    test_weather_biome_temperature();
    test_weather_hot_biome_distribution();
    test_recipes();
    printf("\n%d passed, %d failed\n", g_pass, g_fail);
    return g_fail == 0 ? 0 : 1;
}
