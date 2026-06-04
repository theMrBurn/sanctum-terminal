/*
 * creatures.c — see creatures.h.
 *
 * v0.4.0a data foundation: the Family × Trait composition tables + the
 * deterministic biome-weighted rolls. Stats are the kind_config
 * combat_profile spirit (bat fast/fragile, slime slow/tanky), retuned from
 * metres to the Flipper's Chebyshev tile grid. Element float mods become
 * x4 fixed-point at use time (Tier-2 combat), not here.
 */

#include "creatures.h"
#include "pool.h"

#include <stddef.h>
#include <stdio.h> /* snprintf — provided on host and by the firmware */

#include "loot.h" /* loot_is_item_glyph — keep placement off loot tiles */

#define B_CAVE BIOME_BIT(BIOME_CAVERN)
#define B_OUT  BIOME_BIT(BIOME_OUTDOOR)
#define B_BOTH (B_CAVE | B_OUT)

/* Families — body plans.
 * glyph root      hp atk def spd  move_flags                            disposition       not flee prov scan apt            biomes  wt */
const Family CREATURE_FAMILIES[] = {
    { 'r', "rat",    3, 4, 10, 14, CF_PACK,                              DISP_SKITTISH,     5,  3,  6, 15, APT_SCAVENGE,   B_BOTH, 30 },
    { 'b', "beetle", 5, 3, 14,  8, 0,                                    DISP_PASSIVE,      3,  1, 10, 12, APT_FORTITUDE,  B_BOTH, 22 },
    { 's', "spider", 4, 6, 12, 12, 0,                                    DISP_TERRITORIAL,  4,  2,  3, 30, APT_PATIENCE,   B_CAVE, 16 },
    { 'B', "bat",    2, 3, 14, 20, CF_FLIGHT | CF_PACK | CF_PHOTOPHILIC, DISP_TERRITORIAL,  6,  0,  8, 25, APT_PERCEPTION, B_BOTH, 18 },
    { 'S', "slime",  6, 4,  8,  6, 0,                                    DISP_PASSIVE,      2,  0, 12, 18, APT_RESILIENCE, B_CAVE, 14 },
};
const int CREATURE_FAMILY_COUNT =
    (int)(sizeof(CREATURE_FAMILIES) / sizeof(CREATURE_FAMILIES[0]));

/* Traits — biome-locked adaptations. Index 0 = "plain" (no change), weighted
 * to dominate so most creatures spawn unmodified.
 * affix      hp atk def spd  element    add_flags         dflee apt_mod        biome   wt */
const Trait CREATURE_TRAITS[] = {
    { "",        0, 0,  0,  0, ELEM_NONE, 0,                   0, APT_NONE,      B_BOTH, 50 },
    { "frost-",  1, 0,  2, -1, ELEM_ICE,  CF_PHOTOPHOBIC,      0, APT_FROST,     B_CAVE, 10 },
    { "pallid-", 0, 0, -1,  0, ELEM_NONE, CF_PHOTOPHOBIC,      1, APT_NONE,      B_CAVE,  9 },
    { "cave-",   1, 0,  1,  0, ELEM_NONE, 0,                   0, APT_NONE,      B_CAVE,  8 },
    { "ember-",  0, 2,  0,  1, ELEM_FIRE, 0,                   0, APT_EMBER,     B_OUT,  10 },
    { "swift-",  0, 0,  0,  4, ELEM_NONE, 0,                  -1, APT_NONE,      B_OUT,   9 },
    { "hardy-",  2, 0,  2, -1, ELEM_NONE, 0,                   0, APT_FORTITUDE, B_OUT,   8 },
    { "dire-",   3, 3,  1,  0, ELEM_NONE, 0,                   0, APT_NONE,      B_BOTH,  4 },
};
const int CREATURE_TRAIT_COUNT =
    (int)(sizeof(CREATURE_TRAITS) / sizeof(CREATURE_TRAITS[0]));

const Family* creature_family(uint8_t id) {
    if(id >= (uint8_t)CREATURE_FAMILY_COUNT) return NULL;
    return &CREATURE_FAMILIES[id];
}

