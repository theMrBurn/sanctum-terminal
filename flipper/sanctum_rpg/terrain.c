/* terrain.c — see terrain.h.
 *
 * Props are drawn in a 32-unit design space, floor at y = 31, scaled to
 * the billboard size — the same convention as figure.c. Pipeline per prop:
 *   1. SHAPE  — the plan's primitives fill the mask
 *   2. HIDE   — tighten (pixkit), then ink = outline + the plan's
 *               posterized shading (two tones, hard edge), then despeckle
 *   3. DETAIL — accents drawn after despeckle, so they are never "noise"
 *
 * Adding a prop = one plan function + one TERRAIN row. */
#include "terrain.h"

#include <string.h>

#include "world.h"

/* ── tunables (AGENTS.md: no hardcoded tunables) ───────────────────── */
#define DESIGN             32
#define STONE_LEAN_MAX      2   /* standing stone: design units of lean */
#define STONE_CRACK_Y      13   /* standing stone: first crack row */
#define CAIRN_STONES        4   /* stones in a cairn */
#define BOULDER_TERM       10   /* boulder: shadow below this column depth */
#define SCRUB_TERM          5   /* scrub: leaf shadow below this depth */
#define PROP_LOD_SMALL_PX  16   /* below this: solid silhouette, no accents */
/* Menhir: drawn in a 2x2-tile box, so 16 design units = one tile. */
#define MENHIR_TOP          4   /* crown row: ~1.75 tiles tall, over the walls */
#define MENHIR_HALF_W       4   /* half-width at the crown */
#define MENHIR_FOOT_FLARE   5   /* extra half-width gained down to the foot */
#define MENHIR_CRACK_Y     11   /* first crack row */
#define RUBBLE_STONES       5   /* rocks in a rubble heap */
#define BONE_STROKES        3   /* long bones in a bone pile */
#define URN_TERM           18   /* urn: shadow right of this column */
#define TREE_LOBES          6   /* tree crown: leaf masses */
#define TREE_TRUNK_TOP     21   /* tree: where the trunk meets the crown */
#define TREE_TRUNK_HW       2   /* tree / dead tree: trunk half-width at the foot */
#define DEAD_BRANCHES       5   /* dead tree: branch strokes */
#define STUMP_TOP          23   /* stump: the cut face row */
#define STALAG_TIP          3   /* stalagmite: the tip row */
#define STALAG_BASE_HW      7   /* stalagmite: half-width at the floor */
#define STALAG_TWIN_TIP    18   /* stalagmite: the smaller twin's tip */
#define TABLE_TOP          17   /* table: the top's upper edge */
#define BARREL_HOOP_A      15   /* barrel: hoop rows */
#define BARREL_HOOP_B      27
#define HEARTH_MANTEL       8   /* hearth: mantel row */
#define RACK_SPEARS         3   /* weapon rack: spears */
#define STATUE_PLINTH      27   /* statue: plinth top row */
#define POST_HW             3   /* mine post: half-width */

/* ── plans ─────────────────────────────────────────────────────────── */
enum { PLAN_NONE = 0, PLAN_STANDING, PLAN_CAIRN, PLAN_BOULDER, PLAN_DEADFALL,
       PLAN_SCRUB, PLAN_GLOWCAP, PLAN_MENHIR, PLAN_STALAGMITE,
       PLAN_SARCOPHAGUS, PLAN_BONES, PLAN_URN,          /* crypt */
       PLAN_CART, PLAN_RUBBLE, PLAN_POST,               /* mine */
       PLAN_TREE, PLAN_DEADTREE, PLAN_STUMP,            /* forest */
       PLAN_TABLE, PLAN_BARREL, PLAN_HEARTH,            /* manor */
       PLAN_RACK, PLAN_BRAZIER,                         /* keep */
       PLAN_ALTAR, PLAN_STATUE, PLAN_PEW,               /* abbey */
       PLAN_MOSS = TERRAIN_PLAN_MOSS, PLAN_SCREE = TERRAIN_PLAN_SCREE,
       PLAN_FLAG = TERRAIN_PLAN_FLAG, PLAN_RAILS = TERRAIN_PLAN_RAILS,
       PLAN_GRASS = TERRAIN_PLAN_GRASS, PLAN_PLANKS = TERRAIN_PLAN_PLANKS };

