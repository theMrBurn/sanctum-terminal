/* figure.c — the visual composer (see figure.h).
 *
 * Pipeline, all in a 32-unit design space scaled to the budget:
 *   1. BODY   — the family's body plan fills the mask (silhouette).
 *   2. HIDE   — ink = outline of the mask + the family's material pattern.
 *   3. DETAIL — limbs, tails, antennae (ink+mask), eyes (mask only: they
 *               glow as opaque light out of a dark body).
 *   4. TRAIT  — cues read from the trait's DATA, not its name, so a trait
 *               added later gets a look for free:
 *                 element ICE      -> ice spikes along the back
 *                 element FIRE     -> flame tongues (flicker per frame)
 *                 photophobic      -> pale: hide cleared to outline, gaunt build
 *                 speed  >= +3     -> trailing streaks
 *                 defence>= +2     -> heavy (doubled) outline, stocky build
 *                 hp & def +1 each -> stony bands, hunched build
 *                 hp & atk >= +3   -> bigger body + horns
 *   5. POSE   — strike rears up / raises limbs; flee mirrors and crouches;
 *               dead flips belly-up and flattens.
 *
 * Integer-only and allocation-free; the only randomness is a local hash of
 * (family, trait) for small per-kind variation — never the game's rng. */
#include "figure.h"

#include <string.h>

#include "creatures.h"

const RenderBudget RENDER_BUDGET_FLIPPER_1BIT = {32, 32, 1, 0, 2, 0};

/* ── tunables (AGENTS.md: no hardcoded tunables) ───────────────────── */
#define DESIGN            32   /* design-space units across the figure box */
#define BASE_SCALE        16   /* body scale /16 for ordinary creatures */
#define DIRE_SCALE        19   /* body scale /16 for big (dire) creatures */
#define CROUCH_Y          12   /* flee: vertical squash /16 */
#define DEAD_Y            12   /* dead: vertical squash /16 */
#define HOVER_LIFT         8   /* flyers float this many design units up */
#define SPEED_STREAK_MIN   3   /* d_speed at/above which streaks appear */
#define HEAVY_DEF_MIN      2   /* d_def at/above which the outline doubles */
#define BIG_HP_MIN         3   /* d_hp and d_atk at/above which: big + horns */
#define BIG_ATK_MIN        3
#define LOD_SMALL_PX      16   /* below this: solid hide, no texture */
/* Build follows the trait's stats too, so its cue survives at distance
 * where the hide goes solid: (sx, sy) /16 multipliers on the body scale. */
#define BUILD_STOCKY_X    19   /* defence >= HEAVY_DEF_MIN: broad */
#define BUILD_STOCKY_Y    15
#define BUILD_GAUNT_X     14   /* pale (photophobic, no element): thin */
#define BUILD_GAUNT_Y     13
#define BUILD_HUNCH_X     15   /* hp & def +1 (cave): hunched, tall back */
#define BUILD_HUNCH_Y     19

/* ── planes ─────────────────────────────────────────────────────────── */
typedef struct {
    uint8_t* b;
    int w, h, stride;
} Plane;

static inline bool in_plane(const Plane* p, int x, int y) {
    return x >= 0 && y >= 0 && x < p->w && y < p->h;
}
static inline int pget(const Plane* p, int x, int y) {
    if(!in_plane(p, x, y)) return 0;
    return (p->b[y * p->stride + (x >> 3)] >> (x & 7)) & 1;
}
static inline void pset(Plane* p, int x, int y, int v) {
    if(!in_plane(p, x, y)) return;
    uint8_t* q = &p->b[y * p->stride + (x >> 3)];
    if(v) *q |= (uint8_t)(1u << (x & 7));
    else  *q &= (uint8_t)~(1u << (x & 7));
}

/* ── the transform: design space -> plane, with body scale + pose squash.
 * Anchor is bottom-centre (feet stay on the floor); flyers are lifted. ── */
typedef struct {
    int w, h;          /* plane size */
    int sx, sy;        /* scale /16 in x and y */
    int lift;          /* design units raised (flyers) */
} Xf;

