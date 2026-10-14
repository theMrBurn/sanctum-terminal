/*
 * render_fpv.c — first-person renderer.
 *
 * Wolfenstein-3D-style raycaster, integer-only, 1-bit output. Replaces
 * the previous "5 fixed depth slots" fake perspective (which suggested
 * 3D but didn't project the world — playtest 2026-06-04: "incoherent
 * compared to the top down"). The raycaster reads the SAME chunk grid
 * the top-down view reads, so both views agree on geometry.
 *
 * Algorithm (per frame):
 *   For each screen column c in [0, FPV_VIEW_W):
 *     1. Compute ray direction (rdx, rdy) in 8.8 fixed-point from the
 *        player's facing and the column's FOV offset.
 *     2. DDA-walk the tile grid until the ray hits a blocking tile (or
 *        runs off-grid).
 *     3. Compute the perpendicular wall distance (fish-eye-corrected).
 *     4. Wall column height = WALL_HEIGHT_SCALE / distance, clipped.
 *     5. Draw a vertical line of that height, centered on the view's
 *        horizon. Side hint: horizontal-grid hits draw solid, vertical
 *        hits draw dithered — gives wall corners visual contrast.
 *
 * Sprites (vault, hearth, doors, creatures, loot) are billboarded —
 * placed in world-space, projected, scaled by 1/distance, drawn with
 * Z-ordering. Deferred to a follow-up commit; this commit ships walls
 * only (the load-bearing "coherent geometry" win).
 *
 * Fixed-point: 8.8 (1.0 == 256). Distances + ray directions live in
 * this format. No floats anywhere.
 *
 * The previous helpers (jittered lines, depth-slot insets, frame
 * outline, sprite-at-depth placement) are retired — they don't apply
 * to the raycaster. Sprite handling will return via billboard math.
 */

#include "render_fpv.h"

#include <gui/canvas.h>
#include <stdlib.h>

#include "biome.h"
#include "sprites.h"

#define FPV_VIEW_W      128
#define FPV_VIEW_H       48   /* leaves 16 px for status strip */
#define FPV_HORIZON_Y   (FPV_VIEW_H / 2)

/* Fixed-point: 8.8. One tile = 256 fixed-point units. */
#define FP_ONE 256

/* Wall sizing — wall_height = WALL_HEIGHT_SCALE / perpWallDist (both
 * in fixed-point tile units). Tuned so a wall 1 tile away fills ~3/4
 * of the view height. */
#define WALL_HEIGHT_SCALE (FPV_VIEW_H * 3 / 4 * FP_ONE)

/* FOV half-angle = 30° → tan(30°) ≈ 0.577 ≈ 148/256.
 * For a column at horizontal offset (c - W/2), the camera-plane
 * contribution scales linearly from -PLANE_SCALE to +PLANE_SCALE. */
#define PLANE_SCALE 148  /* tan(30°) × 256 */

/* Max DDA steps before giving up — bounded by chunk size + a margin.
 * Chunks are 16×6 tiles; 32 steps is plenty for any ray. */
#define DDA_MAX_STEPS 64

/* ─── Facing helpers (exported) ────────────────────────────────── */

uint8_t fpv_turn_left(uint8_t facing) { return (uint8_t)((facing + 3u) & 3u); }
uint8_t fpv_turn_right(uint8_t facing) { return (uint8_t)((facing + 1u) & 3u); }

int fpv_facing_dx(uint8_t facing) {
    switch(facing & 3u) {
    case FPV_FACE_E: return  1;
    case FPV_FACE_W: return -1;
    default:         return  0;
    }
}

int fpv_facing_dy(uint8_t facing) {
    switch(facing & 3u) {
    case FPV_FACE_N: return -1;
    case FPV_FACE_S: return  1;
    default:         return  0;
    }
}

/* ─── Ray direction setup ───────────────────────────────────────────
 *
 * For each facing, the camera frame has:
 *   forward vector — unit vector in the facing direction
 *   plane vector   — perpendicular, scaled by tan(FOV/2)
 *
 * Ray for column c: rd = forward + plane × (2c/W - 1)
 *
 * In 8.8 fixed-point (FP_ONE = 256):
 *   forward = ±256 along axis
 *   plane   = ±PLANE_SCALE along perpendicular axis
 */