static const TerrainDef TERRAIN[] = {
    /* glyph       form      material       plan              span name            scale  step: fuel, flags, message */
    {TILE_WALL,   TF_SLAB,  TM_STYLE_WALL, PLAN_NONE,        1, NULL,             1, 0, 0, NULL},
    {TILE_SECRET, TF_SLAB,  TM_STYLE_WALL, PLAN_NONE,        1, NULL,             1, 0, 0, NULL},   /* a secret looks like wall */
    {'O',         TF_SLAB,  TM_COLUMN,     PLAN_NONE,        1, "great column",   1, 0, 0, NULL},   /* mega column */
    {'|',         TF_SLAB,  TM_COLUMN,     PLAN_NONE,        1, "column",         1, 0, 0, NULL},
    {'M',         TF_SLAB,  TM_MONOLITH,   PLAN_NONE,        1, "flowstone",      1, 0, 0, NULL},   /* chamber divider */
    {'A',         TF_PROP,  0,             PLAN_STALAGMITE,  1, "stalagmite",     1, 0, 0, NULL},
    {'H',         TF_PROP,  0,             PLAN_MENHIR,      2, "menhir",         2, 0, 0, NULL},   /* one stone on a 2x2 */
    {'I',         TF_PROP,  0,             PLAN_STANDING,    1, "standing stone", 1, 0, 0, NULL},
    {'Q',         TF_PROP,  0,             PLAN_CAIRN,       1, "cairn",          1, 0, 0, NULL},
    {TILE_ROCK,   TF_PROP,  0,             PLAN_BOULDER,     1, "boulder",        1, 0, 0, NULL},
    {'~',         TF_PROP,  0,             PLAN_DEADFALL,    1, "deadfall",       1, 0, 0, NULL},
    {';',         TF_PROP,  0,             PLAN_SCRUB,       1, "scrub",          1, 0, 0, NULL},
    {'q',         TF_PROP,  0,             PLAN_GLOWCAP,     1, "glowcap",        1, 2, TSF_CONSUMED, "glowcap  +2 fuel"},
    {'n',         TF_PROP,  0,             PLAN_SARCOPHAGUS, 1, "sarcophagus",    1, 0, 0, NULL},   /* crypt */
    {'x',         TF_PROP,  0,             PLAN_BONES,       1, "bone pile",      1, 0, 0, NULL},
    {'U',         TF_PROP,  0,             PLAN_URN,         1, "funeral urn",    1, 0, 0, NULL},
    {'c',         TF_PROP,  0,             PLAN_CART,        1, "ore cart",       1, 0, 0, NULL},   /* mine */
    {'^',         TF_PROP,  0,             PLAN_RUBBLE,      1, "rubble",         1, 0, 0, NULL},
    {'l',         TF_PROP,  0,             PLAN_POST,        1, "timber prop",    1, 0, 0, NULL},
    {'Y',         TF_PROP,  0,             PLAN_TREE,        1, "tree",           2, 0, 0, NULL},   /* forest */
    {'y',         TF_PROP,  0,             PLAN_DEADTREE,    1, "dead tree",      2, 0, 0, NULL},
    {'t',         TF_PROP,  0,             PLAN_STUMP,       1, "stump",          1, 0, 0, NULL},
    {'m',         TF_PROP,  0,             PLAN_TABLE,       1, "table",          1, 0, 0, NULL},   /* manor */
    {'d',         TF_PROP,  0,             PLAN_BARREL,      1, "barrel",         1, 0, 0, NULL},
    {'w',         TF_PROP,  0,             PLAN_HEARTH,      1, "hearth",         1, 0, 0, NULL},
    {'k',         TF_PROP,  0,             PLAN_RACK,        1, "weapon rack",    1, 0, 0, NULL},   /* keep */
    {'v',         TF_PROP,  0,             PLAN_BRAZIER,     1, "brazier",        1, 0, 0, NULL},
    {'a',         TF_PROP,  0,             PLAN_ALTAR,       1, "altar",          1, 0, 0, NULL},   /* abbey */
    {'Z',         TF_PROP,  0,             PLAN_STATUE,      1, "statue",         2, 0, 0, NULL},
    {'p',         TF_PROP,  0,             PLAN_PEW,         1, "pew",            1, 0, 0, NULL},
    {',',         TF_FLOOR, 0,             PLAN_MOSS,        1, "moss",           1, 0, 0, NULL},
    {':',         TF_FLOOR, 0,             PLAN_SCREE,       1, "scree",          1, -1, 0, "loose footing"},
    {'_',         TF_FLOOR, 0,             PLAN_FLAG,        1, "cracked flags",  1, 0, 0, NULL},
    {'-',         TF_FLOOR, 0,             PLAN_RAILS,       1, "rails",          1, 0, 0, NULL},
    {'"',         TF_FLOOR, 0,             PLAN_GRASS,       1, "tall grass",     1, 0, 0, NULL},
    {'\'',        TF_FLOOR, 0,             PLAN_PLANKS,      1, "boards",         1, 0, 0, NULL},
};