static int tx(const Xf* t, int x) {
    int dx = ((x - DESIGN / 2) * t->sx) / 16;
    return ((DESIGN / 2 + dx) * t->w) / DESIGN;
}
static int ty(const Xf* t, int y) {
    int up = ((DESIGN - 1 - y) * t->sy) / 16;     /* height above the floor */
    if(up < 0) up = 0;
    return ((DESIGN - 1 - up - t->lift) * t->h) / DESIGN;
}
static int tr(const Xf* t, int r, bool vertical) {
    int s = vertical ? t->sy : t->sx;
    int v = (r * s * (vertical ? t->h : t->w)) / (16 * DESIGN);
    return v < 1 ? 1 : v;
}

/* ── primitives (all take design-space coordinates) ─────────────────── */
static void ellipse(Plane* p, const Xf* t, int cx, int cy, int rx, int ry, int v) {
    int px = tx(t, cx), py = ty(t, cy);
    int ax = tr(t, rx, false), ay = tr(t, ry, true);
    long a2 = (long)ax * ax, b2 = (long)ay * ay, ab = a2 * b2;
    for(int y = -ay; y <= ay; y++)
        for(int x = -ax; x <= ax; x++)
            if((long)x * x * b2 + (long)y * y * a2 <= ab) pset(p, px + x, py + y, v);
}

static void line_px(Plane* p, int x0, int y0, int x1, int y1, int v) {
    int dx = x1 > x0 ? x1 - x0 : x0 - x1, sx = x0 < x1 ? 1 : -1;
    int dy = y1 > y0 ? y0 - y1 : y1 - y0, sy = y0 < y1 ? 1 : -1;
    int err = dx + dy;
    for(;;) {
        pset(p, x0, y0, v);
        if(x0 == x1 && y0 == y1) break;
        int e2 = 2 * err;
        if(e2 >= dy) { err += dy; x0 += sx; }
        if(e2 <= dx) { err += dx; y0 += sy; }
    }
}

/* A limb: drawn into BOTH planes (thin parts are all outline). */
static void limb(Plane* ink, Plane* mask, const Xf* t, int x0, int y0, int x1, int y1) {
    int a = tx(t, x0), b = ty(t, y0), c = tx(t, x1), d = ty(t, y1);
    line_px(ink, a, b, c, d, 1);
    line_px(mask, a, b, c, d, 1);
}

/* An eye: opaque light — mask on, ink off, a single plane pixel. */
static void eye(Plane* ink, Plane* mask, const Xf* t, int x, int y) {
    int a = tx(t, x), b = ty(t, y);
    pset(mask, a, b, 1);
    pset(ink, a, b, 0);
}

/* ── family body plans ─────────────────────────────────────────────────
 * Each plan has a body() into the mask and a detail() for limbs + eyes.
 * `st` = 1 when striking (the tell), `fr` = animation frame (0/1). */
typedef enum { HIDE_FUR, HIDE_SHELL, HIDE_DARK, HIDE_MEMBRANE, HIDE_GEL } Hide;

typedef struct {
    char glyph;
    Hide hide;
    void (*body)(Plane* m, const Xf* t, int st, int fr);
    void (*detail)(Plane* ink, Plane* m, const Xf* t, int st, int fr);
} BodyPlan;

/* rat — long and low: body, wedge head, ears, a tail that curls. */
static void rat_body(Plane* m, const Xf* t, int st, int fr) {
    (void)fr;
    ellipse(m, t, 14, 24 - st * 3, 10, 6, 1);                 /* body (rears on strike) */
    ellipse(m, t, 24, 21 - st * 6, 5, 5, 1);                  /* head */
    ellipse(m, t, 21, 16 - st * 6, 2, 3, 1);                  /* ear */
}
static void rat_detail(Plane* ink, Plane* m, const Xf* t, int st, int fr) {
    int f = fr ? 2 : -2;
    limb(ink, m, t, 8 + f, 29, 8 + f, 31);                    /* hind legs */
    limb(ink, m, t, 19 - f, 29 - st * 3, 20 - f, 31);         /* fore legs */
    limb(ink, m, t, 4, 26, 1, 21);                            /* tail */
    limb(ink, m, t, 1, 21, 3, 16);
    limb(ink, m, t, 28, 22 - st * 6, 31, 23 - st * 6);        /* snout */
    eye(ink, m, t, 25, 20 - st * 6);
}

