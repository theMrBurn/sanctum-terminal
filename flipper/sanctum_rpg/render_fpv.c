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

static int cast_ray(
    const World* world,
    int px_fp, int py_fp,  /* player position in 8.8 fp tile units */
    int rdx, int rdy,
    int* out_hit_x, int* out_hit_y, int* out_side) {

    int map_x = px_fp >> 8;
    int map_y = py_fp >> 8;

    /* delta_dist_X = |1 / rdx| in fixed-point. Distance the ray
     * travels (in fp units) to cross one full tile in X. */
    int abs_rdx = rdx < 0 ? -rdx : rdx;
    int abs_rdy = rdy < 0 ? -rdy : rdy;
    int delta_dist_x = (abs_rdx == 0) ? 0x7FFFFFFF : (FP_ONE * FP_ONE) / abs_rdx;
    int delta_dist_y = (abs_rdy == 0) ? 0x7FFFFFFF : (FP_ONE * FP_ONE) / abs_rdy;

    int step_x, step_y;
    int side_dist_x, side_dist_y;

    /* Initial side distance — how far along the ray until we cross the
     * first grid line in X (or Y). */
    if(rdx < 0) {
        step_x = -1;
        side_dist_x = ((px_fp - (map_x << 8)) * delta_dist_x) / FP_ONE;
    } else {
        step_x = 1;
        side_dist_x = (((map_x + 1) << 8) - px_fp) * delta_dist_x / FP_ONE;
    }
    if(rdy < 0) {
        step_y = -1;
        side_dist_y = ((py_fp - (map_y << 8)) * delta_dist_y) / FP_ONE;
    } else {
        step_y = 1;
        side_dist_y = (((map_y + 1) << 8) - py_fp) * delta_dist_y / FP_ONE;
    }

    int side = 0;
    bool hit = false;
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

    /* Perpendicular distance — fish-eye-corrected. */
    int perp;
    if(side == 0) {
        perp = ((((map_x << 8) - px_fp) + (step_x < 0 ? FP_ONE : 0)) * FP_ONE) / (rdx == 0 ? 1 : rdx);
        if(perp < 0) perp = -perp;
    } else {
        perp = ((((map_y << 8) - py_fp) + (step_y < 0 ? FP_ONE : 0)) * FP_ONE) / (rdy == 0 ? 1 : rdy);
        if(perp < 0) perp = -perp;
    }
    if(perp < 1) perp = 1;
    return perp;
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

void render_fpv_world(
    Canvas* canvas,
    const World* world,
    int player_x, int player_y,
    uint8_t facing,
    const Creature* creatures, int creature_count) {
    canvas_clear(canvas);
    (void)creatures;       /* sprites land in C3b */
    (void)creature_count;

    if(!world) return;

    /* Player position in 8.8 fixed-point — tile center. */
    int px_fp = (player_x << 8) + (FP_ONE / 2);
    int py_fp = (player_y << 8) + (FP_ONE / 2);

    /* Per-column ray cast. */
    for(int c = 0; c < FPV_VIEW_W; c++) {
        int rdx, rdy;
        ray_dir_for_column(facing, c, &rdx, &rdy);

        int hit_x, hit_y, side;
        int perp = cast_ray(world, px_fp, py_fp, rdx, rdy, &hit_x, &hit_y, &side);

        /* Wall column height. Clamp to view height. */
        int wall_h = WALL_HEIGHT_SCALE / perp;
        if(wall_h > FPV_VIEW_H) wall_h = FPV_VIEW_H;
        if(wall_h < 1) wall_h = 1;

        int top_y = FPV_HORIZON_Y - wall_h / 2;
        int bot_y = top_y + wall_h - 1;
        if(top_y < 0) top_y = 0;
        if(bot_y >= FPV_VIEW_H) bot_y = FPV_VIEW_H - 1;

        /* Side cue: horizontal-grid hits (side==0) draw solid; vertical
         * (side==1) draw dithered. The dither gives corners and wall-
         * face turns visual contrast — without it, all walls read the
         * same. Mono 1-bit equivalent of DOOM's "darker for one side". */
        if(side == 0) {
            for(int y = top_y; y <= bot_y; y++) canvas_draw_dot(canvas, c, y);
        } else {
            for(int y = top_y; y <= bot_y; y++) {
                if(((y + c) & 1) == 0) canvas_draw_dot(canvas, c, y);
            }
        }
    }

    /* Floor / ceiling: leave blank in this commit. A future polish
     * pass will add light horizontal-distance dither so floor + ceiling
     * have texture; keeping it empty now reads as "void" but proves the
     * walls in isolation. */
}