const Trait* creature_trait(uint8_t id) {
    if(id >= (uint8_t)CREATURE_TRAIT_COUNT) return NULL;
    return &CREATURE_TRAITS[id];
}

static uint8_t clamp_u8(int v, int lo, int hi) {
    if(v < lo) v = lo;
    if(v > hi) v = hi;
    return (uint8_t)v;
}

static int8_t clamp_i8(int v, int lo, int hi) {
    if(v < lo) v = lo;
    if(v > hi) v = hi;
    return (int8_t)v;
}

void creature_compose(uint8_t family_id, uint8_t trait_id, CreatureDef* out) {
    const Family* f = creature_family(family_id);
    const Trait* t = creature_trait(trait_id);
    if(!out) return;
    if(!f) f = &CREATURE_FAMILIES[0];
    if(!t) t = &CREATURE_TRAITS[0]; /* plain */

    out->family_id = (uint8_t)(f - CREATURE_FAMILIES);
    out->trait_id = (uint8_t)(t - CREATURE_TRAITS);
    out->glyph = f->glyph;

    {
        int hp = (int)f->base_hp + t->d_hp;
        out->hp = (uint16_t)(hp < 1 ? 1 : hp);
    }
    out->atk = clamp_u8((int)f->base_atk + t->d_atk, 0, 255);
    out->def = clamp_u8((int)f->base_def + t->d_def, 0, 255);
    out->speed = clamp_u8((int)f->base_speed + t->d_speed, 1, 63);
    out->element = t->element;
    out->flags = (uint8_t)(f->move_flags | t->add_flags);
    out->disposition = f->disposition;
    out->notice = f->notice;
    out->flee = clamp_i8((int)f->flee + t->d_flee, -16, 31);
    out->provoke = f->provoke;
    out->scan_diff = f->scan_diff;
    out->aptitude = f->aptitude;
    out->aptitude_trait = t->aptitude_mod;
}

uint8_t creature_family_roll(Rng* r, Biome biome) {
    return creature_family_roll_pooled(r, biome, NULL);
}

/* Slice 50.F2 — Pool-biased family roll. Engine addendum §F1.4.a formula. */
uint8_t creature_family_roll_pooled(
    Rng* r, Biome biome, const Pool* pool) {
    uint8_t bbit = BIOME_BIT(biome);
    uint32_t total = 0;
    uint32_t weights[CREATURE_FAMILY_COUNT];
    for(int i = 0; i < CREATURE_FAMILY_COUNT; i++) {
        weights[i] = 0;
        if(!(CREATURE_FAMILIES[i].biomes & bbit)) continue;
        uint32_t base = CREATURE_FAMILIES[i].weight;
        if(pool && i < POOL_FAMILIES) {
            uint32_t bias = pool->family_bias[i];
            if(bias > 56u) bias = 56u;
            base = base * (8u + bias) / 8u;
        }
        weights[i] = base;
        total += base;
    }
    if(total == 0) return 0;
    uint32_t pick = rng_range(r, 0, total);
    uint32_t acc = 0;
    for(int i = 0; i < CREATURE_FAMILY_COUNT; i++) {
        if(weights[i] == 0) continue;
        acc += weights[i];
        if(pick < acc) return (uint8_t)i;
    }
    return 0;
}

void creature_roll_pooled(
    Rng* r, Biome biome, const Pool* pool,
    uint8_t* out_family, uint8_t* out_trait) {
    uint8_t fam = creature_family_roll_pooled(r, biome, pool);
    uint8_t tr  = creature_trait_roll(r, biome); /* trait stays un-biased in v1 */
    if(out_family) *out_family = fam;
    if(out_trait)  *out_trait  = tr;
}

uint8_t creature_trait_roll(Rng* r, Biome biome) {
    uint8_t bbit = BIOME_BIT(biome);
    uint32_t total = 0;
    for(int i = 0; i < CREATURE_TRAIT_COUNT; i++) {
        if(CREATURE_TRAITS[i].biome_mask & bbit) total += CREATURE_TRAITS[i].weight;
    }
    if(total == 0) return 0;
    uint32_t pick = rng_range(r, 0, total);
    uint32_t acc = 0;
    for(int i = 0; i < CREATURE_TRAIT_COUNT; i++) {
        if(!(CREATURE_TRAITS[i].biome_mask & bbit)) continue;
        acc += CREATURE_TRAITS[i].weight;
        if(pick < acc) return (uint8_t)i;
    }
    return 0;
}

