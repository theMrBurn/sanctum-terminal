/*
 * gen_golden.c — Conformance reference harness for spec 53 §9-A.
 *
 * Compiles with the REAL substrate sources (not copies, not stubs).
 * Emits golden vectors that every conforming port must reproduce byte-for-
 * field-for-field. The Python engine is the first consumer.
 *
 * Build:
 *   cc -std=c11 -Wall -Wextra -Werror -I../../flipper/sanctum_rpg \
 *      ../../flipper/sanctum_rpg/rng.c \
 *      ../../flipper/sanctum_rpg/pool.c \
 *      gen_golden.c -o gen_golden
 *
 * Run and capture:
 *   ./gen_golden > golden_vectors.json
 *
 * Re-run whenever rng.c / pool.c change. Commit the updated
 * golden_vectors.json alongside the substrate change.
 *
 * NEVER hand-edit golden_vectors.json. Its authority is THIS BINARY
 * running the real substrate. If the file and the binary disagree,
 * the binary wins — regenerate.
 *
 * Integer-width / overflow / signedness notes (the gotchas a Python
 * port must handle — also documented in README.md):
 *   - All arithmetic is uint32_t (mod 2^32). Python ints are unbounded;
 *     EVERY shift, multiply, add, and XOR must be masked with & 0xFFFFFFFF.
 *   - rng_range() reject = (uint32_t)(-span) % span
 *       In C: (-span) wraps to (2^32 - span); then (2^32-span) % span.
 *       In Python (-span) % span == 0 for any positive span — WRONG.
 *       Python translation: reject = (0x100000000 - span) % span
 *   - rng_chunk_seed fmix constants are 0x7FEB352D / 0x846CA68B (shifts
 *     16/15/16). NOT the upstream MurmurHash3 fmix32 (0x85EBCA6B /
 *     0xC2B2AE35, shifts 16/13/16). The comment in rng.c is misleading.
 *   - negative chunk_x / chunk_y are cast to uint32_t (two's-complement
 *     wrap) BEFORE the multiply. Python: (x & 0xFFFFFFFF) * MULT & 0xFFFFFFFF.
 *   - Pool struct: sizeof == 48 (NOT 42 as the header comment says).
 *     Three bytes of compiler padding follow rotation_bias before pedigree,
 *     and three bytes follow last_drop_slot. Do NOT raw-memcpy across
 *     languages — use the field-wise layout below.
 *   - pool nibble packing: theme_weights[i/2]; even index → low nibble
 *     (& 0x0F), odd → high nibble (>> 4). Canonical read: pool_theme_weight().
 *   - family_bias seeded 0..7, loot_kind_bias seeded 0..5; both drift-clamp
 *     to [0..15]. The clamp is the runtime invariant, not the seed range.
 *   - FNV offset basis 0x811C9DC5, prime 16777619 (0x01000193).
 *     fnv1a_mix feeds each of the four bytes of v, low byte first.
 *   - pedigree has NO zero-promotion (unlike rng_seed / rng_chunk_seed).
 */

#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "../../flipper/sanctum_rpg/rng.h"
#include "../../flipper/sanctum_rpg/pool.h"

/* ── Named constants (all tunable parameters live here, never inline) ── */

/* Number of rng_next outputs to emit per seed in the sequence block. */
#define RNG_SEQ_LEN        20

/* rng_range test cases */
#define RNG_RANGE_CASES    9

/* rng_chunk_seed test cases */
#define RNG_CHUNK_CASES    8

/* Pool walk test cases */
#define POOL_CASES         6

/* Steps to walk in the pool multi-step cases */
#define POOL_WALK_STEPS    5

/* ── Helper: emit a Pool's logical fields as a JSON object ────────── */