/* beetle — a dome with a split shell, six legs, feelers. */
static void beetle_body(Plane* m, const Xf* t, int st, int fr) {
    (void)fr;
    ellipse(m, t, 15, 25, 11, 7, 1);                          /* shell */
    ellipse(m, t, 26 + st, 26 + st * 2, 4, 3, 1);             /* head (dips to ram) */
}
static void beetle_detail(Plane* ink, Plane* m, const Xf* t, int st, int fr) {
    int f = fr ? 1 : -1;
    for(int i = 0; i < 3; i++) {                              /* six legs: 3 visible pairs */
        int x = 8 + i * 7;
        limb(ink, m, t, x, 29, x - 2 + (i & 1 ? f : -f), 31);
    }
    limb(ink, m, t, 15, 18, 15, 31);                          /* the shell's split */
    limb(ink, m, t, 28 + st, 24 + st * 2, 31, 20 + st * 4);   /* feelers */
    limb(ink, m, t, 27 + st, 24 + st * 2, 29, 19 + st * 4);
    eye(ink, m, t, 28 + st, 26 + st * 2);
}

/* spider — round body high on eight splayed legs, knees above the back. */
static void spider_body(Plane* m, const Xf* t, int st, int fr) {
    (void)fr;
    ellipse(m, t, 16, 20 - st * 2, 6, 5, 1);                  /* abdomen */
    ellipse(m, t, 16, 25 - st * 2, 3, 2, 1);                  /* head, toward you */
}
static void spider_detail(Plane* ink, Plane* m, const Xf* t, int st, int fr) {
    /* four legs per side: knee out and up, foot out and down */
    for(int s = -1; s <= 1; s += 2)
        for(int i = 0; i < 4; i++) {
            int lift = ((i + fr) & 1);                        /* alternate gait */
            int kx = 16 + s * (7 + i * 2), ky = 14 + i - lift;
            int fx = 16 + s * (9 + i * 2 + (i == 3 ? 2 : 0)), fy = 31 - lift;
            if(st && i == 0) { ky = 9; fy = 13; fx = 16 + s * 9; }   /* the tell: front legs up */
            limb(ink, m, t, 16 + s * 3, 21 - st * 2, kx, ky);
            limb(ink, m, t, kx, ky, fx, fy);
        }
    for(int k = -1; k <= 1; k += 2) eye(ink, m, t, 16 + k, 25 - st * 2);
    eye(ink, m, t, 16 + 2, 24 - st * 2);
    eye(ink, m, t, 16 - 2, 24 - st * 2);
}

/* bat — small body, ears, wide scalloped wings (flap per frame). */
static void bat_body(Plane* m, const Xf* t, int st, int fr) {
    ellipse(m, t, 16, 22, 4, 5, 1);                           /* body */
    ellipse(m, t, 16, 16, 3, 3, 1);                           /* head */
    int wy = st ? 12 : (fr ? 17 : 21);                        /* wing tip height */
    for(int s = -1; s <= 1; s += 2) {                         /* both wings */
        for(int k = 0; k < 4; k++) {                          /* scallops */
            int cx = 16 + s * (6 + k * 3);
            int cy = wy + (3 - k) * (22 - wy) / 4;
            ellipse(m, t, cx, cy + 2, 3, 3, 1);
        }
    }
}
static void bat_detail(Plane* ink, Plane* m, const Xf* t, int st, int fr) {
    (void)st; (void)fr;
    limb(ink, m, t, 14, 13, 13, 10);                          /* ears */
    limb(ink, m, t, 18, 13, 19, 10);
    eye(ink, m, t, 15, 16);
    eye(ink, m, t, 17, 16);
}

/* slime — a mound with a drip; stretches tall to strike, pulses per frame. */
static void slime_body(Plane* m, const Xf* t, int st, int fr) {
    int ry = st ? 11 : (fr ? 7 : 6);
    int rx = st ? 8 : (fr ? 11 : 12);
    ellipse(m, t, 16, 31 - ry / 2, rx, ry, 1);
    ellipse(m, t, 16, 31, rx + 2, 2, 1);                      /* the spread at its base */
}
static void slime_detail(Plane* ink, Plane* m, const Xf* t, int st, int fr) {
    (void)fr;
    int ey = st ? 22 : 27;
    eye(ink, m, t, 13, ey);
    eye(ink, m, t, 19, ey);
    eye(ink, m, t, 11, ey - 2);                               /* the shine */
}

