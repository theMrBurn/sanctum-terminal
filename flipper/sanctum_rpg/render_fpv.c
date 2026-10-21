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
#include "figure.h"
#include "sprites.h"
#include "terrain.h"

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

#ifdef SANCTUM_RPG_HOST_TEST
/* Test hooks (host only): the wall span drawn per column, and an
 * "underpaint" switch that inks the whole view before the passes — if a
 * wall is truly opaque its pixels can't depend on what was under it. */
int fpv_test_wall_top[FPV_VIEW_W];
int fpv_test_wall_bot[FPV_VIEW_W];
int fpv_test_underpaint = 0;
int fpv_test_last_figure_x0, fpv_test_last_figure_y0, fpv_test_last_figure_size = 0;
int fpv_test_masked_billboards = 0;   /* composed billboards drawn (count) */
int fpv_test_wall_mat[FPV_VIEW_W];      /* resolved SlabMaterial per wall column, or FPV_TEST_MAT_HAZE */
#endif

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
        if(terrain_stops_ray(world->tiles[map_y][map_x])) {   /* props are billboards */
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

/* Floor features (TF_FLOOR glyphs) mark the whole tile, not one spot:
 * FLOOR_MARKS marks spread across the tile's width at that depth, each a
 * cluster of >= 2 px (cluster discipline: no lone floor dots). Near tiles
 * get the larger mark. */
#define FLOOR_MARKS      3
#define FLOOR_NEAR_FWD   2    /* fwd at/below which marks are drawn large */

static void floor_mark(Canvas* canvas, int plan, int x, int y, bool near) {
    if(y < FPV_HORIZON_Y + 1 || y > FPV_VIEW_H - 2) return;
    if(plan == TERRAIN_PLAN_MOSS) {           /* a low mound of moss */
        canvas_draw_dot(canvas, x - 1, y);
        canvas_draw_dot(canvas, x, y - 1);
        canvas_draw_dot(canvas, x + 1, y);
        if(near) {
            canvas_draw_dot(canvas, x - 2, y);
            canvas_draw_dot(canvas, x + 1, y - 1);
            canvas_draw_dot(canvas, x + 2, y);
        }
    } else if(plan == TERRAIN_PLAN_FLAG) {    /* a flagstone joint: a long line + a tick */
        int half = near ? 3 : 2;
        for(int dx = -half; dx <= half; dx++) canvas_draw_dot(canvas, x + dx, y);
        canvas_draw_dot(canvas, x, y + 1);
    } else if(plan == TERRAIN_PLAN_RAILS) {   /* a sleeper under two rails */
        int half = near ? 4 : 2;
        for(int dx = -half; dx <= half; dx++) canvas_draw_dot(canvas, x + dx, y);
        canvas_draw_dot(canvas, x - half + 1, y - 1);
        canvas_draw_dot(canvas, x + half - 1, y - 1);
    } else if(plan == TERRAIN_PLAN_GRASS) {   /* tall blades */
        int h = near ? 3 : 2;
        for(int dy = 0; dy < h; dy++) {
            canvas_draw_dot(canvas, x - 1, y - dy);
            canvas_draw_dot(canvas, x + 1, y - dy - 1);
        }
    } else if(plan == TERRAIN_PLAN_PLANKS) {  /* two board seams, staggered */
        int half = near ? 5 : 3;
        for(int dx = -half; dx <= half; dx++) canvas_draw_dot(canvas, x + dx, y);
        for(int dx = -half + 2; dx <= half + 2; dx++) canvas_draw_dot(canvas, x + dx, y + 2);
    } else if(plan == TERRAIN_PLAN_SCREE) {   /* loose stones: flat pebbles */
        canvas_draw_dot(canvas, x, y);
        canvas_draw_dot(canvas, x + 1, y);
        if(near) {
            canvas_draw_dot(canvas, x + 2, y);
            canvas_draw_dot(canvas, x + 1, y - 1);
        }
    }
}

static void draw_floor_feature(
    Canvas* canvas, int col, int row, int fwd, int plan, uint32_t h) {
    int tile_w = (FPV_VIEW_W / 2 * FP_ONE) / (fwd * PLANE_SCALE);
    bool near = fwd <= FLOOR_NEAR_FWD;
    for(int k = 0; k < FLOOR_MARKS; k++) {
        int x = col + ((k - FLOOR_MARKS / 2) * tile_w) / (FLOOR_MARKS + 1);
        int y = row + (int)((h >> (k * 2)) & 1u) - (k & 1);   /* stagger in depth */
        if(x < 2 || x >= FPV_VIEW_W - 2) continue;
        floor_mark(canvas, plan, x, y, near);
    }
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
        case 3: /* double blade */
            canvas_draw_dot(canvas, col - 1, row);
            canvas_draw_dot(canvas, col - 1, row - 1);
            canvas_draw_dot(canvas, col + 1, row);
            canvas_draw_dot(canvas, col + 1, row - 1);
            break;
        }
    } else {
        /* Cavern — slate / pebble / crack register. Angular shapes. */
        switch(variant) {
        case 0: /* flat pebble */
            canvas_draw_dot(canvas, col, row);
            canvas_draw_dot(canvas, col + 1, row);
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
        case 3: /* two pebbles */
            canvas_draw_dot(canvas, col, row);
            canvas_draw_dot(canvas, col + 1, row);
            canvas_draw_dot(canvas, col + 3, row + 1);
            canvas_draw_dot(canvas, col + 4, row + 1);
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
            if(terrain_stops_ray(world->tiles[ty][tx])) continue;

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
                if(terrain_stops_ray(world->tiles[cy][cx])) occluded = true;
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
            const TerrainDef* td = terrain_def(world->tiles[ty][tx]);
            if(td && td->form == TF_FLOOR)
                draw_floor_feature(canvas, col, row, fwd, td->plan, h);
            else
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

/* Draw a 32x32 XBM billboard scaled to `size`, Z-checked per column.
 * OPAQUE: with a `mask`, mask && !ink is written as background, so walls
 * can't show through a body; without one (legacy tile sprites) each row is
 * solid between its outermost inked pixels. `src` = source side in px. */
static void draw_billboard_max(
    Canvas* canvas, const uint8_t* xbm, const uint8_t* mask, int src,
    int cx, int floor_y, int size, int max_size, int sprite_dist_fp, const int* wall_dist) {
    if(size < 4) return;        /* too small — reads as noise */
    if(size > max_size) size = max_size;

    int x0 = cx - size / 2;
    int y0 = floor_y - size;
    int stride = (src + 7) / 8;

    for(int dy = 0; dy < size; dy++) {
        int y = y0 + dy;
        if(y < 0 || y >= FPV_VIEW_H) continue;
        int sy_src = (dy * src) / size;  /* nearest-neighbor */
        /* Legacy tile sprites have no mask: treat each source row as solid
         * between its outermost inked pixels, so they're opaque too. */
        int span_l = src, span_r = -1;
        if(!mask) {
            for(int sx = 0; sx < src; sx++)
                if(xbm[sy_src * stride + (sx >> 3)] & (1u << (sx & 7))) {
                    if(sx < span_l) span_l = sx;
                    span_r = sx;
                }
        }
        for(int dx = 0; dx < size; dx++) {
            int x = x0 + dx;
            if(x < 0 || x >= FPV_VIEW_W) continue;
            /* Z-check: sprite occluded by closer wall? */
            if(wall_dist[x] <= sprite_dist_fp) continue;
            int sx_src = (dx * src) / size;
            int byte_idx = sy_src * stride + (sx_src >> 3);
            uint8_t bit = (uint8_t)(1u << (sx_src & 7));
            if(xbm[byte_idx] & bit) {
                canvas_draw_dot(canvas, x, y);
            } else if(mask ? (mask[byte_idx] & bit) : (sx_src > span_l && sx_src < span_r)) {
                canvas_set_color(canvas, ColorWhite);
                canvas_draw_dot(canvas, x, y);
                canvas_set_color(canvas, ColorBlack);
            }
        }
    }
#ifdef SANCTUM_RPG_HOST_TEST
    if(mask) fpv_test_last_figure_x0 = x0, fpv_test_last_figure_y0 = y0,
             fpv_test_last_figure_size = size, fpv_test_masked_billboards++;
#endif
}

/* One-tile billboards are at most 32 px; a spanning prop scales up to
 * its span (nearest-neighbour), so a 2x2 menhir looms when you're close. */
#define BILLBOARD_MAX_PX 32
static void draw_billboard(
    Canvas* canvas, const uint8_t* xbm, const uint8_t* mask, int src,
    int cx, int floor_y, int size, int sprite_dist_fp, const int* wall_dist) {
    draw_billboard_max(canvas, xbm, mask, src, cx, floor_y, size, BILLBOARD_MAX_PX,
                       sprite_dist_fp, wall_dist);
}

/* Smallest box the composer draws in; billboards below it are composed at
 * this size and sampled down. */
#define FIGURE_MIN_COMPOSE 8

/* How far ahead billboards are looked for. Rays cross a whole chunk, so a
 * prop must be found as far as it is still >= 4 px tall, or it would pop
 * out while the wall behind it still draws. */
#define FPV_SPRITE_RANGE 9

/* Composed props, cached by (glyph, variant, size): terrain doesn't move,
 * so a prop is drawn once per size it appears at, not once per frame. */
#define PROP_CACHE_SLOTS 8
static struct {
    char glyph;
    uint8_t variant, size;
    uint8_t ink[PIXKIT_PLANE_BYTES], mask[PIXKIT_PLANE_BYTES];
} prop_cache[PROP_CACHE_SLOTS];
static int prop_cache_next;

static int prop_planes(char glyph, uint8_t variant, int size, const uint8_t** ink, const uint8_t** mask) {
    for(int i = 0; i < PROP_CACHE_SLOTS; i++)
        if(prop_cache[i].size == size && prop_cache[i].glyph == glyph &&
           prop_cache[i].variant == variant) {
            *ink = prop_cache[i].ink; *mask = prop_cache[i].mask;
            return 1;
        }
    int i = prop_cache_next;
    prop_cache_next = (prop_cache_next + 1) % PROP_CACHE_SLOTS;
    if(!terrain_compose_prop(glyph, variant, size, prop_cache[i].ink, prop_cache[i].mask)) {
        prop_cache[i].size = 0;
        return 0;
    }
    prop_cache[i].glyph = glyph; prop_cache[i].variant = variant; prop_cache[i].size = (uint8_t)size;
    *ink = prop_cache[i].ink; *mask = prop_cache[i].mask;
    return 1;
}

/* Spanning / scaled props (TerrainDef.span or .scale > 1). Scale sets the
 * billboard's size in tiles (a tree stands two tiles tall over the walls);
 * span sets the footprint. A block of the same glyph is ONE
 * thing. Found from the tiles actually present (a clipped block still
 * works), drawn once per frame — the first time ANY of its tiles is
 * visited, so it can't pop when the anchor leaves the cone — at the
 * block's centre, projected with fractional depth. Returns false if the
 * block was already drawn this frame. */
#define SPAN_GROUPS_PER_FRAME 8
typedef struct { uint8_t x, y; } SpanAnchor;

static void span_extent(const World* world, char g, int tx, int ty, int span,
                        int* ax, int* ay, int* w, int* h) {
    int x = tx, y = ty;
    for(int k = 1; k < span && x > 0 && world->tiles[ty][x - 1] == g; k++) x--;
    for(int k = 1; k < span && y > 0 && world->tiles[y - 1][tx] == g; k++) y--;
    int ww = 1, hh = 1;
    while(ww < span && x + ww < WORLD_COLS && world->tiles[y][x + ww] == g) ww++;
    while(hh < span && y + hh < WORLD_ROWS && world->tiles[y + hh][x] == g) hh++;
    *ax = x; *ay = y; *w = ww; *h = hh;
}

static void draw_span_prop(
    Canvas* canvas, const World* world, const TerrainDef* td, int tx, int ty,
    int player_x, int player_y, int fdx, int fdy, int rdx, int rdy,
    SpanAnchor* done, int* n_done, const int* wall_dist) {
    int ax, ay, w, h;
    span_extent(world, td->glyph, tx, ty, td->span, &ax, &ay, &w, &h);
    if(td->span > 1) {   /* only multi-tile blocks need de-duplicating */
        for(int i = 0; i < *n_done; i++)
            if(done[i].x == ax && done[i].y == ay) return;
        if(*n_done < SPAN_GROUPS_PER_FRAME) done[(*n_done)++] = (SpanAnchor){(uint8_t)ax, (uint8_t)ay};
    }

    /* Block centre relative to the player, 8.8 fp tiles. */
    int rx = (ax - player_x) * FP_ONE + (w - 1) * FP_ONE / 2;
    int ry = (ay - player_y) * FP_ONE + (h - 1) * FP_ONE / 2;
    int fwd_fp = rx * fdx + ry * fdy;
    int side_fp = rx * rdx + ry * rdy;
    if(fwd_fp < FP_ONE / 2) return;   /* centre at or behind the eye */

    int floor_y = FPV_HORIZON_Y + (WALL_HEIGHT_SCALE / 2) / fwd_fp;
    int size = (WALL_HEIGHT_SCALE * td->scale) / fwd_fp;
    int center_col = FPV_VIEW_W / 2 + (side_fp * (FPV_VIEW_W / 2) * FP_ONE) / (fwd_fp * PLANE_SCALE);
    int box = size > PIXKIT_MAX_PX ? PIXKIT_MAX_PX : size;
    if(box < FIGURE_MIN_COMPOSE) box = FIGURE_MIN_COMPOSE;
    const uint8_t *pi, *pm;
    if(prop_planes(td->glyph, (uint8_t)(tile_hash(ax, ay) >> 8), box, &pi, &pm))
        draw_billboard_max(canvas, pi, pm, box, center_col, floor_y, size,
                           BILLBOARD_MAX_PX * td->scale, fwd_fp, wall_dist);
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
    SpanAnchor span_done[SPAN_GROUPS_PER_FRAME];
    int span_n = 0;

    /* Far-to-near so closer sprites overdraw farther ones. */
    for(int fwd = FPV_SPRITE_RANGE; fwd >= 1; fwd--) {
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
            /* Project tile center to screen column. */
            int center_col = FPV_VIEW_W / 2 +
                             (side * (FPV_VIEW_W / 2) * FP_ONE) /
                                 (fwd * PLANE_SCALE);

            /* A creature on the tile wins over the tile feature, and is
             * COMPOSED from its data at the size it appears (figure.h). */
            const Creature* cr = NULL;
            for(int i = 0; creatures && i < creature_count; i++) {
                const Creature* c = &creatures[i];
                if(c->alive && c->x == (uint8_t)tx && c->y == (uint8_t)ty) { cr = c; break; }
            }
            if(cr) {
                static uint8_t fig_ink[FIGURE_PLANE_BYTES], fig_mask[FIGURE_PLANE_BYTES];
                RenderBudget b = RENDER_BUDGET_FLIPPER_1BIT;
                int box = sprite_size > FIGURE_MAX_PX ? FIGURE_MAX_PX : sprite_size;
                if(box < FIGURE_MIN_COMPOSE) box = FIGURE_MIN_COMPOSE;
                b.width = b.height = (uint8_t)box;
                /* Stride with position parity: the gait changes as it moves. */
                if(figure_compose(&b, cr->family_id, cr->trait_id,
                                  figure_pose_for_state(cr->state),
                                  (uint8_t)((cr->x + cr->y) & 1), fig_ink, fig_mask)) {
                    draw_billboard(canvas, fig_ink, fig_mask, box, center_col, center_y,
                                   sprite_size, sprite_dist_fp, wall_dist);
                }
                continue;
            }
            /* Terrain props: composed from data (terrain.h), opaque. */
            const TerrainDef* td = terrain_def(tile);
            if(td && td->form == TF_PROP && (td->span > 1 || td->scale > 1)) {
                draw_span_prop(canvas, world, td, tx, ty, player_x, player_y, fdx, fdy,
                               rdx, rdy, span_done, &span_n, wall_dist);
                continue;
            }
            if(td && td->form == TF_PROP) {
                int box = sprite_size > PIXKIT_MAX_PX ? PIXKIT_MAX_PX : sprite_size;
                if(box < FIGURE_MIN_COMPOSE) box = FIGURE_MIN_COMPOSE;
                const uint8_t *pi, *pm;
                if(prop_planes(tile, (uint8_t)(tile_hash(tx, ty) >> 8), box, &pi, &pm))
                    draw_billboard(canvas, pi, pm, box, center_col, center_y, sprite_size,
                                   sprite_dist_fp, wall_dist);
                continue;
            }
            const uint8_t* sprite = fpv_sprite_for_tile(tile);
            if(!sprite) continue;
            draw_billboard(canvas, sprite, NULL, 32, center_col, center_y, sprite_size,
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
#define COLUMN_FLUTES          4    /* carved column: flutes per tile face */
#define COLUMN_CAPITAL_V      28    /* carved column: capital band depth (of 256) */
#define MONOLITH_DARKER        2    /* raw monolith sits darker than coursed stone */
#define MONOLITH_CRACK_WOBBLE 10    /* monolith crack: sideways step per third */
#define BRICK_COURSES          6    /* crypt brick: courses per tile (running bond) */
#define NICHE_U0              72    /* crypt niche: left edge (of 256) */
#define NICHE_U1             184    /* crypt niche: right edge */
#define NICHE_V0              96    /* crypt niche: top */
#define NICHE_V1             168    /* crypt niche: bottom */
#define NICHE_EVERY            3    /* one wall tile face in this many has a niche */
#define TIMBER_POST_U         28    /* mine: post width at the tile's left edge */
#define TIMBER_LINTEL_V       26    /* mine: lintel depth at the top */
#define FRAME_BEAM_U          18    /* manor: post width at each tile edge */
#define FRAME_PLATE_V         18    /* manor: top plate depth */
#define FRAME_RAIL_V         128    /* manor: mid-rail centre */
#define FRAME_RAIL_HALF       10    /* manor: mid-rail half-depth */
#define FRAME_BRACE_HALF      12    /* manor: diagonal brace half-width */
#define ASHLAR_COURSES         3    /* keep: courses of big blocks */
#define SLIT_HALF_U           12    /* keep: arrow slit half-width */
#define SLIT_V0               56    /* keep: slit top */
#define SLIT_V1              200    /* keep: slit bottom */
#define SLIT_EVERY             3    /* keep: one face in this many has a slit */
#define LANCET_HALF_U         26    /* abbey: window half-width */
#define LANCET_SPRING_V      112    /* abbey: where the pointed arch springs */
#define LANCET_V1            216    /* abbey: window sill */
#define LANCET_EVERY           2    /* abbey: one face in this many has a window */
#define EARTH_TURF_V          44    /* mound: where the turf meets the earth */
#define EARTH_TURF_WOBBLE      6    /* mound: turf line rise and fall */
#define EARTH_ROOT_LEN        22    /* mound: roots hanging below the turf */
#define EARTH_ROOT_PITCH      48    /* mound: one root in this many u */
#define EARTH_STONE_R         14    /* mound: a stone in the earth, smallest radius */
#define EARTH_STONE_GROW      12    /* mound: ...plus up to this much */
#define EARTH_STONES           3    /* mound: stones per face */
#define EARTH_DARKER           1    /* mound: earth sits a little darker than stone */

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

/* The face's line work by material: coursed stone (courses + joints), a
 * carved column (flutes + a capital band), or a raw monolith (one long
 * crack, no courses). Same one-pixel seam rule for all. */
static bool surface_seam(SlabMaterial mat, uint32_t th, int u, int v, int px_u, int px_v) {
    switch(mat) {
    case TM_COLUMN: {
        int dv = v - COLUMN_CAPITAL_V;
        if(dv < 0) dv = -dv;
        if(dv * 2 < px_v + 2) return true;
        if(v < COLUMN_CAPITAL_V) return false;
        int pitch = 256 / COLUMN_FLUTES, du = (u % pitch) - pitch / 2;
        if(du < 0) du = -du;
        return du * 2 < px_u + 2;
    }
    case TM_BRICK: {
        if(th % NICHE_EVERY == 0 && u >= NICHE_U0 && u <= NICHE_U1 &&
           v >= NICHE_V0 && v <= NICHE_V1)
            return true;                              /* a burial niche: a dark recess */
        const int course_h = 256 / BRICK_COURSES;
        int dv = v % course_h;
        if(dv * 2 < px_v + 2) return true;            /* bed joint */
        int course = v / course_h;
        int du = (u + (course & 1) * 64) % 128;       /* head joints, half-bond */
        return du * 2 < px_u + 2;
    }
    case TM_TIMBER:
        if(u < TIMBER_POST_U || v < TIMBER_LINTEL_V) return true;   /* the shoring */
        return stone_seam(th, u, v, px_u, px_v);
    case TM_FRAME: {                                  /* timber frame; plaster panels */
        if(u < FRAME_BEAM_U / 2 || u > 255 - FRAME_BEAM_U / 2 || v < FRAME_PLATE_V) return true;
        int dr = v - FRAME_RAIL_V;
        if(dr < 0) dr = -dr;
        if(dr < FRAME_RAIL_HALF) return true;
        if(v > FRAME_RAIL_V) {                        /* a brace in the lower panel, alternating */
            int along = FRAME_BEAM_U + ((v - FRAME_RAIL_V) * (256 - 2 * FRAME_BEAM_U)) / (256 - FRAME_RAIL_V);
            if(th & 1) along = 255 - along;
            int db = u - along;
            if(db < 0) db = -db;
            if(db < FRAME_BRACE_HALF) return true;
        }
        return false;
    }
    case TM_ASHLAR: {                                 /* big blocks; a slit on some faces */
        int du = u - 128;
        if(du < 0) du = -du;
        if(th % SLIT_EVERY == 0 && du < SLIT_HALF_U && v > SLIT_V0 && v < SLIT_V1) return true;
        const int course_h = 256 / ASHLAR_COURSES;
        int dv = v % course_h;
        if(dv * 2 < px_v + 2) return true;
        int joint = ((v / course_h) & 1) ? 128 : 0;
        int dj = (u - joint) & 255;
        if(dj > 128) dj = 256 - dj;
        return dj * 2 < px_u + 2;
    }
    case TM_CARVED: {                                 /* smooth stone; a pointed window */
        if(th % LANCET_EVERY != 0 || v > LANCET_V1) return false;
        int du = u - 128;
        if(du < 0) du = -du;
        if(du > LANCET_HALF_U) return false;
        if(v >= LANCET_SPRING_V) return true;
        /* above the springing line the sides lean in to a point: full
         * width at the spring, zero at the apex 2 half-widths higher */
        int apex = LANCET_SPRING_V - 2 * LANCET_HALF_U;
        return v > apex && du * 2 < v - apex;
    }
    case TM_EARTH: {                                  /* earth under turf; roots; stones */
        int wob = (int)(((uint32_t)(u / 32) * 37u + th) % (2 * EARTH_TURF_WOBBLE + 1)) - EARTH_TURF_WOBBLE;
        int turf = EARTH_TURF_V + wob, dt = v - turf;
        if(dt < 0) dt = -dt;
        if(dt * 2 < px_v + 2) return true;            /* the turf line */
        if(v < turf) return false;                    /* the turf itself: plain */
        int ru = (u + (int)(th % EARTH_ROOT_PITCH)) % EARTH_ROOT_PITCH;
        if(v < turf + EARTH_ROOT_LEN - (int)(th >> 5) % 8 && ru * 2 < px_u + 2) return true;   /* a root */
        for(int k = 0; k < EARTH_STONES; k++) {       /* stones packed in the earth */
            uint32_t sh = th * (2654435761u + (uint32_t)k * 40503u);
            int cu = 24 + (int)((sh >> 4) % 208u);
            int cv = turf + 36 + (int)((sh >> 12) % (uint32_t)(212 - turf));
            int du = u - cu, dv = v - cv;
            int r = EARTH_STONE_R + (int)((sh >> 20) % EARTH_STONE_GROW);
            int d2 = du * du + dv * dv, w = px_u > px_v ? px_u : px_v;
            if(d2 >= r * r && d2 < (r + w + 1) * (r + w + 1)) return true;
        }
        return false;
    }
    case TM_MONOLITH: {
        int crack = 64 + (int)(th % 128) + ((v * 3 / 256) & 1) * MONOLITH_CRACK_WOBBLE;
        int du = u - crack;
        if(du < 0) du = -du;
        return du * 2 < px_u + 2;
    }
    default:
        return stone_seam(th, u, v, px_u, px_v);
    }
}

/* The haze on an edge closed by corruption (spec 58 §58.4): a column as
 * tall as a wall would be at `perp`, inked sparsely so it reads as fog,
 * not stone, with slow horizontal wisps. Opaque like a wall: the gaps are
 * written as background, so nothing beyond the edge shows. */
#define HAZE_INK        2   /* of 16 (Bayer): the fog's base density */
#define HAZE_WISP_EVERY 5   /* a wisp row every N rows */
#define HAZE_WISP_LEN   5   /* wisp dash length (of 8) */
static void draw_haze_column(Canvas* canvas, int c, int perp) {
    int h = WALL_HEIGHT_SCALE / (perp > 0 ? perp : 1);
    if(h > FPV_VIEW_H * 4) h = FPV_VIEW_H * 4;
    int top = FPV_HORIZON_Y - h / 2, bot = top + h - 1;
    if(top < 0) top = 0;
    if(bot >= FPV_VIEW_H) bot = FPV_VIEW_H - 1;
    for(int y = top; y <= bot; y++) {
        bool ink = BAYER4[y & 3][c & 3] < HAZE_INK ||
                   (y % HAZE_WISP_EVERY == 0 && ((c + y * 3) & 7) < HAZE_WISP_LEN);
        if(!ink) canvas_set_color(canvas, ColorWhite);
        canvas_draw_dot(canvas, c, y);
        if(!ink) canvas_set_color(canvas, ColorBlack);
    }
#ifdef SANCTUM_RPG_HOST_TEST
    fpv_test_wall_top[c] = top;
    fpv_test_wall_bot[c] = bot;
    fpv_test_wall_mat[c] = FPV_TEST_MAT_HAZE;
#endif
}

static void draw_wall_column(
    Canvas* canvas, int c, int wall_h, int perp, int side, int u,
    uint32_t th, bool edge, SlabMaterial mat) {
    int top = FPV_HORIZON_Y - wall_h / 2;
    int bot = top + wall_h - 1;
    int y0 = top < 0 ? 0 : top;
    int y1 = bot >= FPV_VIEW_H ? FPV_VIEW_H - 1 : bot;
    int dens = wall_density(perp, side) + (mat == TM_MONOLITH ? MONOLITH_DARKER : 0) +
               (mat == TM_EARTH ? EARTH_DARKER : 0);
    if(dens > 16) dens = 16;
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
                  surface_seam(mat, th, u, ((y - top) * 256) / wall_h, px_u, px_v)) {
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
    for(int c = 0; c < FPV_VIEW_W; c++) fpv_test_wall_top[c] = -1, fpv_test_wall_bot[c] = -2, fpv_test_wall_mat[c] = -1;
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
    bool open_biome = (world_terrain(world) == TERRAIN_OPEN);

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

        /* A ray leaving through an edge closed by corruption meets the haze
         * (spec 58 §58.4): a sparse dithered veil at the edge, which also
         * hides whatever lies past it. */
        if(off_grid && world->closed_edges) {
            int e = hit_y < 0 ? WORLD_SEAM_N : hit_y >= WORLD_ROWS ? WORLD_SEAM_S
                  : hit_x < 0 ? WORLD_SEAM_W : WORLD_SEAM_E;
            if(world->closed_edges & (1u << e)) {
                wall_dist[c] = perp;
                draw_haze_column(canvas, c, perp);
                prev_hx = -99;
                continue;
            }
        }
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

        SlabMaterial mat = off_grid ? TM_STYLE_WALL : terrain_material(world->tiles[hit_y][hit_x]);
        /* A seam wall (and a secret in it) is the neighbour's: its material. */
        if(mat == TM_STYLE_WALL)
            mat = (SlabMaterial)STYLE_TABLE[world_wall_style(world, hit_x, hit_y)].wall_material;
#ifdef SANCTUM_RPG_HOST_TEST
        fpv_test_wall_mat[c] = (int)mat;
#endif
        draw_wall_column(canvas, c, wall_h, perp, side, u,
                         tile_hash(hit_x * 2 + side, hit_y), edge, mat);
    }

    /* Step 4: sprite billboard pass — vault, doors, vendor, loot,
     * creatures. Each is placed at world-tile position, projected to
     * screen, scaled by distance, Z-checked per pixel against
     * wall_dist[]. */
    render_sprite_pass(
        canvas, world, player_x, player_y, facing,
        creatures, creature_count, wall_dist);
}