int terrain_count(void) { return (int)(sizeof(TERRAIN) / sizeof(TERRAIN[0])); }

const TerrainDef* terrain_at(int i) {
    return (i >= 0 && i < terrain_count()) ? &TERRAIN[i] : NULL;
}

const TerrainDef* terrain_def(char glyph) {
    for(int i = 0; i < terrain_count(); i++)
        if(TERRAIN[i].glyph == glyph) return &TERRAIN[i];
    return NULL;
}

bool terrain_stops_ray(char glyph) {
    const TerrainDef* d = terrain_def(glyph);
    if(d) return d->form == TF_SLAB;
    return world_is_blocking(glyph);
}

bool terrain_step(char glyph, TerrainStep* out) {
    const TerrainDef* d = terrain_def(glyph);
    if(!d || (!d->step_fuel && !d->step_flags && !d->step_msg)) return false;
    out->fuel = d->step_fuel;
    out->consumed = (d->step_flags & TSF_CONSUMED) != 0;
    out->message = d->step_msg;
    return true;
}

uint16_t terrain_step_fuel(uint16_t fuel, int8_t delta, uint16_t max) {
    int f = (int)fuel + delta;
    if(f < 0) f = 0;
    if(f > (int)max) f = (int)max;
    return (uint16_t)f;
}

const char* terrain_name(char glyph, const char* wall_name) {
    const TerrainDef* d = terrain_def(glyph);
    if(!d) return NULL;
    return d->material == TM_STYLE_WALL && d->form == TF_SLAB ? wall_name : d->name;
}

SlabMaterial terrain_material(char glyph) {
    const TerrainDef* d = terrain_def(glyph);
    return (d && d->form == TF_SLAB) ? (SlabMaterial)d->material : TM_STONE;
}

/* ── design space -> plane ─────────────────────────────────────────── */
static int S(int v, int size) { return (v * size) / DESIGN; }
static int R(int r, int size) { int v = (r * size) / DESIGN; return v < 1 ? 1 : v; }

static bool in_ellipse(int x, int y, int cx, int cy, int rx, int ry) {
    long dx = x - cx, dy = y - cy, a2 = (long)rx * rx, b2 = (long)ry * ry;
    return dx * dx * b2 + dy * dy * a2 <= a2 * b2;
}

/* Fill (design-space) ellipse into a plane. */
static void ell(Plane* p, int size, int cx, int cy, int rx, int ry, int v) {
    int px = S(cx, size), py = S(cy, size), ax = R(rx, size), ay = R(ry, size);
    for(int y = py - ay; y <= py + ay; y++)
        for(int x = px - ax; x <= px + ax; x++)
            if(in_ellipse(x, y, px, py, ax, ay)) pset(p, x, y, v);
}

static void seg(Plane* p, int size, int x0, int y0, int x1, int y1, int v) {
    line_px(p, S(x0, size), S(y0, size), S(x1, size), S(y1, size), v);
}

/* ── shapes ────────────────────────────────────────────────────────── */
static int stone_lean(uint8_t var) { return (int)(var % (2 * STONE_LEAN_MAX + 1)) - STONE_LEAN_MAX; }

/* Cairn stones, bottom up: {cx, cy, rx, ry}; odd stones shift with variant. */
static const int8_t CAIRN[CAIRN_STONES][4] = {
    {16, 28, 10, 3}, {15, 23, 8, 3}, {17, 18, 6, 2}, {16, 14, 3, 2}};

/* Rubble rocks: {cx, cy, rx, ry}, back to front. */
static const int8_t RUBBLE[RUBBLE_STONES][4] = {
    {21, 26, 8, 5}, {10, 27, 7, 4}, {15, 22, 5, 4}, {25, 21, 3, 3}, {16, 29, 9, 2}};

/* Tree crown lobes: {cx, cy, rx, ry}. */
/* Front to back: the low lobes overlap the ones behind them. */
static const int8_t TREE_CROWN[TREE_LOBES][4] = {
    {11, 19, 6, 4}, {21, 19, 6, 4}, {16, 15, 8, 5}, {11, 10, 5, 4}, {21, 10, 5, 4}, {16, 5, 5, 4}};