static const BodyPlan PLANS[] = {
    {'r', HIDE_FUR,      rat_body,    rat_detail},
    {'b', HIDE_SHELL,    beetle_body, beetle_detail},
    {'s', HIDE_DARK,     spider_body, spider_detail},
    {'B', HIDE_MEMBRANE, bat_body,    bat_detail},
    {'S', HIDE_GEL,      slime_body,  slime_detail},
};

static const BodyPlan* plan_for(char glyph) {
    for(unsigned i = 0; i < sizeof(PLANS) / sizeof(PLANS[0]); i++)
        if(PLANS[i].glyph == glyph) return &PLANS[i];
    return NULL;
}

/* Material: does the hide put ink at interior pixel (x, y)? */
static bool hide_ink(Hide h, int x, int y, bool pale, bool small) {
    if(pale) return false;
    if(small) return true;                     /* tiny: solid silhouette reads best */
    switch(h) {
    case HIDE_FUR:      return (y % 3) == 0 && ((x + y) & 1);       /* short fur strokes */
    case HIDE_SHELL:    return ((x + y) & 1) == 0 || (y & 3) == 0;  /* dense lacquer */
    case HIDE_DARK:     return !((x & 3) == 1 && (y & 3) == 1);     /* near-solid */
    case HIDE_MEMBRANE: return ((x + y) & 1) == 0;                  /* even dither */
    case HIDE_GEL:      return ((x + y) & 1) == 0 && !((x & 3) == 1 && (y & 3) == 0); /* wet, with glints */
    }
    return false;
}

static void mirror_x(Plane* a, Plane* b) {
    for(int y = 0; y < a->h; y++)
        for(int x = 0; x < a->w / 2; x++) {
            int xr = a->w - 1 - x;
            int t1 = pget(a, x, y), t2 = pget(b, x, y);
            pset(a, x, y, pget(a, xr, y)); pset(a, xr, y, t1);
            pset(b, x, y, pget(b, xr, y)); pset(b, xr, y, t2);
        }
}

static void flip_y(Plane* a, Plane* b) {
    int top = -1;                                   /* figure's top row */
    for(int y = 0; y < b->h && top < 0; y++)
        for(int x = 0; x < b->w; x++) if(pget(b, x, y)) { top = y; break; }
    if(top < 0) return;
    for(int i = 0; top + i < b->h - 1 - i; i++) {
        int y1 = top + i, y2 = b->h - 1 - i;
        for(int x = 0; x < b->w; x++) {
            int t1 = pget(a, x, y1), t2 = pget(b, x, y1);
            pset(a, x, y1, pget(a, x, y2)); pset(a, x, y2, t1);
            pset(b, x, y1, pget(b, x, y2)); pset(b, x, y2, t2);
        }
    }
}

/* ── the composer ───────────────────────────────────────────────────── */
FigurePose figure_pose_for_state(uint8_t s) {
    switch(s) {
    case CR_APPROACH: return POSE_MOVE;
    case CR_FLEE:     return POSE_FLEE;
    case CR_ENGAGE:   return POSE_STRIKE;
    default:          return POSE_IDLE;
    }
}

