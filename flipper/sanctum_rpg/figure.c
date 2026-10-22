/* figure.c — the visual composer (see figure.h).
 *
 * Pipeline, all in a 32-unit design space scaled to the budget:
 *   1. BODY   — the family's body plan fills the mask (silhouette).
 *   2. HIDE   — tighten the silhouette (no lone pixels, spurs or notches),
 *               then ink = outline + POSTERIZED FORM (clear top, solid below
 *               a hard terminator, one accent line), then despeckle (no
 *               isolated dots of either tone survive inside the body).
 *   3. DETAIL — limbs, tails, antennae (ink+mask), eyes (mask only: they
 *               glow as opaque light out of a dark body). Plans that face
 *               the viewer (spider, bat, slime) are then mirrored: one half,
 *               reflected, so both sides are always pixel-identical.
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
#include "pixkit.h"

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
typedef enum { HIDE_FUR, HIDE_SHELL, HIDE_DARK, HIDE_MEMBRANE, HIDE_GEL, HIDE_GRAVE } Hide;

typedef struct {
    char glyph;
    Hide hide;
    bool front;      /* faces the viewer: composed mirror-symmetric */
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

#define SPIDER_MARK_Y 18   /* spider: design row of the mark on its back */

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
    eye(ink, m, t, 17, 25 - st * 2);                          /* eyes (mirrored) */
    eye(ink, m, t, 18, 24 - st * 2);
    eye(ink, m, t, 16, SPIDER_MARK_Y - st * 2);               /* the mark on its back */
    eye(ink, m, t, 16, SPIDER_MARK_Y + 1 - st * 2);
}

#define BAT_FINGERS     3   /* scallops per wing */
#define BAT_FINGER_GAP  4   /* design units between them (>= 2px gaps survive tighten) */

