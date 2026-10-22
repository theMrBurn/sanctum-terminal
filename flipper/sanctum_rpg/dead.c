/* dead.c — see dead.h. */
#include "dead.h"

#include <stdio.h>
#include <string.h>

#include "biome.h"
#include "ritual.h"
#include "sky.h"
#include "terrain.h"

#define DEAD_CHANCE_SALT 0xDEAD0C4Eu
#define DEAD_KIND_SALT   0xDEAD0F1Du

/* Which kinds come as a horde (spec 50 Q1 §Q.3), by trait mark and flags:
 * data, never names. Ghoulish (fast), feeding (a jaw), bleeding (drips)
 * are hordes; withered, bloated, spectral and rotting come alone. */
bool dead_is_horde(uint8_t trait) {
    const Trait* t = creature_trait(trait);
    if(!t) return false;
    return t->mark == MARK_MAW || t->mark == MARK_DRIP || t->d_speed >= DEAD_HORDE_SPEED;
}

bool dead_resting_place(char glyph) {
    return terrain_opened(glyph) != 0;
}

int dead_up_in_region(const RisenBook* rb, int rx, int ry) {
    int n = 0;
    for(int i = 0; i < rb->count; i++)
        if(region_of(rb->rec[i].cx) == rx && region_of(rb->rec[i].cy) == ry) n += rb->rec[i].count;
    return n;
}

int dead_dormant(uint32_t seed, int rx, int ry, const RegionBook* book, const RisenBook* rb) {
    const RegionRecord* r = region_book_get(book, rx, ry);
    int n = corruption_dead_count(seed, rx, ry) - (r ? r->destroyed : 0) - dead_up_in_region(rb, rx, ry);
    return n > 0 ? n : 0;
}

bool dead_restless(uint32_t seed, int rx, int ry, const RegionBook* book, const RegionRituals* rituals) {
    if(region_ritual_done(rituals, rx, ry)) return false;
    const RegionRecord* r = region_book_get(book, rx, ry);
    if(r && r->destroyed >= corruption_dead_count(seed, rx, ry)) return false;
    RegionSite sites[SITES_PER_REGION_MAX];
    int n = region_sites(seed, rx, ry, sites);
    uint8_t all = (uint8_t)((1u << n) - 1u);
    return !(n > 0 && r && (r->sealed & all) == all);
}

static uint32_t tile_hash(uint32_t seed, int cx, int cy, int x, int y, uint32_t salt) {
    uint32_t h = region_hash(seed ^ salt, cx, cy);
    h ^= (uint32_t)(x * 0x9E3779B1u) ^ (uint32_t)(y * 0x85EBCA77u);
    h ^= h >> 15; h *= 0x2C1B3C6Du; h ^= h >> 12; h *= 0x297A2D39u; h ^= h >> 15;
    return h;
}

uint8_t dead_rise_kind(uint32_t seed, int cx, int cy, int x, int y, Biome biome) {
    uint8_t bbit = BIOME_BIT(biome);
    uint32_t total = 0;
    for(int i = 0; i < CREATURE_TRAIT_COUNT; i++)
        if(creature_trait_fits(FAMILY_DEAD, (uint8_t)i) && (CREATURE_TRAITS[i].biome_mask & bbit))
            total += CREATURE_TRAITS[i].weight;
    if(total == 0) return 0;
    uint32_t pick = tile_hash(seed, cx, cy, x, y, DEAD_KIND_SALT) % total, acc = 0;
    for(int i = 0; i < CREATURE_TRAIT_COUNT; i++) {
        if(!creature_trait_fits(FAMILY_DEAD, (uint8_t)i) || !(CREATURE_TRAITS[i].biome_mask & bbit)) continue;
        acc += CREATURE_TRAITS[i].weight;
        if(pick < acc) return (uint8_t)i;
    }
    return 0;
}

bool dead_chance(uint32_t seed, int cx, int cy, int x, int y, uint32_t turn, uint8_t strength) {
    if(strength == 0) return false;
    uint32_t h = tile_hash(seed, cx, cy, x, y, DEAD_CHANCE_SALT ^ (turn * 0x01000193u));
    return h % (uint32_t)(DEAD_RISE_ODDS * MOON_STRENGTH_MAX) < strength;
}

int dead_disturb_radius(uint8_t strength) {
    if(strength > MOON_STRENGTH_MAX) strength = MOON_STRENGTH_MAX;
    return DISTURB_RADIUS_MIN + strength * (DISTURB_RADIUS_MAX - DISTURB_RADIUS_MIN) / MOON_STRENGTH_MAX;
}

static bool taken(const Creature* cs, int n, int x, int y) {
    for(int i = 0; i < n; i++)
        if(cs[i].alive && cs[i].x == (uint8_t)x && cs[i].y == (uint8_t)y) return true;
    return false;
}

