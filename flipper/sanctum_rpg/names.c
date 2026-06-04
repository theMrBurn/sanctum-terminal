/*
 * names.c — see names.h. Deterministic procedural place names.
 */

#include "names.h"

#include <string.h>

#include "biome.h"

/* 16 prefixes × 16 suffixes per biome. Order is the contract — reordering
 * a slot is a determinism break (a chunk that was "Vael Hollow" becomes
 * something else). New entries appended go in unused indices ONLY when
 * the table grows past 16 (and that's a separate gen-version bump). */

static const char* const OUT_PREFIX[16] = {
    "Vael", "Mor", "Iren", "Sun", "Wind", "Briar", "Sten", "Reed",
    "Lor", "Far", "Wisp", "Ash", "Glen", "Thorn", "Mire", "Hollow",
};

static const char* const OUT_SUFFIX[16] = {
    " Reach", " Hollow", " Stead", " Moor", " Fold", " Fall",
    " Heath", " Field", "wood", "marsh", "down", "vale",
    "shore", "fen", "barrow", " End",
};

static const char* const CAV_PREFIX[16] = {
    "Karen", "Drum", "Vel", "Khaz", "Stone", "Black", "Iron", "Old",
    "Deep", "Bone", "Echo", "Dust", "Cinder", "Coal", "Salt", "Grim",
};

static const char* const CAV_SUFFIX[16] = {
    " Deep", " Vault", " Lode", " Shaft", " Warren", " Den",
    " Halls", " Drift", " Pit", "lode", "shaft", "stone",
    " Cavern", " Hollow", " Reaches", " Vein",
};

/* FNV-1a-flavored hash, byte-equal port target. Same shape as
 * weather.c's hash so future re-unification is trivial. */
static uint32_t names_hash32(uint32_t a, uint32_t b, uint32_t c, uint32_t d) {
    uint32_t h = 0x811C9DC5u;
    uint32_t vs[4] = {a, b, c, d};
    for(int i = 0; i < 4; i++) {
        uint32_t v = vs[i];
        h ^= (v >>  0) & 0xFFu; h *= 16777619u;
        h ^= (v >>  8) & 0xFFu; h *= 16777619u;
        h ^= (v >> 16) & 0xFFu; h *= 16777619u;
        h ^= (v >> 24) & 0xFFu; h *= 16777619u;
    }
    h ^= h >> 16;
    h *= 0x85EBCA6Bu;
    h ^= h >> 13;
    return h;
}

void name_for_chunk(uint32_t campaign_seed, int chunk_x, int chunk_y,
                    uint8_t biome, char* out, size_t cap) {
    if(!out || cap < 2) return;

    uint32_t h = names_hash32(
        campaign_seed, (uint32_t)chunk_x, (uint32_t)chunk_y, 0x9E3779B9u);

    /* Lower nibble → prefix index; upper nibble of low byte → suffix. The
     * two nibbles share a byte, but the hash pre-avalanches enough that
     * prefix/suffix don't visibly correlate at chunk scale. */
    uint8_t pi = (uint8_t)((h >>  0) & 0x0Fu);
    uint8_t si = (uint8_t)((h >>  4) & 0x0Fu);

    const char* const* prefixes;
    const char* const* suffixes;
    if((Biome)biome == BIOME_CAVERN) {
        prefixes = CAV_PREFIX;
        suffixes = CAV_SUFFIX;
    } else {
        /* OUTDOOR + any future biome that isn't explicitly cavern reads
         * as an outdoor-style name. ARID etc. will get their own table
         * when those biomes ship. */
        prefixes = OUT_PREFIX;
        suffixes = OUT_SUFFIX;
    }

    const char* p = prefixes[pi];
    const char* s = suffixes[si];
    size_t plen = strlen(p);
    size_t slen = strlen(s);

    /* Truncate prefix-first to fit `cap-1` chars plus '\0'. */
    size_t room = cap - 1;
    size_t pcopy = plen < room ? plen : room;
    memcpy(out, p, pcopy);
    room -= pcopy;
    size_t scopy = slen < room ? slen : room;
    memcpy(out + pcopy, s, scopy);
    out[pcopy + scopy] = '\0';
}