static void ray_dir_for_column(uint8_t facing, int col, int* rdx, int* rdy) {
    /* offset in [-PLANE_SCALE, +PLANE_SCALE] across the screen width. */
    int offset = ((col * 2 - FPV_VIEW_W) * PLANE_SCALE) / FPV_VIEW_W;
    switch(facing & 3u) {
    case FPV_FACE_N:
        *rdx = offset;       /* plane is +x; forward is -y */
        *rdy = -FP_ONE;
        break;
    case FPV_FACE_E:
        *rdx = FP_ONE;       /* forward is +x; plane is +y */
        *rdy = offset;
        break;
    case FPV_FACE_S:
        *rdx = -offset;      /* plane is -x; forward is +y */
        *rdy = FP_ONE;
        break;
    case FPV_FACE_W:
        *rdx = -FP_ONE;      /* forward is -x; plane is -y */
        *rdy = -offset;
        break;
    default:
        *rdx = 0;
        *rdy = -FP_ONE;
        break;
    }
}

/* ─── DDA grid walker ──────────────────────────────────────────────
 *
 * Standard Wolfenstein-3D DDA: from a starting position (in tile-
 * fixed-point), step through the grid in whichever axis has the
 * nearest grid line, until a blocking tile is hit.
 *
 * Returns the perpendicular distance to the wall (8.8 fixed-point),
 * the tile coordinates of the hit, and the "side" (0=we crossed a
 * vertical grid line / hit an X-aligned wall face; 1=horizontal grid
 * line / Y-aligned wall face). Side is used as a render hint.
 */

/* Cast one ray. Returns perpendicular wall distance (8.8 fp), the
 * hit-tile map coords, the side hint, and whether the hit was an
 * actual wall vs running off-grid. Off-grid is meaningful: in OPEN
 * biomes (outdoor), off-grid is NOT a wall — it's a chunk crossing
 * the player can walk through. The renderer uses this to skip wall
 * draw at outdoor chunk edges.
 *
 * Uses int64 for side/delta distances. The DDA setup for near-axis-
 * aligned rays (rdx==0 or rdy==0) produces astronomically large
 * delta values that overflow int32 in the initial side_dist
 * multiplication — that overflow was the column-64 vertical artifact
 * (playtest 2026-06-04). 64-bit math fixes it cleanly without
 * special-casing the axis-aligned rays.
 */
static int cast_ray(
    const World* world,
    int px_fp, int py_fp,  /* player position in 8.8 fp tile units */
    int rdx, int rdy,
    int* out_hit_x, int* out_hit_y, int* out_side, bool* out_off_grid) {

    int map_x = px_fp >> 8;
    int map_y = py_fp >> 8;

    int abs_rdx = rdx < 0 ? -rdx : rdx;
    int abs_rdy = rdy < 0 ? -rdy : rdy;
    int64_t delta_dist_x = (abs_rdx == 0)
        ? (int64_t)0x100000000LL
        : ((int64_t)FP_ONE * FP_ONE) / abs_rdx;
    int64_t delta_dist_y = (abs_rdy == 0)
        ? (int64_t)0x100000000LL
        : ((int64_t)FP_ONE * FP_ONE) / abs_rdy;

    int step_x, step_y;
    int64_t side_dist_x, side_dist_y;

    if(rdx < 0) {
        step_x = -1;
        side_dist_x = ((int64_t)(px_fp - (map_x << 8)) * delta_dist_x) / FP_ONE;
    } else {
        step_x = 1;
        side_dist_x = ((int64_t)(((map_x + 1) << 8) - px_fp) * delta_dist_x) / FP_ONE;
    }
    if(rdy < 0) {
        step_y = -1;
        side_dist_y = ((int64_t)(py_fp - (map_y << 8)) * delta_dist_y) / FP_ONE;
    } else {
        step_y = 1;
        side_dist_y = ((int64_t)(((map_y + 1) << 8) - py_fp) * delta_dist_y) / FP_ONE;
    }

    int side = 0;
    bool hit = false;
    bool off_grid = false;
    for(int step = 0; step < DDA_MAX_STEPS && !hit; step++) {
        if(side_dist_x < side_dist_y) {
            side_dist_x += delta_dist_x;
            map_x += step_x;
            side = 0;
        } else {
            side_dist_y += delta_dist_y;
            map_y += step_y;
            side = 1;
        }
        if(map_x < 0 || map_x >= WORLD_COLS || map_y < 0 || map_y >= WORLD_ROWS) {
            off_grid = true;
            hit = true;
            break;
        }
        if(world_is_blocking(world->tiles[map_y][map_x])) {
            hit = true;
            break;
        }
    }

    *out_hit_x = map_x;
    *out_hit_y = map_y;
    *out_side = side;
    if(out_off_grid) *out_off_grid = off_grid;

    /* Perpendicular wall distance — fish-eye-corrected. */
    int perp;
    if(side == 0) {
        int64_t num = ((int64_t)((map_x << 8) - px_fp) + (step_x < 0 ? FP_ONE : 0)) * FP_ONE;
        int divisor = (rdx == 0) ? 1 : rdx;
        int64_t p64 = num / divisor;
        if(p64 < 0) p64 = -p64;
        if(p64 > 0x7FFFFFFF) p64 = 0x7FFFFFFF;
        perp = (int)p64;
    } else {
        int64_t num = ((int64_t)((map_y << 8) - py_fp) + (step_y < 0 ? FP_ONE : 0)) * FP_ONE;
        int divisor = (rdy == 0) ? 1 : rdy;
        int64_t p64 = num / divisor;
        if(p64 < 0) p64 = -p64;
        if(p64 > 0x7FFFFFFF) p64 = 0x7FFFFFFF;
        perp = (int)p64;
    }
    if(perp < 1) perp = 1;
    return perp;
}