void creature_roll(Rng* r, Biome biome, uint8_t* out_family, uint8_t* out_trait) {
    uint8_t fam = creature_family_roll(r, biome);
    uint8_t tr = creature_trait_roll(r, biome);
    if(out_family) *out_family = fam;
    if(out_trait) *out_trait = tr;
}

void creature_name(const CreatureDef* d, char* buf, int buflen) {
    if(!buf || buflen <= 0) return;
    const Family* f = creature_family(d->family_id);
    const Trait* t = creature_trait(d->trait_id);
    const char* root = f ? f->root : "thing";
    const char* affix = t ? t->affix : "";
    snprintf(buf, (size_t)buflen, "%s%s", affix, root);
}

/* ── live creature spawning (v0.4.0b) ───────────────────────────────── */

/* Keep creature placement off the world-gen rng stream so adding creatures
 * never perturbs the world golden-master fingerprints. */
#define CREATURE_PLACE_SALT 0x9E3779B9u
#define CREATURES_MIN       2
#define CREATURES_MAX_ROLL  6 /* exclusive — count rolls in [MIN, MAX_ROLL) */
#define CREATURES_ATTEMPTS  48

int creatures_populate(
    uint32_t chunk_seed, Biome biome, const World* world, int player_x,
    int player_y, Creature* out, int max) {
    return creatures_populate_pooled(
        chunk_seed, biome, world, player_x, player_y, NULL, out, max);
}

int creatures_populate_pooled(
    uint32_t chunk_seed, Biome biome, const World* world, int player_x,
    int player_y, const Pool* pool, Creature* out, int max) {
    if(!out || max <= 0 || !world) return 0;
    Rng r;
    rng_seed(&r, chunk_seed ^ CREATURE_PLACE_SALT);
    int want = (int)rng_range(&r, CREATURES_MIN, CREATURES_MAX_ROLL);
    if(want > max) want = max;

    int placed = 0, attempts = 0;
    while(placed < want && attempts < CREATURES_ATTEMPTS) {
        attempts++;
        int x = (int)rng_range(&r, 0, WORLD_COLS);
        int y = (int)rng_range(&r, 0, WORLD_ROWS);
        if(!world_walkable(world, x, y)) continue;
        if(x == world->spawn_x && y == world->spawn_y) continue; /* not on chunk spawn */
        if(x == player_x && y == player_y) continue;             /* not on the player */
        if(loot_is_item_glyph(world->tiles[y][x])) continue;     /* keep loot legible */
        int occupied = 0;
        for(int i = 0; i < placed; i++) {
            if(out[i].x == (uint8_t)x && out[i].y == (uint8_t)y) {
                occupied = 1;
                break;
            }
        }
        if(occupied) continue;

        uint8_t fam = 0, tr = 0;
        creature_roll_pooled(&r, biome, pool, &fam, &tr); /* slice 50.F2 */
        out[placed].family_id = fam;
        out[placed].trait_id = tr;
        out[placed].x = (uint8_t)x;
        out[placed].y = (uint8_t)y;
        out[placed].spawn_x = (uint8_t)x; /* the deterministic kill-key */
        out[placed].spawn_y = (uint8_t)y;
        out[placed].state = CR_IDLE;
        out[placed].energy = 0;
        out[placed].aggro = 0;
        out[placed].alive = 1;
        placed++;
    }
    return placed;
}

void creatures_mark_dead_at_spawn(
    Creature* cs, int n, uint8_t spawn_x, uint8_t spawn_y) {
    if(!cs) return;
    for(int i = 0; i < n; i++) {
        if(cs[i].spawn_x == spawn_x && cs[i].spawn_y == spawn_y) {
            cs[i].alive = 0;
            return;
        }
    }
}

