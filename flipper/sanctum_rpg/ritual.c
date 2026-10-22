/* ritual.c — see ritual.h. */
#include "ritual.h"

#include <string.h>

#include "biome.h"
#include "corruption.h"
#include "deeds.h"

/* Salts keep every pick independent of the others and of generation. */
#define RITE_WAYS_SALT   0x217E5A75u
#define RITE_COUNT_SALT  0x217EC0E7u
#define RUNE_SALT        0x7E5E7E5Eu
#define ARC_CHUNK_SALT   0xA2C0C4E7u
#define ARC_SOURCE_SALT  0xA2C05C0Eu
#define ARC_SPARE_SALT   0xA2C05BA2u

/* The artifact that seals each kind of site (loot.c). */
static const char ARTIFACT_GLYPH[SITE_KIND_COUNT] = {
    [SITE_GRAVE] = 'e',   /* grave-seal */
    [SITE_TOMB]  = ']',   /* reliquary */
    [SITE_ALTAR] = 'j',   /* censer */
    [SITE_STONE] = 'f',   /* bound stone */
};
static const char SOURCE_GLYPH[3] = {'?', '}', '{'};   /* scroll, book, tome */
#define GLYPH_TOME '{'
static const char COMPONENT_GLYPH[2] = {'z', 'J'};     /* cord, iron nail */
static const char FOCUS_GLYPH[3] = {'K', 'P', ')'};    /* candle, salt, relic */

static uint32_t mix(uint32_t h) {
    h ^= h >> 15; h *= 0x2C1B3C6Du; h ^= h >> 12; h *= 0x297A2D39u; h ^= h >> 15;
    return h;
}

int region_sites(uint32_t seed, int rx, int ry, RegionSite* out) {
    int n = 0;
    int count = region_site_count(seed, rx, ry);
    for(int k = 0; k < count; k++)
        for(int s = 0; s < BIOME_REGION * BIOME_REGION; s++) {
            int cx = rx * BIOME_REGION + s % BIOME_REGION, cy = ry * BIOME_REGION + s / BIOME_REGION;
            if(chunk_site_index(seed, cx, cy) != k) continue;
            uint8_t kind = chunk_site_kind(seed, cx, cy);
            if(kind == SITE_NONE) continue;
            out[n].cx = (int16_t)cx;
            out[n].cy = (int16_t)cy;
            out[n].kind = kind;
            n++;
        }
    return n;
}

void region_rite(uint32_t seed, int rx, int ry, RegionRite* out) {
    memset(out, 0, sizeof(*out));
    int intensity = corruption_intensity(seed, rx, ry);
    uint32_t h = region_hash(seed ^ RITE_WAYS_SALT, rx, ry);

    /* Shuffle the four ways; the first `n` are offered, the first is easiest. */
    uint8_t order[WAY_COUNT] = {WAY_SPOKEN, WAY_MADE, WAY_KEPT, WAY_SEEN};
    uint32_t m = h;
    for(int i = WAY_COUNT - 1; i > 0; i--) {
        m = mix(m + (uint32_t)i);
        int j = (int)(m % (uint32_t)(i + 1));
        uint8_t t = order[i]; order[i] = order[j]; order[j] = t;
    }
    int n = 2 + (int)(region_hash(seed ^ RITE_COUNT_SALT, rx, ry) % 3u);
    out->easiest = order[0];
    for(int i = 0; i < n; i++) {
        out->ways |= WAY_BIT(order[i]);
        out->threshold[order[i]] =
            (uint8_t)(i == 0 ? RITE_SKILL_EASY : RITE_SKILL_EASY + (intensity + 1) / 2);
    }
    out->difficulty = (uint8_t)(2 + intensity / 2);
    int pieces = 2 + intensity / 6;
    out->pieces = (uint8_t)(pieces > SPOKEN_PIECES_MAX ? SPOKEN_PIECES_MAX : pieces);
    uint32_t r = mix(h ^ RUNE_SALT);
    out->runes = (uint8_t)(RUNES_MIN + (int)(r % (RUNES_MAX - RUNES_MIN + 1)));
    out->puzzle = (uint8_t)((r >> 8) % 3u);
}