/* ─── Floor detail (perceptual ground plane) ──────────────────────
 *
 * "Carefully placed here and there to provide the illusion of a ground
 * plane" — playtest 2026-06-04 design note. The 1-bit screen + black
 * background register: small white embellishments suggest cobblestone /
 * slate / panels (cavern) or grass blades / leaf tufts (outdoor). The
 * brain does the gestalt; we just place a few pixels.
 *
 * Per visible floor tile: project the tile center to screen, stamp a
 * small (2-4 dot) pattern. Deterministic per (tile_x, tile_y) hash —
 * same chunk paints the same texture each visit.
 *
 * Drawn BEFORE walls so the wall pass naturally occludes any details
 * that fall behind walls (Z-correct by paint order).
 */

static uint32_t tile_hash(int tx, int ty) {
    uint32_t h = (uint32_t)tx * 0x9E3779B9u;
    h ^= (uint32_t)ty * 0x85EBCA77u;
    h ^= h >> 16;
    h *= 0x7FEB352Du;
    h ^= h >> 15;
    return h;
}

static void draw_floor_detail(
    Canvas* canvas, int col, int row, bool open_biome, uint32_t h) {
    int variant = (int)(h & 3u);
    /* Subtle 0..1 px offsets per tile, from the same hash. */
    col += (int)((h >> 2) & 1u);
    row += (int)((h >> 3) & 1u);

    /* Guard: keep details inside the floor zone strip (just below
     * horizon down to view bottom-1). */
    if(col < 0 || col >= FPV_VIEW_W) return;
    if(row < FPV_HORIZON_Y + 1 || row > FPV_VIEW_H - 2) return;

    if(open_biome) {
        /* Outdoor — grass blade / leaf register. Vertical and
         * V-shaped silhouettes. */
        switch(variant) {
        case 0: /* single blade — two dots vertical */
            canvas_draw_dot(canvas, col, row);
            canvas_draw_dot(canvas, col, row - 1);
            break;
        case 1: /* grass tuft — V */
            canvas_draw_dot(canvas, col - 1, row);
            canvas_draw_dot(canvas, col + 1, row);
            canvas_draw_dot(canvas, col, row - 1);
            break;
        case 2: /* leaning blade */
            canvas_draw_dot(canvas, col, row);
            canvas_draw_dot(canvas, col + 1, row - 1);
            break;
        case 3: /* scatter pair — two leaves */
            canvas_draw_dot(canvas, col - 1, row);
            canvas_draw_dot(canvas, col + 1, row + 1);
            break;
        }
    } else {
        /* Cavern — slate / pebble / crack register. Angular shapes. */
        switch(variant) {
        case 0: /* single pebble */
            canvas_draw_dot(canvas, col, row);
            break;
        case 1: /* slate corner — L */
            canvas_draw_dot(canvas, col, row);
            canvas_draw_dot(canvas, col + 1, row);
            canvas_draw_dot(canvas, col, row + 1);
            break;
        case 2: /* crack — short diagonal */
            canvas_draw_dot(canvas, col - 1, row);
            canvas_draw_dot(canvas, col, row);
            canvas_draw_dot(canvas, col + 1, row + 1);
            break;
        case 3: /* scattered pebbles */
            canvas_draw_dot(canvas, col, row);
            canvas_draw_dot(canvas, col + 2, row + 1);
            break;
        }
    }
}