static void emit_pool(const Pool* p) {
    printf("      {\n");

    /* Theme weights — 16 values, each 0..15, via the accessor that handles
     * nibble packing correctly. */
    printf("        \"theme_weights\": [");
    for(int t = 0; t < POOL_THEMES; t++) {
        if(t) printf(", ");
        printf("%u", (unsigned)pool_theme_weight(p, t));
    }
    printf("],\n");

    /* Primitive bag — 8 slots × {id, weight}. */
    printf("        \"primitive_bag\": [");
    for(int s = 0; s < POOL_BAG_SLOTS; s++) {
        if(s) printf(", ");
        printf("[%u, %u]",
               (unsigned)p->primitive_bag[s][0],
               (unsigned)p->primitive_bag[s][1]);
    }
    printf("],\n");

    /* Family bias — 5 values. */
    printf("        \"family_bias\": [");
    for(int f = 0; f < POOL_FAMILIES; f++) {
        if(f) printf(", ");
        printf("%u", (unsigned)p->family_bias[f]);
    }
    printf("],\n");

    /* Loot kind bias — 7 values. */
    printf("        \"loot_kind_bias\": [");
    for(int k = 0; k < POOL_LOOT_KINDS; k++) {
        if(k) printf(", ");
        printf("%u", (unsigned)p->loot_kind_bias[k]);
    }
    printf("],\n");

    printf("        \"intensity\": %u,\n",    (unsigned)p->intensity);
    printf("        \"rotation_bias\": %u,\n", (unsigned)p->rotation_bias);
    printf("        \"pedigree\": %lu,\n",    (unsigned long)p->pedigree);
    printf("        \"last_drop_slot\": %u\n",  (unsigned)p->last_drop_slot);
    printf("      }");
}

/* ── rng section ───────────────────────────────────────────────────── */

static void emit_rng_section(void) {
    printf("  \"rng\": {\n");

    /* 1. Sequences: emit RNG_SEQ_LEN values of rng_next for each seed.
     *    Also emit the state AFTER seeding (before any next()) to pin the
     *    seed-0-promotion behavior. */
    static const uint32_t SEQ_SEEDS[] = {
        0x00000001u,   /* minimum nonzero */
        0x00000000u,   /* zero → promoted to 1; state-after must equal seed=1 */
        0x12345678u,
        0xCAFEBABEu,
        0xDEADBEEFu,
        0xFFFFFFFFu,   /* max uint32 */
    };
    int n_seq = (int)(sizeof(SEQ_SEEDS) / sizeof(SEQ_SEEDS[0]));

    printf("    \"sequences\": [\n");
    for(int i = 0; i < n_seq; i++) {
        Rng r;
        rng_seed(&r, SEQ_SEEDS[i]);
        printf("      {\n");
        printf("        \"seed_arg\": %lu,\n", (unsigned long)SEQ_SEEDS[i]);
        printf("        \"state_after_seed\": %lu,\n", (unsigned long)r.state);
        printf("        \"next_%d\": [", RNG_SEQ_LEN);
        for(int j = 0; j < RNG_SEQ_LEN; j++) {
            if(j) printf(", ");
            printf("%lu", (unsigned long)rng_next(&r));
        }
        printf("],\n");
        printf("        \"state_after_next_%d\": %lu\n", RNG_SEQ_LEN, (unsigned long)r.state);
        printf("      }%s\n", (i < n_seq - 1) ? "," : "");
    }
    printf("    ],\n");

    /* 2. rng_range: emit {lo, hi, result, state_after}.
     *    Includes a large-span case to force the rejection-sampling path.
     *    Each case uses a FRESH seed so cases are independent; the Python
     *    port can verify each row in isolation. state_after pins the stream
     *    position so any rejection-count divergence is detected. */
    static const struct {
        uint32_t seed;
        uint32_t lo;
        uint32_t hi;
    } RANGE_CASES[RNG_RANGE_CASES] = {
        /* small spans — basic coverage */
        { 0x11111111u,  0,  1 },   /* span=1: no rejection possible */
        { 0x22222222u,  3, 17 },   /* span=14: typical */
        { 0x33333333u,  0, 10 },
        { 0x44444444u,  5,  5 },   /* hi==lo: degenerate, returns lo */
        { 0x55555555u,  9,  4 },   /* hi<lo: degenerate, returns lo */
        /* large spans — rejection sampling exercised */
        /* span = 0xC0000000 (3221225472): reject = (2^32) % span = 1073741824
         * ~25% of raw rng_next values are rejected — this WILL hit the loop.
         * seed=0xAAAAAAAA is VERIFIED to trigger rejection (rng_next(state)
         * lands below the reject threshold on the first call — 2 calls total).
         * Use state_after to confirm the extra call was made. */
        { 0xAAAAAAAAu,  0,          0xC0000000u },   /* VERIFIED rejection fires */
        /* span = 0xC0000000, different seed — single-call path */
        { 0x66666666u,  0,          0xC0000000u },
        /* span = 2^31+1 = 2147483649: odd large prime-ish span */
        { 0x77777777u,  0,          0x80000001u },
        /* negative-coord analog — large lo, large hi */
        { 0x88888888u,  0x40000000u, 0xF0000000u },
    };

    printf("    \"range_cases\": [\n");
    for(int i = 0; i < RNG_RANGE_CASES; i++) {
        Rng r;
        rng_seed(&r, RANGE_CASES[i].seed);
        uint32_t result = rng_range(&r, RANGE_CASES[i].lo, RANGE_CASES[i].hi);
        printf("      {\n");
        printf("        \"seed\": %lu,\n",         (unsigned long)RANGE_CASES[i].seed);
        printf("        \"lo\": %lu,\n",            (unsigned long)RANGE_CASES[i].lo);
        printf("        \"hi\": %lu,\n",            (unsigned long)RANGE_CASES[i].hi);
        printf("        \"result\": %lu,\n",        (unsigned long)result);
        printf("        \"state_after\": %lu\n",    (unsigned long)r.state);
        printf("      }%s\n", (i < RNG_RANGE_CASES - 1) ? "," : "");
    }
    printf("    ],\n");

    /* 3. rng_chunk_seed: emit {base, cx, cy, result}.
     *    Covers: zero base, adjacent coords, negative coords (all four
     *    quadrants), and the same base with different coords to confirm
     *    spread. */
    static const struct {
        uint32_t base;
        int       cx, cy;
    } CHUNK_CASES[RNG_CHUNK_CASES] = {
        { 0xCAFEBABEu,   0,   0 },
        { 0xCAFEBABEu,   1,   0 },   /* x+1 must differ */
        { 0xCAFEBABEu,   0,   1 },   /* y+1 must differ */
        { 0xCAFEBABEu,  -1,   0 },   /* negative x — uint32 wrap in mult */
        { 0xCAFEBABEu,   0,  -1 },   /* negative y */
        { 0xCAFEBABEu,  -3,   5 },   /* mixed signs (matches golden test) */
        { 0x00000000u,   0,   0 },   /* zero base */
        { 0xFFFFFFFFu, -16,  16 },   /* extreme values */
    };

    printf("    \"chunk_seed_cases\": [\n");
    for(int i = 0; i < RNG_CHUNK_CASES; i++) {
        uint32_t result = rng_chunk_seed(CHUNK_CASES[i].base,
                                        CHUNK_CASES[i].cx,
                                        CHUNK_CASES[i].cy);
        printf("      {\n");
        printf("        \"base\": %lu,\n",   (unsigned long)CHUNK_CASES[i].base);
        printf("        \"cx\": %d,\n",                     CHUNK_CASES[i].cx);
        printf("        \"cy\": %d,\n",                     CHUNK_CASES[i].cy);
        printf("        \"result\": %lu\n",  (unsigned long)result);
        printf("      }%s\n", (i < RNG_CHUNK_CASES - 1) ? "," : "");
    }
    printf("    ]\n");

    printf("  },\n");
}