bool figure_compose(
    const RenderBudget* budget, uint8_t family_id, uint8_t trait_id,
    FigurePose pose, uint8_t frame, uint8_t* ink_b, uint8_t* mask_b) {
    memset(ink_b, 0, FIGURE_PLANE_BYTES);
    memset(mask_b, 0, FIGURE_PLANE_BYTES);
    if(!budget || budget->bit_depth != 1 || budget->width > FIGURE_MAX_PX ||
       budget->height > FIGURE_MAX_PX || budget->width < 8 || budget->height < 8)
        return false;
    const Family* fam = creature_family(family_id);
    const Trait* tr = creature_trait(trait_id);
    if(!fam || !tr) return false;
    const BodyPlan* plan = plan_for(fam->glyph);
    if(!plan) return false;

    Plane ink = {ink_b, budget->width, budget->height, (budget->width + 7) / 8};
    Plane m = {mask_b, budget->width, budget->height, (budget->width + 7) / 8};

    bool big = tr->d_hp >= BIG_HP_MIN && tr->d_atk >= BIG_ATK_MIN;
    bool flyer = (fam->move_flags & CF_FLIGHT) != 0;
    int fr = budget->anim_frames ? frame % budget->anim_frames : 0;
    int st = pose == POSE_STRIKE;

    Xf t = {budget->width, budget->height,
            big ? DIRE_SCALE : BASE_SCALE, big ? DIRE_SCALE : BASE_SCALE,
            flyer && pose != POSE_DEAD ? HOVER_LIFT : 0};
    bool pale = (tr->add_flags & CF_PHOTOPHOBIC) != 0 && tr->element == ELEM_NONE;
    bool heavy_build = tr->d_def >= HEAVY_DEF_MIN;
    bool banded = tr->d_hp >= 1 && tr->d_def == 1 && tr->element == ELEM_NONE && !big;
    if(heavy_build && tr->element == ELEM_NONE) {
        t.sx = (t.sx * BUILD_STOCKY_X) / 16; t.sy = (t.sy * BUILD_STOCKY_Y) / 16;
    } else if(pale) {
        t.sx = (t.sx * BUILD_GAUNT_X) / 16;  t.sy = (t.sy * BUILD_GAUNT_Y) / 16;
    } else if(banded) {
        t.sx = (t.sx * BUILD_HUNCH_X) / 16;  t.sy = (t.sy * BUILD_HUNCH_Y) / 16;
    }
    if(pose == POSE_FLEE) t.sy = (t.sy * CROUCH_Y) / 16;
    if(pose == POSE_DEAD) t.sy = (t.sy * DEAD_Y) / 16;
    if(pose == POSE_MOVE) fr ^= 1;   /* stride is the other foot from idle */

    /* 1. BODY */
    plan->body(&m, &t, st, fr);

    /* 4a. TRAIT silhouette additions (before the hide, so they get outlined) */
    if(tr->element == ELEM_ICE) {                       /* ice spikes along the back */
        for(int k = 0; k < 4; k++) {
            int x = 9 + k * 4;
            limb(&ink, &m, &t, x, 20, x + 1, 13 + (k & 1) * 2);
            limb(&ink, &m, &t, x + 2, 20, x + 1, 13 + (k & 1) * 2);
        }
    }
    if(tr->element == ELEM_FIRE) {                      /* flame tongues, flicker per frame */
        for(int k = 0; k < 3; k++) {
            int x = 11 + k * 5, h = 10 + ((k + fr) % 2) * 3;
            ellipse(&m, &t, x, 19 - h / 2, 2, h / 2, 1);
        }
    }
    if(big) {                                           /* horns */
        limb(&ink, &m, &t, 20, 18, 23, 11);
        limb(&ink, &m, &t, 23, 11, 25, 13);
        limb(&ink, &m, &t, 24, 19, 28, 12);
    }

    /* 2. HIDE — outline + material, from the mask */
    bool small = budget->width < LOD_SMALL_PX;
    bool heavy = heavy_build && !small;
    for(int y = 0; y < m.h; y++)
        for(int x = 0; x < m.w; x++) {
            if(!pget(&m, x, y)) continue;
            int edge = !pget(&m, x - 1, y) || !pget(&m, x + 1, y) ||
                       !pget(&m, x, y - 1) || !pget(&m, x, y + 1);
            int edge2 = heavy && (!pget(&m, x - 2, y) || !pget(&m, x + 2, y) ||
                                  !pget(&m, x, y - 2) || !pget(&m, x, y + 2));
            bool on = edge || edge2 || hide_ink(plan->hide, x, y, pale, small) ||
                      (banded && (y % 4) == 0);
            if(tr->element == ELEM_FIRE && !edge) on = ((x + y + fr) & 1) == 0;
            pset(&ink, x, y, on);
        }

    /* 3. DETAIL — limbs + eyes over the hide */
    plan->detail(&ink, &m, &t, st, fr);

    /* 4b. TRAIT overlays */
    if(tr->d_speed >= SPEED_STREAK_MIN && pose != POSE_DEAD) {   /* trailing streaks */
        for(int k = 0; k < 3; k++) {
            int y = 21 + k * 3;
            limb(&ink, &m, &t, 0 + k * 2, y, 4 + k * 2, y);
        }
    }
    /* 5. POSE post-process: flee faces away (mirror); dead lies belly-up
     * (rows flipped within the figure, still resting on the floor). */
    if(pose == POSE_FLEE) mirror_x(&ink, &m);
    if(pose == POSE_DEAD) flip_y(&ink, &m);
    return true;
}