/* Put up to `want` of kind `trait` on free floor in rings round (x, y). */
static int place_ring(const World* w, int px, int py, int x, int y, uint8_t trait, int want, Creature* cs,
                      int* n, int max) {
    int placed = 0;
    for(int r = 1; r <= 3 && placed < want; r++)
        for(int dy = -r; dy <= r && placed < want; dy++)
            for(int dx = -r; dx <= r && placed < want; dx++) {
                if((dx < 0 ? -dx : dx) != r && (dy < 0 ? -dy : dy) != r) continue;   /* the ring only */
                int tx = x + dx, ty = y + dy;
                if(tx < 0 || ty < 0 || tx >= WORLD_COLS || ty >= WORLD_ROWS) continue;
                if(!world_walkable(w, tx, ty) || (tx == px && ty == py) || taken(cs, *n, tx, ty)) continue;
                if(*n >= max) return placed;
                Creature* c = &cs[(*n)++];
                memset(c, 0, sizeof(*c));
                c->family_id = FAMILY_DEAD;
                c->trait_id = trait;
                c->x = c->spawn_x = (uint8_t)tx;
                c->y = c->spawn_y = (uint8_t)ty;
                c->alive = 1;
                placed++;
            }
    return placed;
}

int dead_raise(uint32_t seed, int cx, int cy, const World* w, int px, int py, int x, int y,
               const RegionBook* book, RisenBook* rb, Creature* cs, int* n, int max) {
    int rx = region_of(cx), ry = region_of(cy);
    int dormant = dead_dormant(seed, rx, ry, book, rb);
    if(dormant <= 0) return 0;
    uint8_t trait = dead_rise_kind(seed, cx, cy, x, y, w->biome);
    int want = dead_is_horde(trait) ? HORDE_SIZE : 1;
    if(want > dormant) want = dormant;
    int up = place_ring(w, px, py, x, y, trait, want, cs, n, max);
    if(up == 0) return 0;
    if(rb->count >= RISEN_RECORDS_MAX) {   /* the oldest calms first */
        memmove(&rb->rec[0], &rb->rec[1], sizeof(rb->rec[0]) * (RISEN_RECORDS_MAX - 1));
        rb->count--;
    }
    RisenRecord* rec = &rb->rec[rb->count++];
    rec->cx = (int16_t)cx;
    rec->cy = (int16_t)cy;
    rec->x = (int8_t)x;
    rec->y = (int8_t)y;
    rec->trait = trait;
    rec->count = (uint8_t)up;
    return up;
}

void dead_restore(const RisenBook* rb, int cx, int cy, const World* w, int px, int py, Creature* cs,
                  int* n, int max) {
    for(int i = 0; i < rb->count; i++) {
        const RisenRecord* r = &rb->rec[i];
        if(r->cx != cx || r->cy != cy || r->count == 0) continue;
        place_ring(w, px, py, r->x, r->y, r->trait, r->count, cs, n, max);
    }
}

bool dead_destroyed(uint32_t seed, int cx, int cy, uint8_t trait, RisenBook* rb, RegionBook* book) {
    for(int i = 0; i < rb->count; i++) {
        RisenRecord* r = &rb->rec[i];
        if(r->cx == cx && r->cy == cy && r->trait == trait && r->count > 0) {
            r->count--;
            if(r->count == 0) {
                memmove(&rb->rec[i], &rb->rec[i + 1], sizeof(rb->rec[0]) * (size_t)(rb->count - i - 1));
                rb->count--;
            }
            break;
        }
    }
    int rx = region_of(cx), ry = region_of(cy);
    RegionRecord* rec = region_book_touch(book, rx, ry);
    if(!rec) return false;
    if(rec->destroyed < 255) rec->destroyed++;
    return rec->destroyed == corruption_dead_count(seed, rx, ry);
}

bool dead_calm_outside(RisenBook* rb, int rx, int ry) {
    int k = 0;
    bool calmed = false;
    for(int i = 0; i < rb->count; i++) {
        if(region_of(rb->rec[i].cx) == rx && region_of(rb->rec[i].cy) == ry) rb->rec[k++] = rb->rec[i];
        else calmed = true;
    }
    rb->count = (uint8_t)k;
    return calmed;
}

void risen_book_clear(RisenBook* rb) { rb->count = 0; }

size_t risen_book_format(const RisenBook* rb, char* out, size_t cap) {
    if(cap == 0) return 0;
    size_t n = (size_t)snprintf(out, cap, "v1\n");
    for(int i = 0; i < rb->count && n < cap; i++) {
        const RisenRecord* r = &rb->rec[i];
        n += (size_t)snprintf(out + n, cap - n, "%d %d %d %d %u %u\n", r->cx, r->cy, r->x, r->y,
                              (unsigned)r->trait, (unsigned)r->count);
    }
    return n < cap ? n : cap - 1;
}

void risen_book_parse(const char* text, RisenBook* out) {
    risen_book_clear(out);
    if(!text || strncmp(text, "v1\n", 3) != 0) return;
    const char* p = text + 3;
    while(*p && out->count < RISEN_RECORDS_MAX) {
        int cx, cy, x, y;
        unsigned t, c;
        if(sscanf(p, "%d %d %d %d %u %u", &cx, &cy, &x, &y, &t, &c) == 6 && x >= 0 && x < WORLD_COLS &&
           y >= 0 && y < WORLD_ROWS && t < (unsigned)CREATURE_TRAIT_COUNT &&
           creature_trait_fits(FAMILY_DEAD, (uint8_t)t) && c > 0 && c <= HORDE_SIZE) {
            RisenRecord* r = &out->rec[out->count++];
            r->cx = (int16_t)cx; r->cy = (int16_t)cy;
            r->x = (int8_t)x; r->y = (int8_t)y;
            r->trait = (uint8_t)t; r->count = (uint8_t)c;
        }
        const char* nl = strchr(p, '\n');
        if(!nl) break;
        p = nl + 1;
    }
}
