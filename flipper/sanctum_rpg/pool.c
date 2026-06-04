/*
 * pool.c — see pool.h. Spec 50 framework realization (slice 50.F0).
 *
 * Pure module. No Flipper SDK deps. Host-testable. Byte-equal across
 * hardware via integer-only FNV-1a chain transitions.
 */

#include "pool.h"

#include <stddef.h>
#include <string.h>

/* ─── Internal: FNV-1a 32-bit chain hash ──────────────────────────── */

static uint32_t fnv1a_mix(uint32_t h, uint32_t v) {
    h ^= (v & 0xFFu);        h *= 16777619u;
    h ^= ((v >> 8)  & 0xFFu); h *= 16777619u;
    h ^= ((v >> 16) & 0xFFu); h *= 16777619u;
    h ^= ((v >> 24) & 0xFFu); h *= 16777619u;
    return h;
}

static uint32_t fnv1a_seed(uint32_t a, uint32_t b, uint32_t c) {
    uint32_t h = 0x811C9DC5u;
    h = fnv1a_mix(h, a);
    h = fnv1a_mix(h, b);
    h = fnv1a_mix(h, c);
    /* avalanche */
    h ^= h >> 16;
    h *= 0x85EBCA6Bu;
    h ^= h >> 13;
    return h;
}

/* ─── Packed theme weights (16 × 4-bit values in 8 bytes) ──────────── */

uint8_t pool_theme_weight(const Pool* p, int theme_bit) {
    if(!p || theme_bit < 0 || theme_bit >= POOL_THEMES) return 0;
    uint8_t byte = p->theme_weights[theme_bit / 2];
    return (theme_bit & 1) ? (byte >> 4) : (byte & 0x0F);
}

static void pool_set_theme_weight(Pool* p, int theme_bit, uint8_t w) {
    if(!p || theme_bit < 0 || theme_bit >= POOL_THEMES) return;
    if(w > 15) w = 15;
    uint8_t* byte = &p->theme_weights[theme_bit / 2];
    if(theme_bit & 1) {
        *byte = (uint8_t)((*byte & 0x0F) | (w << 4));
    } else {
        *byte = (uint8_t)((*byte & 0xF0) | (w & 0x0F));
    }
}

/* ─── Convenience bias queries ─────────────────────────────────────── */

uint8_t pool_family_bias(const Pool* p, uint8_t family_id) {
    if(!p || family_id >= POOL_FAMILIES) return 0;
    return p->family_bias[family_id];
}

uint8_t pool_loot_kind_bias(const Pool* p, uint8_t kind_id) {
    if(!p || kind_id >= POOL_LOOT_KINDS) return 0;
    return p->loot_kind_bias[kind_id];
}

bool pool_equal(const Pool* a, const Pool* b) {
    if(!a || !b) return a == b;
    return memcmp(a, b, sizeof(Pool)) == 0;
}

/* ─── Biome primitive vocabulary (the user's locked sets) ─────────────
 * Cavern: ST=0, C=1, MC=2, LST=3, MW=4, reserved=5 (spec 50 §C.1).
 * Outdoor: SS=0, CA=1, MH=2, DF=3, SC=4, SR=5 (spec 50 §C.2).
 *
 * The vocabulary is UNIVERSAL — every save uses the same primitive IDs.
 * The per-save starting weights are hashed from prime_seed (below), so
 * each campaign's drift trajectory begins from a unique mix. */
#define BIOME_CAVERN  0u
#define BIOME_OUTDOOR 1u

#define CAVERN_VOCAB_COUNT  6
#define OUTDOOR_VOCAB_COUNT 6

static const uint8_t CAVERN_VOCAB[CAVERN_VOCAB_COUNT] = {0, 1, 2, 3, 4, 5};
static const uint8_t OUTDOOR_VOCAB[OUTDOOR_VOCAB_COUNT] = {0, 1, 2, 3, 4, 5};