/* Bone pile: long bones across the heap {x0, y0, x1, y1}. */
static const int8_t BONES[BONE_STROKES][4] = {
    {3, 30, 13, 24}, {18, 25, 29, 30}, {6, 26, 26, 27}};

/* Dead tree branches: {x0, y0, x1, y1}, drawn 2 units thick. */
static const int8_t BRANCHES[DEAD_BRANCHES][4] = {
    {16, 16, 7, 7}, {16, 12, 24, 3}, {16, 19, 26, 13}, {7, 7, 5, 2}, {16, 8, 15, 1}};

static void thick_seg(Plane* p, int size, int x0, int y0, int x1, int y1, int v) {
    seg(p, size, x0, y0, x1, y1, v);
    seg(p, size, x0 + 1, y0, x1 + 1, y1, v);
}

static void rect(Plane* p, int size, int x0, int y0, int x1, int y1, int v) {
    for(int y = S(y0, size); y <= S(y1, size); y++)
        for(int x = S(x0, size); x <= S(x1, size); x++) pset(p, x, y, v);
}

/* A tapering trunk from the foot (y 31) up to `top`. */
static void trunk(Plane* m, int size, int top, int hw_foot) {
    for(int y = top; y <= 31; y++) {
        int hw = 1 + ((hw_foot - 1) * (y - top)) / (31 - top);
        rect(m, size, 16 - hw, y, 16 + hw, y, 1);
    }
}