/* ── pool section ──────────────────────────────────────────────────── */

static void emit_pool_section(void) {
    printf("  \"pool\": {\n");

    /* Structural metadata — catches padding divergence before any walk. */
    printf("    \"sizeof_pool\": %zu,\n", sizeof(Pool));
    printf("    \"POOL_THEMES\": %d,\n",     POOL_THEMES);
    printf("    \"POOL_BAG_SLOTS\": %d,\n",  POOL_BAG_SLOTS);
    printf("    \"POOL_FAMILIES\": %d,\n",   POOL_FAMILIES);
    printf("    \"POOL_LOOT_KINDS\": %d,\n", POOL_LOOT_KINDS);
    printf("    \"BAG_WEIGHT_FLOOR\": %d,\n", BAG_WEIGHT_FLOOR);

    /* Direction constants — so the Python port uses the same int encoding. */
    printf("    \"POOL_DIR_EAST\": %d,\n",   POOL_DIR_EAST);
    printf("    \"POOL_DIR_WEST\": %d,\n",   POOL_DIR_WEST);
    printf("    \"POOL_DIR_SOUTH\": %d,\n",  POOL_DIR_SOUTH);
    printf("    \"POOL_DIR_NORTH\": %d,\n",  POOL_DIR_NORTH);

    /* Test cases — each covers: at_prime state, then N steps in sequence. */
    static const struct {
        uint32_t prime_seed;
        uint8_t  biome;
        int      chunk_x;
        int      chunk_y;
        /* For the multi-step case: the direction sequence to walk manually
         * (used in the pool_step_sequence block below). */
    } CASES[POOL_CASES] = {
        /* Basic: two biomes at origin */
        { 0xCAFEBABEu, 0 /* BIOME_CAVERN  */,  0,  0 },
        { 0xCAFEBABEu, 1 /* BIOME_OUTDOOR */,  0,  0 },
        /* Positive quadrant */
        { 0xDEADBEEFu, 0,  3,  2 },
        /* Negative x — pool_at X-first walk goes WEST */
        { 0x12345678u, 1, -2,  1 },
        /* Negative y — pool_at X-first walk, Y goes NORTH */
        { 0x12345678u, 0,  1, -3 },
        /* Both negative */
        { 0xFFFFFFFFu, 1, -2, -2 },
    };

    printf("    \"at_prime\": [\n");
    for(int i = 0; i < POOL_CASES; i++) {
        Pool p;
        pool_at_prime(CASES[i].prime_seed, CASES[i].biome, &p);
        printf("      {\n");
        printf("        \"prime_seed\": %lu,\n", (unsigned long)CASES[i].prime_seed);
        printf("        \"biome\": %u,\n",       (unsigned)CASES[i].biome);
        printf("        \"pool\": ");
        emit_pool(&p);
        printf("\n      }%s\n", (i < POOL_CASES - 1) ? "," : "");
    }
    printf("    ],\n");

    /* pool_at: canonical X-first-then-Y walk to (chunk_x, chunk_y). */
    printf("    \"at_xy\": [\n");
    for(int i = 0; i < POOL_CASES; i++) {
        Pool p;
        pool_at(CASES[i].prime_seed, CASES[i].biome,
                CASES[i].chunk_x, CASES[i].chunk_y, &p);
        printf("      {\n");
        printf("        \"prime_seed\": %lu,\n", (unsigned long)CASES[i].prime_seed);
        printf("        \"biome\": %u,\n",       (unsigned)CASES[i].biome);
        printf("        \"chunk_x\": %d,\n",                  CASES[i].chunk_x);
        printf("        \"chunk_y\": %d,\n",                  CASES[i].chunk_y);
        printf("        \"pool\": ");
        emit_pool(&p);
        printf("\n      }%s\n", (i < POOL_CASES - 1) ? "," : "");
    }
    printf("    ],\n");

    /* pool_step_sequence: start at prime, then emit the pool state after
     * EACH individual pool_step call so the Python port can verify each
     * transition, not just the final state.
     * Direction sequence: EAST, SOUTH, WEST, NORTH, EAST (hits all dirs). */
    static const int STEP_DIRS[POOL_WALK_STEPS] = {
        POOL_DIR_EAST, POOL_DIR_SOUTH, POOL_DIR_WEST,
        POOL_DIR_NORTH, POOL_DIR_EAST
    };
    static const char* DIR_NAMES[4] = { "EAST", "WEST", "SOUTH", "NORTH" };

    printf("    \"step_sequences\": [\n");
    /* Run one seed/biome pair through the full step sequence. */
    {
        uint32_t prime_seed = 0xCAFEBABEu;
        uint8_t  biome      = 0; /* BIOME_CAVERN */

        Pool p;
        pool_at_prime(prime_seed, biome, &p);

        printf("      {\n");
        printf("        \"prime_seed\": %lu,\n", (unsigned long)prime_seed);
        printf("        \"biome\": %u,\n",       (unsigned)biome);
        printf("        \"steps\": [\n");
        for(int s = 0; s < POOL_WALK_STEPS; s++) {
            pool_step(&p, prime_seed, STEP_DIRS[s]);
            printf("          {\n");
            printf("            \"step\": %d,\n",       s + 1);
            printf("            \"dir\": \"%s\",\n",    DIR_NAMES[STEP_DIRS[s]]);
            printf("            \"dir_int\": %d,\n",    STEP_DIRS[s]);
            printf("            \"pool\": ");
            emit_pool(&p);
            printf("\n          }%s\n", (s < POOL_WALK_STEPS - 1) ? "," : "");
        }
        printf("        ]\n");
        printf("      }\n");
    }
    printf("    ]\n");

    printf("  }\n");
}

/* ── main ──────────────────────────────────────────────────────────── */

int main(void) {
    printf("{\n");
    printf("  \"_meta\": {\n");
    printf("    \"spec\": \"53_seed_is_truth §9-A\",\n");
    printf("    \"substrate\": \"rng.c + pool.c (flipper/sanctum_rpg)\",\n");
    printf("    \"sizeof_pool_actual\": %zu,\n", sizeof(Pool));
    printf("    \"sizeof_pool_header_comment\": 42,\n");
    printf("    \"WARNING\": \"sizeof_pool_actual != header comment; use actual; never raw-memcpy across languages\"\n");
    printf("  },\n");
    emit_rng_section();
    emit_pool_section();
    printf("}\n");
    return 0;
}