/* bat — small body, ears, wide scalloped wings (flap per frame). */
static void bat_body(Plane* m, const Xf* t, int st, int fr) {
    ellipse(m, t, 16, 22, 4, 5, 1);                           /* body */
    ellipse(m, t, 16, 16, 3, 3, 1);                           /* head */
    int wy = st ? 12 : (fr ? 17 : 21);                        /* wing tip height */
    for(int s = -1; s <= 1; s += 2) {                         /* both wings */
        ellipse(m, t, 16 + s * 5, 20, 3, 2, 1);               /* wing root: joins the body */
        for(int k = 0; k < BAT_FINGERS; k++) {
            int cx = 16 + s * (7 + k * BAT_FINGER_GAP);
            int cy = 20 + k * (wy - 20) / (BAT_FINGERS - 1);  /* rises toward the tip */
            ellipse(m, t, cx, cy - 1, 3, 2, 1);               /* leading edge */
            ellipse(m, t, cx, cy + 1, 2, 3, 1);               /* scallop: gaps open below */
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

/* the dead (spec 50 Q1 §Q.3) — a figure that stands like you do, facing
 * you: a bowed head, narrow shoulders, arms that hang and reach to strike. */
static void dead_body(Plane* m, const Xf* t, int st, int fr) {
    (void)fr;
    ellipse(m, t, 16, 9 + st, 4, 4, 1);                       /* head (bows to strike) */
    ellipse(m, t, 16, 18, 5, 6, 1);                           /* chest and shroud */
    ellipse(m, t, 16, 24, 4, 3, 1);                           /* hips */
}
static void dead_detail(Plane* ink, Plane* m, const Xf* t, int st, int fr) {
    int f = fr ? 1 : 0;
    int hand_y = st ? 13 : 24;                                /* the tell: arms up */
    limb(ink, m, t, 11, 15, 8, hand_y);                       /* arms */
    limb(ink, m, t, 21, 15, 24, hand_y);
    limb(ink, m, t, 14, 26, 13 - f, 31);                      /* legs, a dragging step */
    limb(ink, m, t, 18, 26, 19 + f, 31);
    eye(ink, m, t, 14, 9 + st);                               /* hollow eyes */
    eye(ink, m, t, 18, 9 + st);
}

static const BodyPlan PLANS[] = {
    {'r', HIDE_FUR,      false, rat_body,    rat_detail},
    {'b', HIDE_SHELL,    false, beetle_body, beetle_detail},
    {'s', HIDE_DARK,     true,  spider_body, spider_detail},
    {'B', HIDE_MEMBRANE, true,  bat_body,    bat_detail},
    {'S', HIDE_GEL,      true,  slime_body,  slime_detail},
    {'D', HIDE_GRAVE,    true,  dead_body,   dead_detail},
};

static const BodyPlan* plan_for(char glyph) {
    for(unsigned i = 0; i < sizeof(PLANS) / sizeof(PLANS[0]); i++)
        if(PLANS[i].glyph == glyph) return &PLANS[i];
    return NULL;
}

/* Material = POSTERIZED FORM. Light comes from above. Each body column is
 * split at a TERMINATOR (v = 0 top .. 15 belly): clear above, solid ink
 * below, with exactly one 50% row at the boundary — two tones and a hard
 * edge, which is what reads as tight on a 1-bit screen (gradient dither
 * read as mush; tried 2026-10-14, see sheets). Each hide has its own
 * terminator and ONE accent drawn as a crisp clear LINE — never single
 * dots or a checker row, which despeckle() would treat as noise. */
#define TERM_SOLID 0
static const struct { int8_t term; } MATERIAL[] = {
    [HIDE_FUR]      = {11},          /* pale coat, dark belly */
    [HIDE_SHELL]    = {2},           /* dark lacquer ... */
    [HIDE_DARK]     = {TERM_SOLID},  /* spider: solid */
    [HIDE_MEMBRANE] = {5},           /* bat: light crown, dark wings */
    [HIDE_GEL]      = {9},           /* slime: clear dome, dark base */
    [HIDE_GRAVE]    = {6},           /* the dead: pale head and shoulders, dark shroud */
};
#define GLOSS_V        5   /* shell: a clear highlight line at this depth */
#define SHINE_V        3   /* slime: a clear shine dot row */
#define EMBER_TERM     4   /* ember: crust below this depth */
#define EMBER_SEAM_V   9   /* ember: depth of the glowing seam ... */
#define EMBER_DASH     3   /* ... broken into dashes this long (crawl per frame) */

static bool hide_ink(Hide h, int x, int y, int v, bool small) {
    if(small) return true;                     /* tiny: solid silhouette reads best */
    int term = MATERIAL[h].term;
    (void)x; (void)y;
    bool ink = term == TERM_SOLID || v > term;
    switch(h) {
    case HIDE_SHELL: if(v == GLOSS_V) ink = false; break;             /* gloss line */
    case HIDE_GEL:   if(v == SHINE_V) ink = false; break;             /* shine line */
    default: break;
    }
    return ink;
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
    bool flyer = (fam->move_flags & CF_FLIGHT) != 0 || (tr->add_flags & CF_PHASE) != 0;   /* the spectral hover */
    int fr = budget->anim_frames ? frame % budget->anim_frames : 0;
    int st = pose == POSE_STRIKE;

    Xf t = {budget->width, budget->height,
            big ? DIRE_SCALE : BASE_SCALE, big ? DIRE_SCALE : BASE_SCALE,
            flyer && pose != POSE_DEAD ? HOVER_LIFT : 0};
    bool pale = (tr->add_flags & (CF_PHOTOPHOBIC | CF_PHASE)) != 0 && tr->element == ELEM_NONE;
    bool heavy_build = tr->d_def >= HEAVY_DEF_MIN;
    bool banded = tr->d_hp >= 1 && tr->d_def == 1 && tr->element == ELEM_NONE && !big;
    if(heavy_build && tr->element == ELEM_NONE) {
        t.sx = (t.sx * BUILD_STOCKY_X) / 16; t.sy = (t.sy * BUILD_STOCKY_Y) / 16;
    } else if(pale || tr->mark == MARK_GAUNT) {
        t.sx = (t.sx * BUILD_GAUNT_X) / 16;  t.sy = (t.sy * BUILD_GAUNT_Y) / 16;
    } else if(banded || tr->mark == MARK_SPOTS) {
        t.sx = (t.sx * BUILD_HUNCH_X) / 16;  t.sy = (t.sy * BUILD_HUNCH_Y) / 16;
    }
    if(pose == POSE_FLEE) t.sy = (t.sy * CROUCH_Y) / 16;
    if(pose == POSE_DEAD) t.sy = (t.sy * DEAD_Y) / 16;
    if(pose == POSE_MOVE) fr ^= 1;   /* stride is the other foot from idle */

    /* 1. BODY */
    plan->body(&m, &t, st, fr);

    /* 4a. TRAIT silhouette additions that are BODIES (outlined by the hide) */
    if(tr->element == ELEM_FIRE) {                      /* flame tongues, flicker per frame */
        for(int k = 0; k < 3; k++) {
            int x = 11 + k * 5, h = 10 + ((k + fr) % 2) * 3;
            ellipse(&m, &t, x, 19 - h / 2, 2, h / 2, 1);
        }
    }

    /* 2. HIDE — tighten the silhouette, then outline + form shading */
    tighten(&m);
    bool small = budget->width < LOD_SMALL_PX;
    bool heavy = heavy_build && !small;
    for(int y = 0; y < m.h; y++)
        for(int x = 0; x < m.w; x++) {
            if(!pget(&m, x, y)) continue;
            int edge = !pget(&m, x - 1, y) || !pget(&m, x + 1, y) ||
                       !pget(&m, x, y - 1) || !pget(&m, x, y + 1);
            int edge2 = heavy && (!pget(&m, x - 2, y) || !pget(&m, x + 2, y) ||
                                  !pget(&m, x, y - 2) || !pget(&m, x, y + 2));
            int v = column_v(&m, x, y);
            bool on;
            if(edge || edge2) on = true;
            else if(pale) on = small;                           /* hollow, unless tiny */
            else if(banded && !small && (v == 5 || v == 10)) on = true;   /* bands follow the body */
            else if(tr->element == ELEM_FIRE && !small)          /* dark crust, glowing seams */
                on = v > EMBER_TERM && !(v == EMBER_SEAM_V && ((x + fr * EMBER_DASH) / EMBER_DASH) & 1);
            else on = hide_ink(plan->hide, x, y, v, small);
            pset(&ink, x, y, on);
        }

    despeckle(&ink, &m);

    /* 4b. TRAIT strokes — 1px, so all outline; drawn after tighten/despeckle */
    if(tr->element == ELEM_ICE) {                       /* ice spikes along the back */
        for(int k = 0; k < 4; k++) {
            int x = 9 + k * 4;
            limb(&ink, &m, &t, x, 20, x + 1, 13 + (k & 1) * 2);
            limb(&ink, &m, &t, x + 2, 20, x + 1, 13 + (k & 1) * 2);
        }
    }
    if(big) {                                           /* horns */
        limb(&ink, &m, &t, 20, 18, 23, 11);
        limb(&ink, &m, &t, 23, 11, 25, 13);
        limb(&ink, &m, &t, 24, 19, 28, 12);
    }

    /* 3. DETAIL — limbs + eyes over the hide */
    plan->detail(&ink, &m, &t, st, fr);
    /* 4d. TRAIT marks (data: Trait.mark), drawn before the front mirror so
     * they come out symmetric on figures that face you. */
    switch(tr->mark) {
    case MARK_MAW:                                     /* an open jaw */
        limb(&ink, &m, &t, 14, 13 + st, 13, 16 + st);
        limb(&ink, &m, &t, 18, 13 + st, 19, 16 + st);
        break;
    case MARK_DRIP:                                    /* drops falling, one frame apart */
        limb(&ink, &m, &t, 9, 26 + fr, 9, 27 + fr);
        limb(&ink, &m, &t, 23, 28 - fr, 23, 29 - fr);
        break;
    case MARK_SPOTS:                                   /* clear blotches on the hide */
        eye(&ink, &m, &t, 14, 17);
        eye(&ink, &m, &t, 18, 20);
        eye(&ink, &m, &t, 15, 23);
        break;
    default: break;
    }
    if(plan->front) mirror_half(&ink, &m);

    /* 4c. TRAIT overlays (asymmetric on purpose: streaks trail) */
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