EffortTask ritual_task(const RegionRite* rite, RitualWay way) {
    static const uint8_t TURNS[WAY_COUNT] = {
        [WAY_SPOKEN] = RITE_TURNS_SPOKEN, [WAY_MADE] = RITE_TURNS_MADE,
        [WAY_KEPT] = RITE_TURNS_KEPT, [WAY_SEEN] = RITE_SEEN_ATTEMPTS,
    };
    EffortTask t = {TURNS[way], rite->difficulty, 0};
    return t;
}

uint8_t ritual_way_axis(RitualWay way, const uint8_t* axes) {
    switch(way) {
    case WAY_SPOKEN: return axes[DEED_AXIS_WILL] > axes[DEED_AXIS_MIND] ? axes[DEED_AXIS_WILL] : axes[DEED_AXIS_MIND];
    case WAY_MADE:   return axes[DEED_AXIS_CRAFT];
    case WAY_KEPT:   return axes[DEED_AXIS_HEART] > axes[DEED_AXIS_BODY] ? axes[DEED_AXIS_HEART] : axes[DEED_AXIS_BODY];
    case WAY_SEEN:   return axes[DEED_AXIS_SIGHT];
    default:         return 0;
    }
}

int region_objects(uint32_t seed, int rx, int ry, ArcObject* out) {
    RegionSite sites[SITES_PER_REGION_MAX];
    int ns = region_sites(seed, rx, ry, sites);
    RegionRite rite;
    region_rite(seed, rx, ry, &rite);
    int n = 0;
#define ADD(w, a) do { out[n].what = (uint8_t)(w); out[n].arg = (uint8_t)(a); n++; } while(0)
    for(int i = 0; i < ns; i++) ADD(ARC_ARTIFACT, sites[i].kind);
    for(int i = 0; i < ARTIFACT_SPARE && ns > 0; i++)
        ADD(ARC_ARTIFACT, sites[region_hash(seed ^ ARC_SPARE_SALT ^ (uint32_t)i, rx, ry) % (uint32_t)ns].kind);
    uint8_t kinds = 0;
    for(int i = 0; i < ns; i++) kinds |= SITE_BIT(sites[i].kind);
    for(int k = 0; k < SITE_KIND_COUNT; k++)
        if(kinds & SITE_BIT(k)) ADD(ARC_SOURCE, k);
    if(rite.ways & WAY_BIT(WAY_SPOKEN))
        for(int i = 0; i < rite.pieces; i++) ADD(ARC_PIECE, i);
    if(rite.ways & WAY_BIT(WAY_MADE)) {
        ADD(ARC_MADE_TOME, 0);
        ADD(ARC_COMPONENT, 0);
        ADD(ARC_COMPONENT, 1);
    }
    if(rite.ways & WAY_BIT(WAY_KEPT))
        for(int i = 0; i < 3; i++) ADD(ARC_FOCUS, i);
    if(rite.ways & WAY_BIT(WAY_SEEN))
        for(int i = 0; i < rite.runes; i++) ADD(ARC_CLUE, i);
#undef ADD
    /* Spread round the region's nine chunks from a hashed start, so no
     * chunk takes more than its share. */
    const int slots = BIOME_REGION * BIOME_REGION;
    uint32_t base = region_hash(seed ^ ARC_CHUNK_SALT, rx, ry) % (uint32_t)slots;
    for(int i = 0; i < n; i++) {
        int s = (int)((base + (uint32_t)i) % (uint32_t)slots);
        out[i].cx = (int16_t)(rx * BIOME_REGION + s % BIOME_REGION);
        out[i].cy = (int16_t)(ry * BIOME_REGION + s / BIOME_REGION);
    }
    return n;
}