static void shape(int plan, Plane* m, int size, uint8_t var) {
    switch(plan) {
    case PLAN_STANDING: {   /* a tall rough stone, tapering up, leaning */
        int lean = stone_lean(var);
        for(int y = 6; y <= 31; y++) {
            int hw = 4 + (y - 6) / 12;                        /* wider at the foot */
            int cx = 16 + (lean * (31 - y)) / 25;
            for(int x = S(cx - hw, size); x <= S(cx + hw, size); x++) pset(m, x, S(y, size), 1);
        }
        ell(m, size, 16 + lean, 7, 4, 3, 1);                  /* rounded crown */
        break;
    }
    case PLAN_MENHIR: {     /* one great stone: broad, flat-shouldered, leaning */
        int lean = stone_lean(var);
        for(int y = MENHIR_TOP; y <= 31; y++) {
            int hw = MENHIR_HALF_W + (MENHIR_FOOT_FLARE * (y - MENHIR_TOP)) / (31 - MENHIR_TOP);
            int cx = 16 + (lean * (31 - y)) / (31 - MENHIR_TOP);
            for(int x = S(cx - hw, size); x <= S(cx + hw, size); x++) pset(m, x, S(y, size), 1);
        }
        ell(m, size, 16 + lean + (var & 2 ? 1 : -1), MENHIR_TOP + 1, MENHIR_HALF_W, 3, 1);  /* weathered, off-centre crown */
        break;
    }
    case PLAN_STALAGMITE: { /* a pointed spire, a smaller one beside it */
        int side = (var & 1) ? 1 : -1;
        for(int y = STALAG_TIP; y <= 31; y++) {
            int hw = ((y - STALAG_TIP) * STALAG_BASE_HW) / (31 - STALAG_TIP);
            rect(m, size, 15 - hw, y, 15 + hw, y, 1);
        }
        for(int y = STALAG_TWIN_TIP; y <= 31; y++) {
            int hw = ((y - STALAG_TWIN_TIP) * 3) / (31 - STALAG_TWIN_TIP);
            int cx = 15 + side * 9;
            rect(m, size, cx - hw, y, cx + hw, y, 1);
        }
        break;
    }
    case PLAN_TABLE:        /* a board on four legs (two show), a jug on some */
        rect(m, size, 3, TABLE_TOP, 28, TABLE_TOP + 3, 1);
        rect(m, size, 5, TABLE_TOP + 4, 8, 31, 1);
        rect(m, size, 23, TABLE_TOP + 4, 26, 31, 1);
        if(var & 1) { ell(m, size, 10, TABLE_TOP - 4, 3, 4, 1); rect(m, size, 9, TABLE_TOP - 9, 11, TABLE_TOP - 6, 1); }
        break;
    case PLAN_BARREL:       /* staves bulging between narrower ends */
        for(int y = 11; y <= 31; y++) {
            int d = y - 21;
            rect(m, size, 16 - (8 - (d * d) / 33), y, 16 + (8 - (d * d) / 33), y, 1);
        }
        break;
    case PLAN_HEARTH:       /* a stone fireplace under a mantel */
        rect(m, size, 4, HEARTH_MANTEL, 27, 31, 1);
        rect(m, size, 2, HEARTH_MANTEL, 29, HEARTH_MANTEL + 2, 1);
        break;
    case PLAN_RACK:         /* two uprights, a bar, spears standing in it */
        rect(m, size, 5, 9, 7, 31, 1);
        rect(m, size, 24, 9, 26, 31, 1);
        rect(m, size, 5, 11, 26, 13, 1);
        for(int k = 0; k < RACK_SPEARS; k++) {
            int x = 11 + k * 5;
            rect(m, size, x, 4, x + 1, 30, 1);
            ell(m, size, x, 3, 1, 2, 1);                          /* the blade */
        }
        break;
    case PLAN_BRAZIER:      /* a fire bowl on three legs */
        ell(m, size, 16, 9, 4, 5, 1);                             /* flames */
        ell(m, size, 16, 15, 9, 4, 1);                            /* bowl */
        thick_seg(m, size, 10, 17, 7, 31, 1);
        thick_seg(m, size, 21, 17, 24, 31, 1);
        rect(m, size, 15, 18, 16, 31, 1);
        break;
    case PLAN_ALTAR:        /* a stone block, a cloth, two candles */
        rect(m, size, 4, 17, 27, 31, 1);
        rect(m, size, 2, 14, 29, 17, 1);
        rect(m, size, 6, 8, 7, 13, 1);
        rect(m, size, 24, 8, 25, 13, 1);
        break;
    case PLAN_STATUE: {     /* a robed figure on a plinth; two tiles tall */
        rect(m, size, 10, STATUE_PLINTH, 22, 31, 1);
        ell(m, size, 16, 5, 3, 3, 1);                             /* head */
        rect(m, size, 15, 8, 17, 9, 1);                           /* neck */
        ell(m, size, 16, 12, 6, 2, 1);                            /* shoulders */
        for(int y = 12; y < STATUE_PLINTH; y++) {                 /* robe, flaring */
            int hw = y < 18 ? 4 : 4 + ((y - 18) * 4) / (STATUE_PLINTH - 18);
            rect(m, size, 16 - hw, y, 16 + hw, y, 1);
        }
        break;
    }
    case PLAN_PEW:          /* a bench with a back, seen end-on to the aisle */
        rect(m, size, 3, 14, 28, 17, 1);                          /* back rail */
        rect(m, size, 3, 22, 28, 24, 1);                          /* seat */
        rect(m, size, 3, 14, 6, 31, 1);                           /* ends */
        rect(m, size, 25, 14, 28, 31, 1);
        break;
    case PLAN_SARCOPHAGUS:  /* a long lidded stone box */
        rect(m, size, 5, 20, 26, 31, 1);
        rect(m, size, 3, 17, 28, 20, 1);                      /* lid, overhanging */
        if(var & 1) ell(m, size, 16, 17, 6, 2, 1);            /* a carved effigy on the lid */
        break;
    case PLAN_BONES: {      /* a heap of long bones, a skull on top */
        int sx = 13 + (var & 1) * 5;
        ell(m, size, 16, 29, 11, 2, 1);
        for(int k = 0; k < BONE_STROKES; k++)
            thick_seg(m, size, BONES[k][0], BONES[k][1], BONES[k][2], BONES[k][3], 1);
        ell(m, size, sx, 21, 5, 4, 1);                        /* cranium */
        rect(m, size, sx - 3, 24, sx + 3, 26, 1);             /* jaw */
        break;
    }
    case PLAN_URN:
        ell(m, size, 16, 23, 8, 7, 1);                        /* belly */
        rect(m, size, 13, 12, 19, 17, 1);                     /* neck */
        ell(m, size, 16, 12, 5, 1, 1);                        /* lip */
        rect(m, size, 12, 29, 20, 31, 1);                     /* foot */
        break;
    case PLAN_CART:
        for(int y = 17; y <= 26; y++) {                       /* body, wider at the top */
            int hw = 11 - (y - 17) / 4;
            rect(m, size, 16 - hw, y, 16 + hw, y, 1);
        }
        ell(m, size, 16, 16, 9, 3, 1);                        /* heaped ore */
        ell(m, size, 9, 28, 3, 3, 1);                         /* wheels */
        ell(m, size, 23, 28, 3, 3, 1);
        break;
    case PLAN_RUBBLE:
        for(int k = 0; k < RUBBLE_STONES; k++)
            ell(m, size, RUBBLE[k][0] + ((k & 1) ? (var & 1) * 2 - 1 : 0), RUBBLE[k][1],
                RUBBLE[k][2], RUBBLE[k][3], 1);
        break;
    case PLAN_POST:         /* a timber post holding up the roof, with a cap */
        rect(m, size, 16 - POST_HW, 3, 16 + POST_HW, 31, 1);
        rect(m, size, 8, 0, 24, 3, 1);
        break;
    case PLAN_TREE: {       /* a full, lobed crown low on a short trunk; two tiles tall */
        int sh = (var & 1) * 2 - 1;
        trunk(m, size, TREE_TRUNK_TOP, TREE_TRUNK_HW + 1);
        for(int k = 0; k < TREE_LOBES; k++)
            ell(m, size, TREE_CROWN[k][0] + (k & 1) * sh, TREE_CROWN[k][1],
                TREE_CROWN[k][2], TREE_CROWN[k][3], 1);
        break;
    }
    case PLAN_DEADTREE:
        trunk(m, size, 6, TREE_TRUNK_HW + 1);
        for(int k = 0; k < DEAD_BRANCHES; k++) {
            int f = (var & 1) && k != 4 ? 32 - 1 : -1;        /* mirrored variant */
            int x0 = f < 0 ? BRANCHES[k][0] : f - BRANCHES[k][0];
            int x1 = f < 0 ? BRANCHES[k][2] : f - BRANCHES[k][2];
            thick_seg(m, size, x0, BRANCHES[k][1], x1, BRANCHES[k][3], 1);
        }
        break;
    case PLAN_STUMP:        /* a low stump flaring into its roots */
        for(int y = STUMP_TOP; y <= 31; y++) {
            int hw = 6 + ((y - STUMP_TOP) * (y - STUMP_TOP)) / 12;   /* flares at the foot */
            rect(m, size, 16 - hw, y, 16 + hw, y, 1);
        }
        ell(m, size, 16, STUMP_TOP, 6, 2, 1);                 /* cut face */
        break;
    case PLAN_CAIRN:
        for(int k = 0; k < CAIRN_STONES; k++)
            ell(m, size, CAIRN[k][0] + ((k & 1) ? (var & 1) * 2 - 1 : 0), CAIRN[k][1],
                CAIRN[k][2], CAIRN[k][3], 1);
        break;
    case PLAN_BOULDER:
        ell(m, size, 15, 24, 12, 7, 1);
        if(var & 1) ell(m, size, 26, 28, 5, 3, 1);            /* a fallen piece */
        break;
    case PLAN_DEADFALL:
        ell(m, size, 16, 28, 15, 3, 1);                       /* lower log */
        for(int k = -1; k <= 1; k++)                          /* upper log, crossing */
            seg(m, size, 4, 24 + k + (var & 1) * 2, 27, 20 + k, 1);
        break;
    case PLAN_SCRUB:
        ell(m, size, 10, 28, 5, 3, 1);
        ell(m, size, 17, 26, 6, 5, 1);
        ell(m, size, 24, 28, 5, 3, 1);
        break;
    case PLAN_GLOWCAP:
        ell(m, size, 15, 25, 6, 3, 1);                        /* cap */
        for(int y = 27; y <= 31; y++) pset(m, S(15, size), S(y, size), 1);   /* stem */
        if(var & 1) { ell(m, size, 23, 28, 3, 2, 1); pset(m, S(23, size), S(31, size), 1); }
        break;
    default: break;
    }
}

