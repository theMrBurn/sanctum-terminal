/*
 * names.c — see names.h. Deterministic procedural place names.
 */

#include "names.h"

#include <string.h>

#include "biome.h"
#include "style.h"

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

/* WORLDGEN 6: the styles that aren't the original two get their own
 * endings (prefixes still come from the realm: underground / above ground).
 * Same contract as above — order is the determinism key. */
static const char* const CRYPT_SUFFIX[16] = {
    " Crypt", " Tomb", " Ossuary", " Barrow", " Sepulchre", " Catacomb",
    " Charnel", "grave", " Rest", " Cairn", " Mound", " Sleep",
    " Tombs", " Undercroft", " Vaults", " Lich-gate",
};

static const char* const MINE_SUFFIX[16] = {
    " Mine", " Shaft", " Adit", " Drift", " Lode", " Works",
    " Diggings", " Pit", " Seam", " Gallery", "cut", " Stope",
    " Delve", " Heading", " Winze", " Level",
};

static const char* const FOREST_SUFFIX[16] = {
    "wood", " Wood", " Grove", " Thicket", " Weald", " Holt",
    " Copse", " Shaw", " Tangle", " Brake", "hurst", " Glade",
    " Wilds", " Greenwood", "dell", " Coppice",
};

static const char* const MANOR_SUFFIX[16] = {
    " Hall", " Manor", " House", " Court", " Grange", " Lodge",
    " Place", " Garth", " Croft", "bury", " Steading", " Rooms",
    " Chambers", " Mansion", " Seat", " Halls",
};

static const char* const KEEP_SUFFIX[16] = {
    " Keep", " Tower", " Hold", " Castle", " Fort", " Bastion",
    " Citadel", " Ward", " Gate", " Watch", " Redoubt", " Donjon",
    " Rampart", " Bailey", "guard", " Spire",
};

static const char* const ABBEY_SUFFIX[16] = {
    " Abbey", " Priory", " Chapel", " Cloister", " Minster", " Shrine",
    " Sanctum", " Chantry", " Friary", " Hermitage", " Nave", " Kirk",
    " Oratory", " Cell", " Rood", " Sanctuary",
};

/* Endings per style. A style's realm (STYLE_TABLE.biome) picks the
 * prefixes; its name_scope picks chunk or region (style.h). */
static const char* const* const STYLE_SUFFIX[STYLE_COUNT] = {
    [STYLE_CAVERN] = CAV_SUFFIX,   [STYLE_MOOR]   = OUT_SUFFIX,
    [STYLE_CRYPT]  = CRYPT_SUFFIX, [STYLE_MINE]   = MINE_SUFFIX,
    [STYLE_FOREST] = FOREST_SUFFIX, [STYLE_MANOR] = MANOR_SUFFIX,
    [STYLE_KEEP]   = KEEP_SUFFIX,  [STYLE_ABBEY]  = ABBEY_SUFFIX,
};

/* Salt for region-scoped names, so a region's name is not its anchor
 * chunk's per-chunk name. */
#define NAME_REGION_SALT 0x52E61F0Du

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
                    uint8_t style, char* out, size_t cap) {
    if(!out || cap < 2) return;
    if(style >= STYLE_COUNT) style = STYLE_MOOR;
    const StyleDef* sd = &STYLE_TABLE[style];

    /* A built place (name_scope REGION) carries one name for every chunk of
     * its region; wild places are named chunk by chunk, as before. */
    uint32_t h = (sd->name_scope == NAME_SCOPE_REGION)
        ? names_hash32(campaign_seed, (uint32_t)region_of(chunk_x),
                       (uint32_t)region_of(chunk_y), NAME_REGION_SALT)
        : names_hash32(campaign_seed, (uint32_t)chunk_x, (uint32_t)chunk_y, 0x9E3779B9u);

    /* Lower nibble → prefix index; upper nibble of low byte → suffix. The
     * two nibbles share a byte, but the hash pre-avalanches enough that
     * prefix/suffix don't visibly correlate at chunk scale. */
    uint8_t pi = (uint8_t)((h >>  0) & 0x0Fu);
    uint8_t si = (uint8_t)((h >>  4) & 0x0Fu);

    /* Underground styles take the stony prefixes; everything else reads
     * as above ground. */
    const char* const* prefixes = (sd->biome == BIOME_CAVERN) ? CAV_PREFIX : OUT_PREFIX;
    const char* const* suffixes = STYLE_SUFFIX[style];

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
