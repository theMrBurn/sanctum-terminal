/*
 * pool.h — the world character Pool (spec 50, Tier 2).
 *
 * A small state-propagating struct that walks with the player. Seeded
 * by the campaign's prime stamp (deterministic per prime_seed + biome).
 * Drifts as the player walks via FNV-chain transitions, regenerable by
 * canonical X-first-then-Y walk from the prime to any chunk_xy.
 *
 * Pure module. Integer-only. Byte-equal across hardware. Honors spec
 * 43 §14.0 determinism. NEVER persisted — always regenerated from
 * (prime_seed, biome, chunk_x, chunk_y).
 *
 * Consumers (each its own later slice):
 *   50.F1 — terrain consumer reads primitive_bag + rotation_bias
 *   50.F2 — creature consumer reads family_bias
 *   50.F3 — loot consumer reads loot_kind_bias
 *   50.F4 — narrative consumer reads theme_weights
 *
 * Vocabulary is UNIVERSAL (same primitive IDs across all campaigns),
 * but the per-campaign starting bag is hashed from prime_seed so every
 * save's drift trajectory is unique. Per spec 50 §9.5 + user steer.
 */

#pragma once

#include <stdbool.h>
#include <stdint.h>

#define POOL_THEMES        16  /* mirrors spec 49 §I.1.3 theme vocabulary */
#define POOL_BAG_SLOTS      8  /* primitive bag capacity                  */
#define POOL_FAMILIES       5  /* creature families per biome (spec 45)   */
#define POOL_LOOT_KINDS     7  /* KIND_COUNT (spec 46)                    */
#define BAG_WEIGHT_FLOOR    1  /* no slot's weight drops below this — every
                                * primitive always has presence (spec 50
                                * addendum §F1.A.3 anti-monotony rule)    */

/* Walk directions used by pool_step. Encoded as 0..3 so rotation_bias can
 * mix them cleanly. Order chosen so that east/north flip with west/south
 * cleanly via XOR with 1. */
#define POOL_DIR_EAST   0
#define POOL_DIR_WEST   1
#define POOL_DIR_SOUTH  2
#define POOL_DIR_NORTH  3

/* The Pool. Sized for the stack — 42 bytes packed (spec 50 §2). */
typedef struct {
    /* 16 theme weights packed 4-bits-each into 8 bytes. Use the
     * pool_theme_weight() / pool_set_theme_weight() helpers below. */
    uint8_t theme_weights[POOL_THEMES / 2];

    /* Primitive bag — recently-used/available terrain primitives.
     * Each slot is (primitive_id, weight). Slot 0 has highest priority
     * but the consumer picks weighted, not first-fit. id 0xFF = empty slot. */
    uint8_t primitive_bag[POOL_BAG_SLOTS][2];

    /* Creature family bias — multiplier applied to spec 45 family_roll
     * weights. 0 = neutral; positive = upweight (added to base weight). */
    uint8_t family_bias[POOL_FAMILIES];

    /* Loot kind bias — same pattern, applied in loot_roll (spec 46). */
    uint8_t loot_kind_bias[POOL_LOOT_KINDS];

    /* Drift intensity — distance from prime (saturating uint8). Used by
     * consumers to scale rare/set-piece probability. */
    uint8_t intensity;

    /* Rotation bias — current rotation tendency (0..3, mixed with
     * direction at each step). Spec 50 §4.1 consumer reads this. */
    uint8_t rotation_bias;

    /* Walk pedigree — hash-of-path identity. Equal Pools have equal
     * pedigree; debug-fingerprintable. Drives the FNV-chain mixing. */
    uint32_t pedigree;

    /* Anti-recurrence: the bag slot whose weight dropped on the previous
     * pool_step (spec 50 addendum §F1.A.4). Ineligible to drop again on
     * the next step, breaking A↔B oscillation in a tiny bag. 0xFF = no
     * prior step (set at pool_at_prime). */
    uint8_t last_drop_slot;
} Pool;

/* Initialize the Pool at the campaign's prime stamp.
 * Same (prime_seed, biome) → byte-equal Pool.
 *
 * The primitive_bag is seeded with the biome's primitive vocabulary
 * (the user's locked sets: cavern = ST/C/MC/LST/MW; outdoor = SS/CA/MH/
 * DF/SC/SR — spec 50 §C.1/§C.2). Weights are hashed from prime_seed so
 * each save starts with a unique mix — every campaign's vocabulary is
 * "informed by the primitive set, unique by save" per spec 50 §9.5. */
void pool_at_prime(uint32_t prime_seed, uint8_t biome, Pool* out);

/* Compute the Pool at chunk (chunk_x, chunk_y) by canonical X-first-then-
 * Y walk from the prime. Same (prime_seed, biome, x, y) → byte-equal Pool.
 * Walking back retraces; walking forward drifts.
 *
 * Cost: O(|chunk_x| + |chunk_y|) integer steps. ~20 ops per step. Cheap
 * for chunks within ±32 of the prime (spec 50 §3.4). */
void pool_at(uint32_t prime_seed, uint8_t biome, int chunk_x, int chunk_y,
             Pool* out);

/* Advance the Pool one step in `dir` (POOL_DIR_*). Used internally by
 * pool_at and exposed for host-test verification. */
void pool_step(Pool* p, uint32_t prime_seed, int dir);

/* Read a packed theme weight (0..15). Returns 0 on out-of-range index. */
uint8_t pool_theme_weight(const Pool* p, int theme_bit);

/* Convenience bias queries — used by spec 50 §4 consumers. */
uint8_t pool_family_bias(const Pool* p, uint8_t family_id);
uint8_t pool_loot_kind_bias(const Pool* p, uint8_t kind_id);

/* Equality test — byte-equal struct comparison. Pure. */
bool pool_equal(const Pool* a, const Pool* b);