static void render_floor_detail_pass(
    Canvas* canvas, const World* world,
    int player_x, int player_y, uint8_t facing, bool open_biome) {
    int fdx = fpv_facing_dx(facing);
    int fdy = fpv_facing_dy(facing);
    int rdx = -fdy;   /* perpendicular right of facing */
    int rdy = fdx;

    /* Iterate the visible cone: forward 1..5 tiles, sideways ±fwd. The
     * FOV cone narrows the actually-visible set; out-of-FOV columns are
     * filtered by the projection check below. */
    for(int fwd = 1; fwd <= 5; fwd++) {
        for(int side = -fwd; side <= fwd; side++) {
            int tx = player_x + fdx * fwd + rdx * side;
            int ty = player_y + fdy * fwd + rdy * side;
            if(tx < 0 || tx >= WORLD_COLS || ty < 0 || ty >= WORLD_ROWS) continue;
            if(world_is_blocking(world->tiles[ty][tx])) continue;

            /* Coarse occlusion: walk a line from player toward tile,
             * sample at each fwd step. Any blocking tile in between =
             * occluded. Approximate but cheap. */
            bool occluded = false;
            for(int t = 1; t < fwd && !occluded; t++) {
                int sn = (side * t) / fwd;
                int cx = player_x + fdx * t + rdx * sn;
                int cy = player_y + fdy * t + rdy * sn;
                if(cx < 0 || cx >= WORLD_COLS || cy < 0 || cy >= WORLD_ROWS) {
                    occluded = true;
                    break;
                }
                if(world_is_blocking(world->tiles[cy][cx])) occluded = true;
            }
            if(occluded) continue;

            /* Project tile center to screen.
             *   col  = W/2 + (side * (W/2) * FP_ONE) / (fwd * PLANE_SCALE)
             *   row  = HORIZON + (WALL_HEIGHT_SCALE / 2) / (fwd * FP_ONE) */
            int col = FPV_VIEW_W / 2 +
                      (side * (FPV_VIEW_W / 2) * FP_ONE) / (fwd * PLANE_SCALE);
            int row = FPV_HORIZON_Y + (WALL_HEIGHT_SCALE / (2 * FP_ONE)) / fwd;
            if(col < 0 || col >= FPV_VIEW_W) continue;

            uint32_t h = tile_hash(tx, ty);
            draw_floor_detail(canvas, col, row, open_biome, h);
        }
    }
}

/* ─── Sprite billboard pass ─────────────────────────────────────────
 *
 * For each visible sprite-bearing tile in the player's forward cone,
 * project to screen, scale by distance, and draw the 32x32 source at
 * the appropriate size. Per-pixel Z-check against per-column wall
 * distance — sprites occluded by closer walls don't draw.
 *
 * Sprite scaling: a 1-tile-tall sprite at distance D (fp) renders at
 * WALL_HEIGHT_SCALE / D pixels — same scale as a 1-tile-tall wall at
 * the same distance. Bottom-aligned to the floor line at that depth.
 *
 * Render after walls (which populate wall_dist[]). Iterate FAR-to-NEAR
 * so closer sprites overdraw farther ones when they overlap.
 */

const uint8_t* fpv_sprite_for_tile(char glyph) {
    switch(glyph) {
    case TILE_VAULT:  return vault_xbm;
    case TILE_DOOR:   return door_xbm;
    case TILE_VENDOR: return you_xbm;       /* humanoid stand-in until vendor sprite */
    /* Loot kinds (mirrors KIND_CATALOG glyphs in loot.c). */
    case '*':         return crystal_xbm;   /* crystal shard */
    case '&':         return fungus_xbm;    /* fungus cap */
    case '!':         return vial_xbm;      /* vial */
    case '(':         return tool_xbm;      /* tool */
    case 'i':         return torch_xbm;     /* torch */
    case 'T':         return chest_xbm;     /* chest */
    case 'u':         return chest_xbm;     /* clay pot — chest fallback */
    default:          return NULL;
    }
}

const uint8_t* fpv_sprite_for_creature_glyph(char glyph) {
    switch(glyph) {
    case 'r': return rat_xbm;
    case 'b': return beetle_xbm;
    case 's': return spider_xbm;
    case 'B': return bat_xbm;
    case 'S': return slime_xbm;
    default:  return NULL;
    }
}