/* Posterized shading inside the outline: true = ink. */
static bool shade(int plan, const Plane* m, int x, int y, int size, uint8_t var) {
    int v = column_v(m, x, y);
    switch(plan) {
    case PLAN_STANDING:                  /* lit face left, shadow face right */
    case PLAN_MENHIR:
        return x > S(16 + stone_lean(var), size);
    case PLAN_CAIRN: {                   /* each stone: clear top, dark under-crescent */
        int lift = R(1, size);
        for(int k = 0; k < CAIRN_STONES; k++) {
            int cx = S(CAIRN[k][0] + ((k & 1) ? (var & 1) * 2 - 1 : 0), size);
            int cy = S(CAIRN[k][1], size), rx = R(CAIRN[k][2], size), ry = R(CAIRN[k][3], size);
            if(in_ellipse(x, y, cx, cy, rx, ry))
                return !in_ellipse(x, y + lift, cx, cy, rx, ry);
        }
        return false;
    }
    case PLAN_BOULDER:  return v > BOULDER_TERM;
    case PLAN_STALAGMITE: return x > S(15, size);            /* lit left, shadow right */
    case PLAN_TABLE:    return y > S(TABLE_TOP + 3, size) && x > S(16, size) ? true
                               : y == S(TABLE_TOP + 3, size);  /* the board's edge, legs in shade */
    case PLAN_BARREL:   return x > S(19, size);
    case PLAN_HEARTH: {                  /* dark firebox, a lit flame in it */
        bool box = x > S(9, size) && x < S(22, size) && y > S(HEARTH_MANTEL + 6, size);
        bool flame = in_ellipse(x, y, S(16, size), S(27, size), R(4, size), R(4, size));
        return box && !flame;
    }
    case PLAN_RACK:     return y > S(13, size) && (x < S(8, size) || x > S(23, size));
    case PLAN_BRAZIER:  return y > S(13, size);                /* bowl + legs dark, flames lit */
    case PLAN_ALTAR:                     /* lit top and face, the side in shadow */
        return y > S(17, size) && x > S(22, size);
    case PLAN_STATUE:   return x > S(16, size);
    case PLAN_PEW:      return x < S(7, size) || x > S(24, size);
    case PLAN_SARCOPHAGUS:               /* lid lit, the box's face in shadow below the lid */
        return y > S(21, size);
    case PLAN_BONES:    return y > S(29, size);              /* pale bone; a shadow under the heap */
    case PLAN_URN:      return x > S(URN_TERM, size);
    case PLAN_CART:                      /* dark ore heap + iron wheels, light planks */
        return y < S(17, size) || y > S(26, size);
    case PLAN_RUBBLE: {                  /* each rock: lit top-left face, dark below its middle */
        for(int k = RUBBLE_STONES - 1; k >= 0; k--) {
            int cx = S(RUBBLE[k][0] + ((k & 1) ? (var & 1) * 2 - 1 : 0), size);
            int cy = S(RUBBLE[k][1], size), rx = R(RUBBLE[k][2], size), ry = R(RUBBLE[k][3], size);
            if(in_ellipse(x, y, cx, cy, rx, ry)) return y >= cy || x > cx + rx / 2;
        }
        return false;
    }
    case PLAN_POST:     return x > S(16, size);              /* lit face left */
    case PLAN_TREE: {                    /* a dark leaf mass; each clump lit top-left */
        int sh = (var & 1) * 2 - 1;
        for(int k = 0; k < TREE_LOBES; k++) {
            int cx = S(TREE_CROWN[k][0] + (k & 1) * sh, size), cy = S(TREE_CROWN[k][1], size);
            int rx = R(TREE_CROWN[k][2], size), ry = R(TREE_CROWN[k][3], size);
            if(in_ellipse(x, y, cx, cy, rx, ry))
                return !(y < cy && x < cx + rx / 3);
        }
        return x > S(16, size);          /* the trunk: shadow side */
    }
    case PLAN_DEADTREE: return x > S(16, size);
    case PLAN_STUMP:                     /* cut face light, bark dark on the shadow side */
        return y > S(STUMP_TOP + 1, size) && x > S(18, size);
    case PLAN_DEADFALL:                  /* dark bark, one rim-light line under the top edge */
        return pget(m, x, y - 2) || !pget(m, x, y - 1);
    case PLAN_SCRUB:    return v > SCRUB_TERM;
    case PLAN_GLOWCAP:  return false;                        /* caps glow: all light inside the outline */
    default:            return true;
    }
}