/* ── overworld movement tick (v0.4.0c) ──────────────────────────────── */

#define ENERGY_THRESHOLD 12 /* action point cost of one step */
#define CREATURE_MAX_ACT 2  /* cap steps/turn so a fast creature can't bolt */
#define PACK_ALERT_RADIUS 3 /* a hostile pack member rouses kin within this */

static int sgn(int v) {
    return (v > 0) - (v < 0);
}

/* Can this creature occupy (x,y)? Walkable for all; flight also clears
 * outdoor rock obstacles (never solid cavern walls). */
static int creature_can_enter(const CreatureDef* d, const World* world, int x, int y) {
    if(x < 0 || x >= WORLD_COLS || y < 0 || y >= WORLD_ROWS) return 0;
    if(world_walkable(world, x, y)) return 1;
    if((d->flags & CF_FLIGHT) && world->tiles[y][x] == TILE_ROCK) return 1;
    return 0;
}

static int tile_taken(const Creature* cs, int n, int self, int x, int y) {
    for(int i = 0; i < n; i++) {
        if(i == self) continue;
        if(cs[i].alive && cs[i].x == (uint8_t)x && cs[i].y == (uint8_t)y) return 1;
    }
    return 0;
}

/* Decide one creature's FSM state + take a single step. */
static void creature_act(
    Creature* cs, int n, int self, const CreatureDef* d, const World* world,
    int px, int py, int torch_radius, uint32_t chunk_seed, uint32_t turn, int act,
    const Weather* weather) {
    Creature* c = &cs[self];
    int ddx = px - (int)c->x, ddy = py - (int)c->y;
    int adx = ddx < 0 ? -ddx : ddx;
    int ady = ddy < 0 ? -ddy : ddy;
    int dist = adx > ady ? adx : ady; /* Chebyshev */
    int aware = (dist <= torch_radius); /* lit = within the awareness zone */
    int dark = (torch_radius <= 1);     /* torch nearly out → emboldening (§5.5) */

    /* Weather-modified CreatureDef. Shadow `d` with the local copy so every
     * downstream `d->...` reference reads the modified values automatically.
     * Determinism: the weather pedigree is the same for everyone in this
     * chunk this turn, so the modifications are uniform across slots. */
    CreatureDef d_local = *d;
    if(weather) {
        /* STORM / DUST_STORM grounds flyers — the wind tears them down.
         * Creature loses CF_FLIGHT for this turn; creature_can_enter then
         * refuses TILE_ROCK like a non-flyer would. */
        if(weather->kind == WEATHER_STORM || weather->kind == WEATHER_DUST_STORM) {
            d_local.flags = (uint8_t)(d_local.flags & ~CF_FLIGHT);
        }
        /* FOG extends stealth-affinity notice by 1: spiders + bats stalk
         * the player 1 tile further into mist. The reciprocal cap on the
         * player's lit pool already lives in weather_apply_fov. */
        if(weather->kind == WEATHER_FOG && (d_local.glyph == 's' || d_local.glyph == 'B')) {
            if(d_local.notice < 255) d_local.notice = (uint8_t)(d_local.notice + 1);
        }
    }
    d = &d_local;

    /* Aggression (spec §4.8): rises while you crowd it — more in the dark,
     * more inside its flight bubble — and decays when you leave its awareness.
     * A non-hostile creature driven past `provoke` turns hostile and drifts
     * back as aggro decays. (Chunk-exit reset is free — RAM regen.) */
    int heat_dampen = (weather && weather->kind == WEATHER_HEAT) ? 1 : 0;
    int fire_pacify =
        (weather && weather->kind == WEATHER_RAIN && d->element == ELEM_FIRE) ? 1 : 0;
    if(aware && dist <= d->notice) {
        int rise = 1 + (dark ? 1 : 0) + ((d->flee > 0 && dist <= d->flee) ? 1 : 0);
        rise -= heat_dampen; /* HEAT lethargy — the air saps will */
        if(rise < 0) rise = 0;
        int cap = (d->provoke > 0) ? (int)d->provoke + 8 : 255;
        int a = (int)c->aggro + rise;
        c->aggro = (uint8_t)(a > cap ? cap : a); /* bounded so it drifts back, §4.8 */
    } else if(c->aggro > 0) {
        int decay = 2 + (fire_pacify ? 2 : 0); /* RAIN doubles decay for fire creatures */
        int a = (int)c->aggro - decay;
        c->aggro = (uint8_t)(a < 0 ? 0 : a);
    }
    uint8_t eff = d->disposition;
    if(d->provoke > 0 && c->aggro >= d->provoke) eff = DISP_HOSTILE;

    if(dist <= 1) {
        c->state = CR_ENGAGE;
    } else if(aware) {
        if(eff == DISP_HOSTILE)
            c->state = CR_APPROACH;
        else if(eff == DISP_TERRITORIAL && dist <= d->notice)
            c->state = CR_APPROACH; /* territorial closes — it does NOT flee */
        else if(d->flee > 0 && dist <= d->flee)
            c->state = CR_FLEE; /* skittish: bolt within flee radius */
        else if(d->flee < 0)
            c->state = CR_APPROACH; /* approacher (e.g. bat drawn to light) */
        else
            c->state = CR_IDLE;
    } else {
        c->state = CR_IDLE;
    }

    int sx = 0, sy = 0;
    if(c->state == CR_APPROACH) {
        sx = sgn(ddx);
        sy = sgn(ddy);
    } else if(c->state == CR_FLEE) {
        sx = -sgn(ddx);
        sy = -sgn(ddy);
    } else if(c->state == CR_IDLE) {
        /* wander — deterministic per (chunk_seed, turn, slot); ~50% hold */
        Rng wr;
        rng_seed(
            &wr,
            chunk_seed ^ (turn * 2654435761u) ^ ((uint32_t)self * 40503u + 1u) ^
                ((uint32_t)act * 0x85EBCA77u));
        if(rng_range(&wr, 0, 2) == 0) return;
        sx = (int)rng_range(&wr, 0, 3) - 1;
        sy = (int)rng_range(&wr, 0, 3) - 1;
    } else {
        return; /* CR_ENGAGE: hold adjacent (combat is Tier-2) */
    }
    if(sx == 0 && sy == 0) return;

    /* greedy: diagonal first, then the two cardinals; first legal wins */
    int ox[3] = {sx, sx, 0};
    int oy[3] = {sy, 0, sy};
    for(int k = 0; k < 3; k++) {
        if(ox[k] == 0 && oy[k] == 0) continue;
        int nx = (int)c->x + ox[k];
        int ny = (int)c->y + oy[k];
        if(nx == px && ny == py) continue; /* never step onto the player */
        if(!creature_can_enter(d, world, nx, ny)) continue;
        if(tile_taken(cs, n, self, nx, ny)) continue;
        c->x = (uint8_t)nx;
        c->y = (uint8_t)ny;
        return;
    }
    /* Cornered: it wanted to flee but no legal away-step exists — fear curdles
     * into aggression (over a couple turns it turns and fights). */
    if(c->state == CR_FLEE) {
        int cap = (d->provoke > 0) ? (int)d->provoke + 8 : 255;
        int a = (int)c->aggro + 4;
        c->aggro = (uint8_t)(a > cap ? cap : a);
    }
}