static void draw_billboard(
    Canvas* canvas, const uint8_t* xbm, int cx, int floor_y, int size,
    int sprite_dist_fp, const int* wall_dist) {
    if(size < 4) return;        /* too small — reads as noise */
    if(size > 32) size = 32;    /* sprite is 32x32 native; clip */

    int x0 = cx - size / 2;
    int y0 = floor_y - size;

    for(int dy = 0; dy < size; dy++) {
        int y = y0 + dy;
        if(y < 0 || y >= FPV_VIEW_H) continue;
        int sy_src = (dy * 32) / size;  /* nearest-neighbor downscale */
        for(int dx = 0; dx < size; dx++) {
            int x = x0 + dx;
            if(x < 0 || x >= FPV_VIEW_W) continue;
            /* Z-check: sprite occluded by closer wall? */
            if(wall_dist[x] <= sprite_dist_fp) continue;
            int sx_src = (dx * 32) / size;
            int byte_idx = sy_src * 4 + (sx_src >> 3);
            int bit = sx_src & 7;
            if(xbm[byte_idx] & (1u << bit)) {
                canvas_draw_dot(canvas, x, y);
            }
        }
    }
}

static void render_sprite_pass(
    Canvas* canvas, const World* world,
    int player_x, int player_y, uint8_t facing,
    const Creature* creatures, int creature_count,
    const int* wall_dist) {
    int fdx = fpv_facing_dx(facing);
    int fdy = fpv_facing_dy(facing);
    int rdx = -fdy;
    int rdy = fdx;

    /* Far-to-near so closer sprites overdraw farther ones. */
    for(int fwd = 5; fwd >= 1; fwd--) {
        int sprite_dist_fp = fwd * FP_ONE;
        int center_y = FPV_HORIZON_Y + (WALL_HEIGHT_SCALE / (2 * FP_ONE)) / fwd;
        int sprite_size = (WALL_HEIGHT_SCALE / FP_ONE) / fwd;

        for(int side = -fwd; side <= fwd; side++) {
            int tx = player_x + fdx * fwd + rdx * side;
            int ty = player_y + fdy * fwd + rdy * side;
            if(tx < 0 || tx >= WORLD_COLS || ty < 0 || ty >= WORLD_ROWS) continue;

            char tile = world->tiles[ty][tx];

            /* Pick the sprite. Creature on tile wins over tile feature
             * (a creature standing on a vault is what you see). */
            const uint8_t* sprite = NULL;
            if(creatures && creature_count > 0) {
                for(int i = 0; i < creature_count; i++) {
                    const Creature* c = &creatures[i];
                    if(!c->alive) continue;
                    if(c->x != (uint8_t)tx || c->y != (uint8_t)ty) continue;
                    const Family* f = creature_family(c->family_id);
                    if(f) sprite = fpv_sprite_for_creature_glyph(f->glyph);
                    break;
                }
            }
            if(!sprite) sprite = fpv_sprite_for_tile(tile);
            if(!sprite) continue;

            /* Project tile center to screen column. */
            int center_col = FPV_VIEW_W / 2 +
                             (side * (FPV_VIEW_W / 2) * FP_ONE) /
                                 (fwd * PLANE_SCALE);

            draw_billboard(
                canvas, sprite, center_col, center_y, sprite_size,
                sprite_dist_fp, wall_dist);
        }
    }
}

/* ─── Public entry points ──────────────────────────────────────── */

void render_fpv_demo(Canvas* canvas) {
    /* Demo retains a minimal hardcoded scene for back-compat / visual
     * regression. Just draws a flat corridor and the hearth at fixed
     * mid-distance. Will be replaced with a synthetic test chunk in
     * a follow-up; for now, callers should use render_fpv_world. */
    canvas_clear(canvas);
    /* Draw a fixed wall pattern proving the renderer is alive. */
    for(int c = 0; c < FPV_VIEW_W; c++) {
        int dist = 256 + (c < FPV_VIEW_W / 2 ? c : FPV_VIEW_W - c) * 4;
        int h = WALL_HEIGHT_SCALE / dist;
        if(h > FPV_VIEW_H) h = FPV_VIEW_H;
        int top = FPV_HORIZON_Y - h / 2;
        int bot = top + h;
        for(int y = top; y <= bot; y++) {
            if(y >= 0 && y < FPV_VIEW_H) canvas_draw_dot(canvas, c, y);
        }
    }
    canvas_draw_xbm(canvas, 48, 8, 32, 32, hearth_low_xbm);
}