char arc_object_glyph(uint32_t seed, int rx, int ry, const ArcObject* o, int index) {
    switch(o->what) {
    case ARC_ARTIFACT:  return ARTIFACT_GLYPH[o->arg % SITE_KIND_COUNT];
    case ARC_SOURCE:    return SOURCE_GLYPH[region_hash(seed ^ ARC_SOURCE_SALT ^ (uint32_t)index, rx, ry) % 3u];
    case ARC_MADE_TOME: return GLYPH_TOME;
    case ARC_COMPONENT: return COMPONENT_GLYPH[o->arg % 2];
    case ARC_FOCUS:     return FOCUS_GLYPH[o->arg % 3];
    case ARC_PIECE:
    case ARC_CLUE:      return TILE_CARVING;
    default:            return 0;
    }
}

void rune_puzzle(uint32_t seed, int rx, int ry, RunePuzzle* out) {
    RegionRite rite;
    region_rite(seed, rx, ry, &rite);
    memset(out, 0, sizeof(*out));
    out->count = rite.runes;
    out->kind = rite.puzzle;
    uint32_t h = mix(region_hash(seed ^ RUNE_SALT, rx, ry));
    uint8_t shapes[RUNE_SHAPES];
    for(int i = 0; i < RUNE_SHAPES; i++) shapes[i] = (uint8_t)i;
    for(int i = RUNE_SHAPES - 1; i > 0; i--) {
        h = mix(h + (uint32_t)i);
        int j = (int)(h % (uint32_t)(i + 1));
        uint8_t t = shapes[i]; shapes[i] = shapes[j]; shapes[j] = t;
    }
    for(int i = 0; i < out->count; i++) {
        out->shape[i] = shapes[i];
        h = mix(h + 0x9E37u);
        bool turns = out->kind != PUZZLE_ORDER;
        out->turn[i] = turns ? (uint8_t)(h % 4u) : 0;
        out->start[i] = turns ? (uint8_t)((out->turn[i] + 1u + (h >> 8) % 3u) % 4u) : 0;
        out->order[i] = (uint8_t)i;
    }
    for(int i = out->count - 1; i > 0; i--) {
        h = mix(h + (uint32_t)i * 7u);
        int j = (int)(h % (uint32_t)(i + 1));
        uint8_t t = out->order[i]; out->order[i] = out->order[j]; out->order[j] = t;
    }
}

bool rune_answer(const RunePuzzle* p, const uint8_t* turns, const uint8_t* touched) {
    if(p->kind != PUZZLE_ORDER)
        for(int i = 0; i < p->count; i++)
            if(turns[i] % 4u != p->turn[i]) return false;
    if(p->kind != PUZZLE_TURN)
        for(int k = 0; k < p->count; k++)
            if(touched[k] != p->order[k]) return false;
    return true;
}

/* Six rune shapes, none the same under a turn as itself or another
 * (test_runes checks). Rows top first, LSB = left column. */
static const uint8_t RUNES[RUNE_SHAPES][8] = {
    {0x04, 0x24, 0x14, 0x0C, 0x04, 0x04, 0x04, 0x00},   /* a staff with two twigs */
    {0x41, 0x22, 0x14, 0x08, 0x08, 0x18, 0x28, 0x00},   /* a fork on a crooked foot */
    {0x1E, 0x02, 0x02, 0x0E, 0x02, 0x02, 0x02, 0x00},   /* a flag */
    {0x08, 0x14, 0x22, 0x14, 0x08, 0x08, 0x38, 0x00},   /* a diamond on a hooked tail */
    {0x1E, 0x10, 0x10, 0x1E, 0x02, 0x02, 0x06, 0x00},   /* a hook and its counter */
    {0x22, 0x26, 0x2A, 0x32, 0x22, 0x02, 0x02, 0x00},   /* a ladder leaning */
};

void rune_icon(uint8_t shape, uint8_t turn, uint8_t out[8]) {
    uint8_t a[8];
    memcpy(a, RUNES[shape % RUNE_SHAPES], 8);
    for(int t = 0; t < (int)(turn % 4u); t++) {
        uint8_t b[8] = {0};
        for(int y = 0; y < 8; y++)
            for(int x = 0; x < 8; x++)
                if(a[y] & (1u << x)) b[x] |= (uint8_t)(1u << (7 - y));   /* a quarter turn clockwise */
        memcpy(a, b, 8);
    }
    memcpy(out, a, 8);
}