static void pool_seed_bag(Pool* p, uint32_t prime_seed, uint8_t biome) {
    /* Initialize bag from biome vocabulary. The primitive IDs go in
     * declared order; the WEIGHTS are hashed from prime_seed so each
     * campaign starts uniquely. Slots beyond vocabulary length stay
     * empty (0xFF id). */
    const uint8_t* vocab = (biome == BIOME_OUTDOOR) ? OUTDOOR_VOCAB : CAVERN_VOCAB;
    uint8_t vlen = (biome == BIOME_OUTDOOR) ? OUTDOOR_VOCAB_COUNT
                                            : CAVERN_VOCAB_COUNT;
    for(int slot = 0; slot < POOL_BAG_SLOTS; slot++) {
        if(slot < vlen) {
            p->primitive_bag[slot][0] = vocab[slot];
            uint32_t h = fnv1a_seed(prime_seed, (uint32_t)biome,
                                    (uint32_t)(0xB00u | slot));
            /* Weight range 4..15 — every starting primitive has presence,
             * but the distribution is unique per save. */
            p->primitive_bag[slot][1] = (uint8_t)(4 + (h % 12u));
        } else {
            p->primitive_bag[slot][0] = 0xFF;
            p->primitive_bag[slot][1] = 0;
        }
    }
}

/* ─── pool_at_prime: initial state at the prime stamp ──────────────── */

void pool_at_prime(uint32_t prime_seed, uint8_t biome, Pool* out) {
    if(!out) return;
    memset(out, 0, sizeof(*out));

    /* Theme weights — 16 themes, each hashed to a 0..15 value. Every save's
     * theme distribution at the prime is unique. */
    for(int t = 0; t < POOL_THEMES; t++) {
        uint32_t h = fnv1a_seed(prime_seed, (uint32_t)biome,
                                (uint32_t)(0xA00u | t));
        pool_set_theme_weight(out, t, (uint8_t)(h % 16u));
    }

    /* Primitive bag — biome vocabulary with hashed starting weights. */
    pool_seed_bag(out, prime_seed, biome);

    /* Family bias — 5 families, hashed to 0..7 each. Sum is unbounded
     * (each is additive into the family_roll weight walk). */
    for(int f = 0; f < POOL_FAMILIES; f++) {
        uint32_t h = fnv1a_seed(prime_seed, (uint32_t)biome,
                                (uint32_t)(0xC00u | f));
        out->family_bias[f] = (uint8_t)(h % 8u);
    }

    /* Loot kind bias — 7 kinds, hashed to 0..5 each. */
    for(int k = 0; k < POOL_LOOT_KINDS; k++) {
        uint32_t h = fnv1a_seed(prime_seed, (uint32_t)biome,
                                (uint32_t)(0xD00u | k));
        out->loot_kind_bias[k] = (uint8_t)(h % 6u);
    }

    out->intensity = 0;
    out->rotation_bias = 0;
    out->pedigree = fnv1a_seed(prime_seed, (uint32_t)biome, 0u);
    out->last_drop_slot = 0xFFu; /* spec 50 addendum §F1.A.4 — no prior step */
}

/* ─── pool_step: advance one chunk in a direction ─────────────────── */

