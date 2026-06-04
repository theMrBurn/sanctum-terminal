/*
 * rng.h — small deterministic PRNG for procgen.
 *
 * xorshift32 with one round of post-mix. The point is *determinism
 * across platforms*: same seed must produce the same sequence on
 * Flipper, on the host's sync-tooling, and in the desktop
 * sanctum-engage when it reads these chunks. Don't replace with
 * platform RNG (rand(), furi_hal_random_get) for any procgen path —
 * those are nondeterministic by design.
 *
 * Spec: sanctum-os/docs/specs/43_app_sanctum_rpg_flipper.md §6.
 */

#pragma once

#include <stdint.h>

typedef struct {
    uint32_t state;
} Rng;

/* Seed the PRNG. state must be nonzero; we promote 0 → 1 silently. */
void rng_seed(Rng* r, uint32_t s);

/* Next 32 random bits. */
uint32_t rng_next(Rng* r);

/* Random integer in [lo, hi). Returns lo if hi<=lo. */
uint32_t rng_range(Rng* r, uint32_t lo, uint32_t hi);

/* Mix a base seed with chunk coordinates to derive the chunk's own
 * deterministic seed. The mix is keyed so that adjacent chunks look
 * unrelated (no visual moiré along chunk boundaries). */
uint32_t rng_chunk_seed(uint32_t base, int chunk_x, int chunk_y);
