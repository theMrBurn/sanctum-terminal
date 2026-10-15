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

/* ── plans ─────────────────────────────────────────────────────────── */
enum { PLAN_NONE = 0, PLAN_STANDING, PLAN_CAIRN, PLAN_BOULDER, PLAN_DEADFALL,
       PLAN_SCRUB, PLAN_GLOWCAP, PLAN_MENHIR, PLAN_MOSS = TERRAIN_PLAN_MOSS, PLAN_SCREE = TERRAIN_PLAN_SCREE };

static const TerrainDef TERRAIN[] = {
    /* glyph       form      material     plan           span */
    {TILE_WALL,   TF_SLAB,  TM_STONE,    PLAN_NONE,     1},
    {TILE_SECRET, TF_SLAB,  TM_STONE,    PLAN_NONE,     1},   /* a secret looks like wall */
    {'O',         TF_SLAB,  TM_COLUMN,   PLAN_NONE,     1},   /* mega column */
    {'H',         TF_PROP,  0,           PLAN_MENHIR,   2},   /* menhir: one stone on a 2x2 */
    {'I',         TF_PROP,  0,           PLAN_STANDING, 1},
    {'Q',         TF_PROP,  0,           PLAN_CAIRN,    1},
    {TILE_ROCK,   TF_PROP,  0,           PLAN_BOULDER,  1},
    {'~',         TF_PROP,  0,           PLAN_DEADFALL, 1},
    {';',         TF_PROP,  0,           PLAN_SCRUB,    1},
    {'q',         TF_PROP,  0,           PLAN_GLOWCAP,  1},
    {',',         TF_FLOOR, 0,           PLAN_MOSS,     1},
    {':',         TF_FLOOR, 0,           PLAN_SCREE,    1},
};

const TerrainDef* terrain_def(char glyph) {
    for(unsigned i = 0; i < sizeof(TERRAIN) / sizeof(TERRAIN[0]); i++)
        if(TERRAIN[i].glyph == glyph) return &TERRAIN[i];
    return NULL;
}

bool terrain_stops_ray(char glyph) {
    const TerrainDef* d = terrain_def(glyph);
    if(d) return d->form == TF_SLAB;
    return world_is_blocking(glyph);
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