/* Accents after despeckle: never treated as noise. */
static void detail(int plan, Plane* ink, Plane* m, int size, uint8_t var) {
    (void)m;
    switch(plan) {
    case PLAN_STANDING: {                /* one crack across the lit face */
        int lean = stone_lean(var), y = STONE_CRACK_Y + (var & 3) * 3;
        int cx = 16 + (lean * (31 - y)) / 25;
        seg(ink, size, cx - 3, y, cx, y + 1, 1);
        break;
    }
    case PLAN_MENHIR: {                  /* two cracks across the lit face */
        int lean = stone_lean(var);
        for(int k = 0; k < 2; k++) {
            int y = MENHIR_CRACK_Y + (var & 1) * 2 + k * 8;
            int cx = 16 + (lean * (31 - y)) / (31 - MENHIR_TOP);
            seg(ink, size, cx - 5 + k, y, cx, y + 1 + k, 1);
        }
        break;
    }
    case PLAN_ALTAR:                     /* the cloth's edges down the front */
        seg(ink, size, 10, 17, 10, 26, 1);
        seg(ink, size, 21, 17, 21, 26, 1);
        seg(ink, size, 10, 26, 21, 26, 1);
        break;
    case PLAN_BARREL:                    /* the hoops */
        seg(ink, size, 9, BARREL_HOOP_A, 23, BARREL_HOOP_A, 1);
        seg(ink, size, 9, BARREL_HOOP_B, 23, BARREL_HOOP_B, 1);
        break;
    case PLAN_HEARTH:                    /* the flame's tongue */
        seg(ink, size, 16, 24, 16, 28, 1);
        break;
    case PLAN_STATUE:                    /* folds of the robe */
        seg(ink, size, 14, 14, 13, 25, 1);
        break;
    case PLAN_STALAGMITE:                /* drip rings on the lit face */
        seg(ink, size, 12, 18, 15, 19, 1);
        seg(ink, size, 10, 25, 15, 26, 1);
        break;
    case PLAN_SARCOPHAGUS:               /* the lid's edge, and a carved panel */
        seg(ink, size, 3, 20, 28, 20, 1);
        seg(ink, size, 11, 24, 20, 24, 1);
        break;
    case PLAN_BONES: {                   /* dark eye sockets + teeth line */
        int sx = 13 + (var & 1) * 5;
        rect(ink, size, sx - 3, 20, sx - 1, 22, 1);
        rect(ink, size, sx + 1, 20, sx + 3, 22, 1);
        seg(ink, size, sx - 2, 25, sx + 2, 25, 1);
        break;
    }
    case PLAN_URN:                       /* a painted band round the belly */
        seg(ink, size, 9, 21, 22, 21, 1);
        break;
    case PLAN_CART:                      /* plank line + corner irons */
        seg(ink, size, 7, 21, 25, 21, 1);
        seg(ink, size, 9, 17, 9, 25, 1);
        break;
    case PLAN_POST:                      /* the grain, and an iron band */
        seg(ink, size, 15, 6, 15, 27, 1);
        seg(ink, size, 16 - POST_HW, 20, 16, 20, 1);
        break;
    case PLAN_STUMP:                     /* growth ring + a bark split */
        seg(ink, size, 14, STUMP_TOP, 18, STUMP_TOP, 1);
        seg(ink, size, 13, STUMP_TOP + 3, 12, 30, 1);
        break;
    case PLAN_BOULDER:                   /* a split down the face */
        if(var & 2) seg(ink, size, 13, 18, 11, 24, 1);
        break;
    case PLAN_SCRUB:                     /* two bare twigs above the leaves */
        seg(ink, size, 15, 21, 13, 17, 1); seg(m, size, 15, 21, 13, 17, 1);
        seg(ink, size, 20, 22, 22, 18, 1); seg(m, size, 20, 22, 22, 18, 1);
        break;
    default: break;
    }
}

