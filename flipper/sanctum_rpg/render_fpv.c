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
    }

    /* Step 3: per-column ray cast — walls. */
    for(int c = 0; c < FPV_VIEW_W; c++) {
        int rdx, rdy;
        ray_dir_for_column(facing, c, &rdx, &rdy);

        int hit_x, hit_y, side;
        bool off_grid = false;
        int perp = cast_ray(
            world, px_fp, py_fp, rdx, rdy, &hit_x, &hit_y, &side, &off_grid);

        /* Outdoor + off-grid = walkable edge, not a wall. Leave the
         * column blank (reads as horizon / open void). */
        if(off_grid && open_biome) continue;

        /* Wall column height. Clamp to view height. */
        int wall_h = WALL_HEIGHT_SCALE / perp;
        if(wall_h > FPV_VIEW_H) wall_h = FPV_VIEW_H;
        if(wall_h < 1) wall_h = 1;

        int top_y = FPV_HORIZON_Y - wall_h / 2;
        int bot_y = top_y + wall_h - 1;
        if(top_y < 0) top_y = 0;
        if(bot_y >= FPV_VIEW_H) bot_y = FPV_VIEW_H - 1;

        /* Side cue: horizontal-grid hits (side==0) draw solid; vertical
         * (side==1) draw dithered. */
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