/* ─── Wall pass v2 — 1-bit depth, edges, stone (2026-10-14) ────────
 *
 * The first wall pass was a flat fill: solid on X-faces, 50% checker on
 * Y-faces, so a wall one tile away read the same as one six away and
 * corners vanished. v2 is drawn the way 1-bit crawlers on the LCDs of the
 * 80s/90s did it:
 *
 *   - EDGES: every wall column gets its top and bottom pixel; a vertical
 *     line marks each corner / depth break (hit tile, face, or distance
 *     jumps between neighbouring columns). Shape comes from line, not fill.
 *   - DARKNESS: an ordered (Bayer 4x4) dither whose density RISES with
 *     distance — the torch lights near stone, the dark takes far stone.
 *     Y-faces sit a step darker, the old side-shade in a softer form.
 *   - STONE: irregular courses + joints in ink, hashed per wall tile so a
 *     wall always looks the same, drawn only when the wall is tall enough
 *     for them to read (else they'd just be noise).
 *
 * Outdoor chunks also get a far ridge on the horizon, hashed from the
 * absolute view direction, so turning in open ground shows new country. */

#ifdef SANCTUM_RPG_HOST_TEST
/* Test hooks (host only): the wall span drawn per column, and an
 * "underpaint" switch that inks the whole view before the passes — if a
 * wall is truly opaque its pixels can't depend on what was under it. */
int fpv_test_wall_top[FPV_VIEW_W];
int fpv_test_wall_bot[FPV_VIEW_W];
int fpv_test_underpaint = 0;
#endif

/* Wall pass v2 tunables (AGENTS.md: no hardcoded tunables). Distances are
 * 8.8 fp tile units; densities are ink-per-16 for the Bayer dither. */
#define WALL_DARK_STEPS 6
static const int WALL_DARK_AT[WALL_DARK_STEPS - 1] = {   /* step boundaries */
    FP_ONE * 3 / 2, FP_ONE * 5 / 2, FP_ONE * 4, FP_ONE * 6, FP_ONE * 9};
static const int WALL_DARK_INK[WALL_DARK_STEPS] = {1, 3, 5, 8, 11, 14};
#define WALL_SIDE_DARKER       2    /* Y-faces sit this much darker */
#define WALL_TEXTURE_MIN_H    12    /* px: below this, seams would be noise */
#define STONE_COURSES          3    /* courses per wall tile */
#define STONE_COURSE_JITTER   16    /* ± texture units per course boundary */
#define STONE_JOINT_MIN       40    /* earliest joint position in a course */
#define STONE_JOINT_STAGGER   31    /* per-course joint offset */
#define EDGE_JUMP_DIV         16    /* depth break if |Δperp| ≥ perp/16 */
#define RIDGE_KNOT_PX          8    /* outdoor ridge: knot spacing */
#define RIDGE_MAX_H            6    /* outdoor ridge: tallest peak, px */
#define RIDGE_FILL_INK         2    /* outdoor ridge: fill density (of 16) */

static const uint8_t BAYER4[4][4] = {
    { 0,  8,  2, 10},
    {12,  4, 14,  6},
    { 3, 11,  1,  9},
    {15,  7, 13,  5},
};

/* Ink density (of 16) for a wall at perpendicular distance `perp` (8.8 fp).
 * DARKNESS, not fog: the torch lights near stone (light fill, seams in ink),
 * and the dark takes it back with distance (denser ink). Y-faces sit one
 * step darker — the old side-shade, kept. */
static int wall_density(int perp, int side) {
    int step = 0;
    while(step < WALL_DARK_STEPS - 1 && perp >= WALL_DARK_AT[step]) step++;
    int d = WALL_DARK_INK[step] + (side == 1 ? WALL_SIDE_DARKER : 0);
    return d > 16 ? 16 : d;
}

/* Is (u, v) — both 0..255 across one wall tile face — on a stone seam?
 * px_u / px_v are how many texture units one screen pixel spans, so seams
 * stay one pixel wide at any distance. */
static bool stone_seam(uint32_t th, int u, int v, int px_u, int px_v) {
    const int course_h = 256 / STONE_COURSES;
    /* Course boundaries, each jittered per tile. */
    for(int k = 1; k < STONE_COURSES; k++) {
        int jit = (int)((th >> (k * 5)) % (2 * STONE_COURSE_JITTER)) - STONE_COURSE_JITTER;
        int dv = v - (k * course_h + jit);
        if(dv < 0) dv = -dv;
        if(dv * 2 < px_v + 2) return true;
    }
    /* One joint per course, staggered so joints never line up. */
    int course = v / course_h;
    if(course >= STONE_COURSES) course = STONE_COURSES - 1;
    int joint = (STONE_JOINT_MIN + (int)((th >> (course * 7 + 3)) & 127) +
                 course * STONE_JOINT_STAGGER) & 255;
    int du = u - joint;
    if(du < 0) du = -du;
    return du * 2 < px_u + 2;
}