void pool_step(Pool* p, uint32_t prime_seed, int dir) {
    if(!p) return;
    if(dir < 0 || dir > 3) return;

    /* Advance pedigree first — every subsequent drift reads from it. */
    p->pedigree = fnv1a_mix(
        fnv1a_mix(p->pedigree, (uint32_t)dir),
        prime_seed);

    /* Intensity grows with every step (saturating cap per spec 50 §9.4). */
    if(p->intensity < 255) p->intensity++;

    /* Rotation bias drifts by direction (mod 4). */
    p->rotation_bias = (uint8_t)((p->rotation_bias + (uint8_t)dir + 1u) & 3u);

    /* Drift theme weights: small +1/-1 nudges driven by pedigree bits.
     * Each step touches up to 4 theme slots so drift is gradual. */
    for(int n = 0; n < 4; n++) {
        uint32_t h = fnv1a_mix(p->pedigree, (uint32_t)(0xE00u | n));
        int slot = (int)(h & 0x0Fu);
        int delta = ((h >> 8) & 1u) ? +1 : -1;
        int cur = (int)pool_theme_weight(p, slot);
        cur += delta;
        if(cur < 0) cur = 0;
        if(cur > 15) cur = 15;
        pool_set_theme_weight(p, slot, (uint8_t)cur);
    }

    /* Drift family bias: pick one slot, ±1. */
    {
        uint32_t h = fnv1a_mix(p->pedigree, 0xF1F1u);
        int slot = (int)(h % POOL_FAMILIES);
        int delta = ((h >> 16) & 1u) ? +1 : -1;
        int cur = (int)p->family_bias[slot] + delta;
        if(cur < 0) cur = 0;
        if(cur > 15) cur = 15;
        p->family_bias[slot] = (uint8_t)cur;
    }

    /* Drift loot kind bias: pick one slot, ±1. */
    {
        uint32_t h = fnv1a_mix(p->pedigree, 0xF2F2u);
        int slot = (int)(h % POOL_LOOT_KINDS);
        int delta = ((h >> 16) & 1u) ? +1 : -1;
        int cur = (int)p->loot_kind_bias[slot] + delta;
        if(cur < 0) cur = 0;
        if(cur > 15) cur = 15;
        p->loot_kind_bias[slot] = (uint8_t)cur;
    }

    /* Rotate primitive bag — the "recycled to be re-assigned" mechanic
     * from the user's design (spec 50 §0). Per spec 50 addendum §F1.A:
     *
     *   DROP: pick the lowest-weight occupied slot, EXCLUDING (a) slots
     *   at BAG_WEIGHT_FLOOR (every primitive keeps presence) and (b) the
     *   slot drained on the previous step (anti-recurrence). Tiebreaker
     *   is a hashed rotor over the pedigree, NOT lowest-index — index-
     *   tiebreaker caused a drain-cascade where one slot bled to zero
     *   forever within ~30 steps.
     *
     *   BUMP: pick a hashed target slot; if it collides with the drop
     *   slot, walk forward through the bag until a different occupied
     *   slot is found.
     *
     * The bag's CONTENT (primitive IDs) stays universal; only WEIGHTS drift. */
    {
        /* --- DROP --- */
        int drop = -1;
        uint8_t low_w = 255;
        uint8_t rotor = (uint8_t)((p->pedigree >> 24) & 7u);
        for(int r = 0; r < POOL_BAG_SLOTS; r++) {
            int s = (int)((rotor + (uint8_t)r) & 7u);
            uint8_t id = p->primitive_bag[s][0];
            uint8_t w  = p->primitive_bag[s][1];
            if(id == 0xFF) continue;
            if(w <= BAG_WEIGHT_FLOOR) continue;
            if((uint8_t)s == p->last_drop_slot) continue;
            if(w < low_w) { low_w = w; drop = s; }
        }
        if(drop >= 0) {
            p->primitive_bag[drop][1]--;
            p->last_drop_slot = (uint8_t)drop;
        }
        /* else: no eligible candidate — bag is floor-locked this step. */

        /* --- BUMP --- */
        uint32_t h_bump = fnv1a_mix(p->pedigree, 0xF3F3u);
        int bump = (int)(h_bump % POOL_BAG_SLOTS);
        for(int r = 0; r < POOL_BAG_SLOTS; r++) {
            int s = (int)(((uint32_t)bump + (uint32_t)r) % POOL_BAG_SLOTS);
            if(p->primitive_bag[s][0] == 0xFF) continue;
            if(s == drop) continue;
            bump = s;
            break;
        }
        if(bump >= 0 && p->primitive_bag[bump][1] < 15) {
            p->primitive_bag[bump][1]++;
        }
    }
}

/* ─── pool_at: canonical X-first-then-Y walk from prime ─────────────── */

void pool_at(uint32_t prime_seed, uint8_t biome, int chunk_x, int chunk_y,
             Pool* out) {
    if(!out) return;
    pool_at_prime(prime_seed, biome, out);

    /* X first — east (+x) or west (-x). */
    int x_steps = (chunk_x >= 0) ? chunk_x : -chunk_x;
    int x_dir = (chunk_x >= 0) ? POOL_DIR_EAST : POOL_DIR_WEST;
    for(int i = 0; i < x_steps; i++) {
        pool_step(out, prime_seed, x_dir);
    }

    /* Y second — south (+y) or north (-y). */
    int y_steps = (chunk_y >= 0) ? chunk_y : -chunk_y;
    int y_dir = (chunk_y >= 0) ? POOL_DIR_SOUTH : POOL_DIR_NORTH;
    for(int i = 0; i < y_steps; i++) {
        pool_step(out, prime_seed, y_dir);
    }
}
