/* afflict.c — see afflict.h. */
#include "afflict.h"

#include <string.h>

#include "biome.h"
#include "loot.h"
#include "recipes.h"

#define ROT_SALT  0x2077A11Cu
#define READ_SALT 0xB00C5EEDu

static int cheb(int ax, int ay, int bx, int by) {
    int dx = ax - bx, dy = ay - by;
    if(dx < 0) dx = -dx;
    if(dy < 0) dy = -dy;
    return dx > dy ? dx : dy;
}

static uint8_t effect_of(const Creature* c) {
    const Trait* t = creature_trait(c->trait_id);
    return (c->family_id == FAMILY_DEAD && t) ? t->effect : TE_NONE;
}

void afflict_area(const Creature* cs, int n, int px, int py, AreaFelt* out) {
    memset(out, 0, sizeof(*out));
    for(int i = 0; i < n; i++) {
        if(!cs[i].alive || cheb(cs[i].x, cs[i].y, px, py) > AREA_RADIUS) continue;
        switch(effect_of(&cs[i])) {
        case TE_WITHER: out->wither = true; break;
        case TE_CHILL:  out->chill = true; break;
        case TE_ROT:    out->rot = true; break;
        default: break;
        }
    }
}

int afflict_foe_bonus(const Creature* cs, int n, int foe, int px, int py, uint16_t hp, uint16_t max_hp) {
    if(foe < 0 || foe >= n) return 0;
    uint8_t e = effect_of(&cs[foe]);
    int bonus = 0;
    if(e == TE_FLANK)
        for(int i = 0; i < n; i++)
            if(i != foe && cs[i].alive && cs[i].family_id == FAMILY_DEAD &&
               cs[i].trait_id == cs[foe].trait_id && cheb(cs[i].x, cs[i].y, px, py) <= 1)
                bonus += HORDE_FLANK_ATK;
    if(e == TE_FEED && (uint32_t)hp * 2 < max_hp) bonus += FEED_ATK;
    return bonus;
}

void afflict_foe_hit(uint8_t trait, CharacterState* c, uint16_t* foe_hp, uint16_t foe_max) {
    const Trait* t = creature_trait(trait);
    if(!t) return;
    if(t->effect == TE_BLEED) {
        int b = c->bleed + BLEED_TURNS;
        c->bleed = (uint8_t)(b > 255 ? 255 : b);
    }
    if(t->effect == TE_FEED && *foe_hp < foe_max) *foe_hp = (uint16_t)(*foe_hp + FEED_HEAL);
}

void foul_clear(FoulField* f) { f->n = 0; }

void foul_add(FoulField* f, int x, int y, uint32_t turn) {
    if(f->n >= FOUL_MAX) {
        memmove(&f->p[0], &f->p[1], sizeof(f->p[0]) * (FOUL_MAX - 1));
        f->n--;
    }
    f->p[f->n].x = (int8_t)x;
    f->p[f->n].y = (int8_t)y;
    f->p[f->n].until = turn + FOUL_TURNS;
    f->n++;
}

bool foul_at(const FoulField* f, int x, int y, uint32_t turn) {
    for(int i = 0; i < f->n; i++)
        if(turn < f->p[i].until && cheb(f->p[i].x, f->p[i].y, x, y) <= 1) return true;
    return false;
}

int foul_step(FoulField* f, int x, int y, uint32_t turn) {
    int k = 0;
    for(int i = 0; i < f->n; i++)
        if(turn < f->p[i].until) f->p[k++] = f->p[i];
    f->n = (uint8_t)k;
    return foul_at(f, x, y, turn) ? FOUL_DAMAGE : 0;
}

void afflict_foe_died(uint8_t trait, int x, int y, uint32_t turn, FoulField* f) {
    const Trait* t = creature_trait(trait);
    if(t && t->effect == TE_FOUL) foul_add(f, x, y, turn);
}

int afflict_bleed_tick(CharacterState* c) {
    if(c->bleed == 0) return 0;
    c->bleed--;
    if(c->hp > 0) c->hp--;
    return 1;
}

uint8_t afflict_spoils_into(uint8_t kind) {
    if(kind == AF_KIND_FUNGUS) return AF_KIND_ROTCAP;
    if(kind == AF_KIND_VIAL) return AF_KIND_SOURVIAL;
    return 0xFFu;
}

uint8_t afflict_rot(uint32_t seed, int cx, int cy, uint32_t turn, CharacterState* c) {
    uint32_t h = region_hash(seed ^ ROT_SALT ^ (turn * 0x9E3779B9u), cx, cy);
    if(h % ROT_ODDS != 0) return 0xFFu;
    uint8_t first = (h >> 8) & 1u ? AF_KIND_VIAL : AF_KIND_FUNGUS;
    uint8_t second = first == AF_KIND_VIAL ? AF_KIND_FUNGUS : AF_KIND_VIAL;
    uint8_t pick = c->inv_qty[first] ? first : c->inv_qty[second] ? second : 0xFFu;
    if(pick == 0xFFu) return 0xFFu;
    uint8_t into = afflict_spoils_into(pick);
    if(c->inv_qty[into] == 255) return 0xFFu;
    c->inv_qty[pick]--;
    c->inv_qty[into]++;
    return pick;
}

bool afflict_carries_corrupted(const CharacterState* c) {
    for(int i = 0; i < KIND_COUNT && i < SAVE_INV_KINDS_MAX; i++)
        if(c->inv_qty[i] && (KIND_CATALOG[i].flags & KF_CORRUPTED)) return true;
    return false;
}

int afflict_experiment(CharacterState* c) {
    for(int i = 0; i < RECIPE_COUNT; i++) {
        const RecipeDef* r = recipe_def((uint8_t)i);
        if(r->cls != RC_DESTRUCTIVE || recipe_known((uint8_t)i, c->recipes_known)) continue;
        if(!recipe_craftable(r, c->inv_qty, SAVE_INV_KINDS_MAX)) continue;
        c->recipes_known |= RECIPE_BIT(i);
        return i;
    }
    return -1;
}

int afflict_read(char glyph, uint32_t seed, int cx, int cy, int x, int y, CharacterState* c) {
    int id = -1;
    if(glyph == '}') {   /* a book: one of the roots */
        uint32_t h = region_hash(seed ^ READ_SALT ^ (uint32_t)(x * 31 + y), cx, cy);
        id = (h & 1u) ? AF_RECIPE_DRAUGHT : AF_RECIPE_TINCTURE;
    } else if(glyph == '{') {   /* a tome: the branch */
        id = AF_RECIPE_BLIGHT;
    }
    if(id < 0 || recipe_known((uint8_t)id, c->recipes_known)) return -1;
    c->recipes_known |= RECIPE_BIT(id);
    return id;
}

uint8_t afflict_throwable(const CharacterState* c) {
    if(c->inv_qty[AF_KIND_TINCTURE] && recipe_known(AF_RECIPE_TINCTURE, c->recipes_known))
        return AF_KIND_TINCTURE;
    if(c->inv_qty[AF_KIND_BLIGHT] && recipe_known(AF_RECIPE_BLIGHT, c->recipes_known))
        return AF_KIND_BLIGHT;
    return 0xFFu;
}
