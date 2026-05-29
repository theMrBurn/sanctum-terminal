/*
 * rng.c — see rng.h.
 */

#include "rng.h"

void rng_seed(Rng* r, uint32_t s) {
    r->state = s ? s : 1u; /* xorshift collapses on 0 */
}

uint32_t rng_next(Rng* r) {
    uint32_t x = r->state;
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    r->state = x;
    return x;
}

uint32_t rng_range(Rng* r, uint32_t lo, uint32_t hi) {
    if(hi <= lo) return lo;
    uint32_t span = hi - lo;
    /* Rejection sampling removes modulo bias: discard the lowest
     * (2^32 mod span) outputs, so the accepted range is an exact
     * multiple of span and every residue is equally likely. Still
     * fully deterministic for a given seed (the rejection path is
     * itself part of the deterministic sequence). Matters because
     * this is the prime reference impl the PC port must reproduce. */
    uint32_t reject = (uint32_t)(-span) % span; /* == 2^32 mod span */
    uint32_t x;
    do {
        x = rng_next(r);
    } while(x < reject);
    return lo + (x % span);
}

uint32_t rng_chunk_seed(uint32_t base, int chunk_x, int chunk_y) {
    /* Mix base with chunk coords using golden-ratio-derived multipliers
     * (Knuth-style). Final integer-hash pass spreads bits so chunks
     * with adjacent (x,y) don't share visible structure. */
    uint32_t s = base;
    s ^= (uint32_t)chunk_x * 0x9E3779B1u;
    s ^= (uint32_t)chunk_y * 0x85EBCA77u;
    /* fmix32 from MurmurHash3 — strong avalanche */
    s ^= s >> 16; s *= 0x7FEB352Du;
    s ^= s >> 15; s *= 0x846CA68Bu;
    s ^= s >> 16;
    return s ? s : 1u;
}