int creature_is_hostile(uint8_t disposition, uint8_t provoke, uint8_t aggro) {
    return disposition == DISP_HOSTILE || (provoke > 0 && aggro >= provoke);
}

int creatures_tick(
    Creature* cs, int n, const World* world, int px, int py, int torch_radius,
    uint32_t chunk_seed, uint32_t turn, const Weather* weather) {
    if(!cs || !world) return 0;
    for(int i = 0; i < n; i++) {
        if(!cs[i].alive) continue;
        CreatureDef d;
        creature_compose(cs[i].family_id, cs[i].trait_id, &d);
        int e = (int)cs[i].energy + (int)d.speed;
        int act = 0;
        while(e >= ENERGY_THRESHOLD && act < CREATURE_MAX_ACT) {
            e -= ENERGY_THRESHOLD;
            creature_act(cs, n, i, &d, world, px, py, torch_radius, chunk_seed, turn, act,
                         weather);
            act++;
        }
        cs[i].energy = (uint8_t)(e < 0 ? 0 : (e > 255 ? 255 : e));
    }

    /* Pack threat (spec §4.8): a hostile pack member rouses nearby kin — hurt
     * one rat and the scatter turns. Cheap O(n^2); n is tiny. */
    for(int i = 0; i < n; i++) {
        if(!cs[i].alive) continue;
        CreatureDef di;
        creature_compose(cs[i].family_id, cs[i].trait_id, &di);
        if(!(di.flags & CF_PACK)) continue;
        if(!creature_is_hostile(di.disposition, di.provoke, cs[i].aggro)) continue;
        for(int j = 0; j < n; j++) {
            if(j == i || !cs[j].alive) continue;
            if(cs[j].family_id != cs[i].family_id) continue; /* same kind */
            int ddx = (int)cs[i].x - (int)cs[j].x, ddy = (int)cs[i].y - (int)cs[j].y;
            int adx = ddx < 0 ? -ddx : ddx;
            int ady = ddy < 0 ? -ddy : ddy;
            if((adx > ady ? adx : ady) > PACK_ALERT_RADIUS) continue;
            if(cs[j].aggro < 254) cs[j].aggro++;
        }
    }

    /* Contact cost: hostile creatures now adjacent to the player (innately
     * hostile or provoked past threshold). The caller applies the fuel
     * "flicker" — combat-as-torch-loss preview (spec §4.7). */
    int contacts = 0;
    for(int i = 0; i < n; i++) {
        if(!cs[i].alive) continue;
        int ddx = px - (int)cs[i].x, ddy = py - (int)cs[i].y;
        int adx = ddx < 0 ? -ddx : ddx;
        int ady = ddy < 0 ? -ddy : ddy;
        if((adx > ady ? adx : ady) > 1) continue;
        CreatureDef d;
        creature_compose(cs[i].family_id, cs[i].trait_id, &d);
        if(creature_is_hostile(d.disposition, d.provoke, cs[i].aggro)) contacts++;
    }
    return contacts;
}