static void draw_wall_column(
    Canvas* canvas, int c, int wall_h, int perp, int side, int u,
    uint32_t th, bool edge) {
    int top = FPV_HORIZON_Y - wall_h / 2;
    int bot = top + wall_h - 1;
    int y0 = top < 0 ? 0 : top;
    int y1 = bot >= FPV_VIEW_H ? FPV_VIEW_H - 1 : bot;
    int dens = wall_density(perp, side);
    bool textured = wall_h >= WALL_TEXTURE_MIN_H;
    /* Texture units per screen pixel: vertical from the wall height;
     * horizontal from distance (a wall tile spans ~W/(2·tan·perp) px). */
    int px_v = 256 / (wall_h > 0 ? wall_h : 1);
    int px_u = (perp * 2 * PLANE_SCALE) / (FPV_VIEW_W * FP_ONE / 256);
    px_u /= 256;
    if(px_u < 1) px_u = 1;
    for(int y = y0; y <= y1; y++) {
        bool ink;
        if(edge || y == top || y == bot) {
            ink = true;
        } else if(textured &&
                  stone_seam(th, u, ((y - top) * 256) / wall_h, px_u, px_v)) {
            ink = true;                       /* torch-lit stone shows its joints */
        } else {
            ink = BAYER4[y & 3][c & 3] < dens;
        }
        /* OPAQUE: a wall owns every pixel it covers. Dither gaps are written
         * as background, not skipped — skipping them let the horizon, ridge
         * and floor detail drawn earlier bleed through the stone. */
        if(!ink) canvas_set_color(canvas, ColorWhite);
        canvas_draw_dot(canvas, c, y);
        if(!ink) canvas_set_color(canvas, ColorBlack);
    }
#ifdef SANCTUM_RPG_HOST_TEST
    fpv_test_wall_top[c] = y0;
    fpv_test_wall_bot[c] = y1;
#endif
}

/* Far ridge for open biomes: a 1D hashed profile over absolute view
 * columns (facing * W + c), smoothed between knots every 8 columns. */
static int ridge_height(uint8_t facing, int c) {
    int g = (int)(facing & 3u) * FPV_VIEW_W + c;
    int knots = 4 * FPV_VIEW_W / RIDGE_KNOT_PX;          /* wraps all the way round */
    int k = g / RIDGE_KNOT_PX, f = g % RIDGE_KNOT_PX;
    int ha = 1 + (int)(tile_hash(k % knots, 0x51D6E) % (uint32_t)RIDGE_MAX_H);
    int hb = 1 + (int)(tile_hash((k + 1) % knots, 0x51D6E) % (uint32_t)RIDGE_MAX_H);
    return ha + ((hb - ha) * f) / RIDGE_KNOT_PX;
}