bool terrain_compose_prop(char glyph, uint8_t variant, int size, uint8_t* ink_b, uint8_t* mask_b) {
    memset(ink_b, 0, PIXKIT_PLANE_BYTES);
    memset(mask_b, 0, PIXKIT_PLANE_BYTES);
    const TerrainDef* d = terrain_def(glyph);
    if(!d || d->form != TF_PROP || size < 8 || size > PIXKIT_MAX_PX) return false;
    uint8_t var = (uint8_t)(variant % TERRAIN_VARIANTS);
    Plane ink = {ink_b, size, size, (size + 7) / 8};
    Plane m = {mask_b, size, size, (size + 7) / 8};

    shape(d->plan, &m, size, var);
    tighten(&m);
    for(int y = 0; y < size; y++)
        for(int x = 0; x < size; x++) {
            if(!pget(&m, x, y)) continue;
            bool edge = !pget(&m, x - 1, y) || !pget(&m, x + 1, y) ||
                        !pget(&m, x, y - 1) || !pget(&m, x, y + 1);
            bool solid = size < PROP_LOD_SMALL_PX && d->plan != PLAN_GLOWCAP;
            pset(&ink, x, y, edge || solid || shade(d->plan, &m, x, y, size, var));
        }
    despeckle(&ink, &m);
    if(size >= PROP_LOD_SMALL_PX) detail(d->plan, &ink, &m, size, var);
    return true;
}