/* ── scan / bestiary (v0.4.0d) ──────────────────────────────────────── */

int creature_scan_tier(uint8_t observe, uint8_t scan_diff) {
    if((int)observe >= (int)scan_diff + 15) return 3;
    if(observe >= scan_diff) return 2;
    return 1;
}

int creature_scan_cost(uint8_t scan_diff) {
    return 1 + (int)scan_diff / 12; /* rat 15→2, bat 25→3, spider 30→3 */
}

int creature_bestiary_grade(uint16_t bestiary, uint8_t family_id) {
    if(family_id >= 8) return 0;
    return (bestiary >> (family_id * 2)) & 0x3;
}

uint16_t creature_bestiary_set(uint16_t bestiary, uint8_t family_id, uint8_t grade) {
    if(family_id >= 8) return bestiary;
    if(grade > 3) grade = 3;
    uint16_t mask = (uint16_t)(0x3u << (family_id * 2));
    return (uint16_t)((bestiary & ~mask) | ((uint16_t)grade << (family_id * 2)));
}

const char* creature_disposition_name(uint8_t disposition) {
    switch(disposition) {
    case DISP_PASSIVE: return "calm";
    case DISP_SKITTISH: return "shy";
    case DISP_TERRITORIAL: return "terr";
    case DISP_HOSTILE: return "hostile";
    default: return "?";
    }
}

const char* creature_element_name(uint8_t element) {
    switch(element) {
    case ELEM_FIRE: return "fire";
    case ELEM_ICE: return "ice";
    default: return "-";
    }
}

const char* creature_aptitude_name(uint8_t aptitude) {
    switch(aptitude) {
    case APT_SCAVENGE: return "scavenge";
    case APT_FORTITUDE: return "fortitude";
    case APT_PATIENCE: return "patience";
    case APT_PERCEPTION: return "perception";
    case APT_RESILIENCE: return "resilience";
    case APT_FROST: return "frost";
    case APT_EMBER: return "ember";
    default: return "-";
    }
}