void render_fpv_world(
    Canvas* canvas,
    const World* world,
    int player_x, int player_y,
    uint8_t facing,
    const Creature* creatures, int creature_count) {
    canvas_clear(canvas);
    if(!world) return;
#ifdef SANCTUM_RPG_HOST_TEST
    for(int c = 0; c < FPV_VIEW_W; c++) fpv_test_wall_top[c] = -1, fpv_test_wall_bot[c] = -2;
    if(fpv_test_underpaint)
        for(int y = 0; y < FPV_VIEW_H; y++)
            for(int c = 0; c < FPV_VIEW_W; c++) canvas_draw_dot(canvas, c, y);
#endif

    /* Player position in 8.8 fixed-point — tile center. */
    int px_fp = (player_x << 8) + (FP_ONE / 2);
    int py_fp = (player_y << 8) + (FP_ONE / 2);

    /* In OPEN biomes (outdoor), chunk edges are walkable transitions;
     * the ray running off-grid is NOT a wall. We must not draw a wall
     * column there, or the player sees walls where they can walk through.
     * In WALLED biomes (cavern), the perimeter is TILE_WALL and the ray
     * never reaches off-grid before hitting that wall. */
    bool open_biome = (biome_terrain(world->biome) == TERRAIN_OPEN);

    /* Step 1: floor detail pass — sparse biome-specific dots in the
     * floor zone, anchored at each visible tile's projected center.
     * Drawn FIRST so the wall pass naturally overdraws (Z-correct by
     * paint order). */
    render_floor_detail_pass(canvas, world, player_x, player_y, facing, open_biome);

    /* Step 2: horizon baseline — a thin line at HORIZON_Y across the
     * whole view. Provides visual orientation when no walls fill the
     * column (open outdoor space). The wall raycast pass below
     * overdraws this where walls exist, so cavern interiors look
     * exactly as before, while open outdoor reads as "horizon
     * visible" instead of "renderer is dead". */
    for(int c = 0; c < FPV_VIEW_W; c++) {
        canvas_draw_dot(canvas, c, FPV_HORIZON_Y);
        if(open_biome) {
            /* Far ridge: outline + sparse fill down to the horizon. */
            int rh = ridge_height(facing, c);
            canvas_draw_dot(canvas, c, FPV_HORIZON_Y - rh);
            for(int y = FPV_HORIZON_Y - rh + 1; y < FPV_HORIZON_Y; y++)
                if(BAYER4[y & 3][c & 3] < RIDGE_FILL_INK) canvas_draw_dot(canvas, c, y);
        }
    }

    /* Step 3: per-column ray cast — walls. Per-column wall perpendicular
     * distance saved into wall_dist[] for the sprite pass's Z-check.
     * Columns with no wall (off-grid in open biome) get INT_MAX so any
     * sprite beats them — the sprite IS visible past the chunk edge. */
    int wall_dist[FPV_VIEW_W];
    int prev_hx = -99, prev_hy = -99, prev_side = -1, prev_perp = 0;
    for(int c = 0; c < FPV_VIEW_W; c++) {
        int rdx, rdy;
        ray_dir_for_column(facing, c, &rdx, &rdy);

        int hit_x, hit_y, side;
        bool off_grid = false;
        int perp = cast_ray(
            world, px_fp, py_fp, rdx, rdy, &hit_x, &hit_y, &side, &off_grid);

        if(off_grid && open_biome) {
            wall_dist[c] = 0x7FFFFFFF; /* no wall here — sprites pass through */
            prev_hx = -99;
            continue;
        }
        wall_dist[c] = perp;

        int wall_h = WALL_HEIGHT_SCALE / perp;
        if(wall_h > FPV_VIEW_H * 4) wall_h = FPV_VIEW_H * 4;
        if(wall_h < 1) wall_h = 1;

        /* Where along the face the ray landed (0..255): the hit point is
         * p + perp·rd (rd's forward component is FP_ONE). */
        int u = (side == 0)
            ? (py_fp + (int)(((int64_t)perp * rdy) / FP_ONE)) & 0xFF
            : (px_fp + (int)(((int64_t)perp * rdx) / FP_ONE)) & 0xFF;

        /* A corner / depth break: the neighbour hit another tile or face,
         * or its distance jumps by more than ~6%. The line goes on the
         * nearer of the two columns, so it hugs the foreground edge. */
        bool edge = false;
        if(prev_hx != -99 &&
           (hit_x != prev_hx || hit_y != prev_hy || side != prev_side)) {
            int jump = perp - prev_perp;
            if(jump < 0) jump = -jump;
            bool same_face_seam = (side == prev_side) && jump * EDGE_JUMP_DIV < perp;
            edge = !same_face_seam || jump * EDGE_JUMP_DIV >= perp;
            if(edge && prev_perp < perp && c > 0) {
                /* previous column is nearer: mark it instead */
                int ph = WALL_HEIGHT_SCALE / prev_perp;
                if(ph > FPV_VIEW_H * 4) ph = FPV_VIEW_H * 4;
                int pt = FPV_HORIZON_Y - ph / 2, pb = pt + ph - 1;
                if(pt < 0) pt = 0;
                if(pb >= FPV_VIEW_H) pb = FPV_VIEW_H - 1;
                for(int y = pt; y <= pb; y++) canvas_draw_dot(canvas, c - 1, y);
                edge = false;
            }
        }
        prev_hx = hit_x; prev_hy = hit_y; prev_side = side; prev_perp = perp;

        draw_wall_column(canvas, c, wall_h, perp, side, u,
                         tile_hash(hit_x * 2 + side, hit_y), edge);
    }

    /* Step 4: sprite billboard pass — vault, doors, vendor, loot,
     * creatures. Each is placed at world-tile position, projected to
     * screen, scaled by distance, Z-checked per pixel against
     * wall_dist[]. */
    render_sprite_pass(
        canvas, world, player_x, player_y, facing,
        creatures, creature_count, wall_dist);
}
