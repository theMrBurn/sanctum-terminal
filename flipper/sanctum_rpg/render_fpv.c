/*
 * render_fpv.c — Etrian-style first-person renderer.
 *
 * Layout (128x64 screen, status strip reserved at the bottom):
 *
 *   y=0  ┌─────────────────────────────────┐
 *        │ vanishing point at (64, 24)     │
 *        │                                 │
 *        │       perspective view          │
 *        │       (height 48 px)            │
 *        │                                 │
 *   y=48 ├─────────────────────────────────┤
 *        │ status line (same as world view)│
 *   y=63 └─────────────────────────────────┘
 *
 * Walls converge to the central vanishing point. Five depth slots:
 *   depth 0  near (player tile)        — wall segments at screen edges
 *   depth 1  mid-near                  — sprite at ~24x24
 *   depth 2  mid                       — sprite at ~20x20
 *   depth 3  mid-far                   — sprite at ~16x16
 *   depth 4  far / horizon             — sprite at ~12x12
 *
 * Sprites in this slice (demo): a hearth at depth 2 (mid), a vault to
 * the east (off-frame for the demo; future commit places it via the
 * side-cell logic).
 *
 * Hand-drawn jitter: each wall line gets a 1-px deterministic per-row
 * offset so walls don't read as CAD — Sable register.
 */

#include "render_fpv.h"

#include <gui/canvas.h>

#include "sprites.h"

#define FPV_VIEW_W      128
#define FPV_VIEW_H       48   /* leaves 16 px for status strip (matches world view) */

/* Perspective frame — narrower than the full screen to tame the
 * fisheye / force-perspective squeeze (playtest 2026-06-03e v1: "a
 * bit wide in the force perspective"). The viewport sits inside a
 * margin on each side; the player reads the margins as "I cannot see
 * further to the side from this facing." Etrian's classic framed
 * perspective lives in this same negative space. */
#define FPV_FRAME_X0    16   /* left edge of perspective frame */
#define FPV_FRAME_X1    111  /* right edge (inclusive) — 96-px-wide viewport */
#define FPV_FRAME_Y0     2
#define FPV_FRAME_Y1    45

#define FPV_VANISH_X     64
/* Vanishing point pulled up slightly — gives the floor more screen
 * area than the ceiling, reads as "looking forward" not "floating". */
#define FPV_VANISH_Y     18

/* Depth-slot wall extents — the trapezoid inset at each depth. Each
 * pair is (x_offset_from_center, y_offset_from_vanishing) — the wall's
 * inner corner at that depth. depth 0 is the frame edge; depth 4 is
 * nearly the vanishing point. Tuned for ~70° apparent FOV. */
static const int8_t depth_x_inset[5] = { 48, 36, 26, 16,  8 };
static const int8_t depth_y_inset[5] = { 22, 17, 12,  8,  4 };

/* Sprite scales per depth — how big the sprite renders. Bumped at near
 * depths so foreground entities dominate the framed viewport. */
static const uint8_t depth_sprite_size[5] = { 32, 28, 24, 18, 12 };

/* Soft jitter per row — purely deterministic. Adds Sable-register
 * hand-drawn feel; replaces pure-geometric look. */
static int row_jitter(int row) {
    /* Cheap deterministic pseudo-random in [-1, +1] from row index. */
    uint32_t h = (uint32_t)row * 2654435761u;
    h ^= h >> 16;
    int v = (int)(h & 3u) - 1; /* in [-1, +2], close enough */
    if(v > 1) v = 1;
    return v;
}

/* Draw a single line from (x0,y0) to (x1,y1) but offset each pixel by
 * deterministic jitter to give the hand-drawn feel. Bresenham-style. */
static void draw_jittered_line(Canvas* canvas, int x0, int y0, int x1, int y1) {
    int dx = x1 - x0;
    int dy = y1 - y0;
    int adx = dx < 0 ? -dx : dx;
    int ady = dy < 0 ? -dy : dy;
    int steps = adx > ady ? adx : ady;
    if(steps == 0) return;
    for(int i = 0; i <= steps; i++) {
        int x = x0 + (dx * i) / steps;
        int y = y0 + (dy * i) / steps;
        /* Jitter only every few px so the line still reads as a line. */
        if((i & 3) == 0) {
            int j = row_jitter(i + x0 * 7 + y0 * 13);
            /* Jitter perpendicular to the dominant axis. */
            if(adx > ady) y += j;
            else          x += j;
        }
        if(x >= 0 && x < FPV_VIEW_W && y >= 0 && y < FPV_VIEW_H) {
            canvas_draw_dot(canvas, x, y);
        }
    }
}

/* Draw a sprite centered at (cx, cy) at the depth's sprite size. For
 * sizes equal to 32, draws the raw 32x32 XBM. For smaller sizes, the
 * first pass scales naively by skipping rows/columns — simple but
 * acceptable for the prototype. (Pixel-perfect downscaling is a future
 * commit; right now we just want the silhouette readable.) */
static void draw_sprite_at_depth(
    Canvas* canvas, const uint8_t* xbm, int cx, int cy, uint8_t size) {
    if(size >= 32) {
        canvas_draw_xbm(canvas, cx - 16, cy - 16, 32, 32, xbm);
        return;
    }
    /* Downscale by 32/size — draw only every (32/size)-th pixel. Crude
     * but readable; the silhouette survives. */
    int draw_x = cx - size / 2;
    int draw_y = cy - size / 2;
    for(int dy = 0; dy < size; dy++) {
        int sy = (dy * 32) / size;
        for(int dx = 0; dx < size; dx++) {
            int sx = (dx * 32) / size;
            /* Read XBM bit at (sx, sy). LSB-first per byte. */
            int byte_idx = sy * 4 + (sx >> 3);
            int bit = sx & 7;
            if(xbm[byte_idx] & (1 << bit)) {
                int x = draw_x + dx;
                int y = draw_y + dy;
                if(x >= 0 && x < FPV_VIEW_W && y >= 0 && y < FPV_VIEW_H) {
                    canvas_draw_dot(canvas, x, y);
                }
            }
        }
    }
}

/* Facing helpers. */

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

/* Per-tile sprite lookup — which 32x32 XBM (if any) represents a given
 * world tile glyph in FPV. NULL = render as floor (no sprite). Walls /
 * doors are handled by the perspective itself (back wall + clear
 * opening), not a sprite. */
static const uint8_t* sprite_for_tile(char glyph) {
    switch(glyph) {
    case TILE_VAULT:  return vault_xbm;
    /* TILE_HEARTH glyph isn't defined yet (slice C2 — Sanctum chunk).
     * Future: case TILE_HEARTH: return hearth_low_xbm; */
    case TILE_VENDOR: /* fall-through: vendor uses no sprite yet — drawn
                       * as a wireframe shape by the perspective when
                       * the per-kind table lands in C3. */
    default:          return NULL;
    }
}

/* Draw the perspective frame + convergence lines + depth markers up to
 * `back_depth` (inclusive). The back wall closes the corridor at that
 * depth. Shared by render_fpv_demo and render_fpv_world. */
static void draw_perspective_frame(Canvas* canvas, int back_depth) {
    if(back_depth < 1) back_depth = 1;
    if(back_depth > 4) back_depth = 4;

    /* Frame outline. */
    canvas_draw_frame(
        canvas, FPV_FRAME_X0, FPV_FRAME_Y0,
        FPV_FRAME_X1 - FPV_FRAME_X0 + 1,
        FPV_FRAME_Y1 - FPV_FRAME_Y0 + 1);

    /* Convergence lines from frame corners to vanishing point. */
    draw_jittered_line(canvas, FPV_FRAME_X0, FPV_FRAME_Y0, FPV_VANISH_X, FPV_VANISH_Y);
    draw_jittered_line(canvas, FPV_FRAME_X1, FPV_FRAME_Y0, FPV_VANISH_X, FPV_VANISH_Y);
    draw_jittered_line(canvas, FPV_FRAME_X0, FPV_FRAME_Y1, FPV_VANISH_X, FPV_VANISH_Y);
    draw_jittered_line(canvas, FPV_FRAME_X1, FPV_FRAME_Y1, FPV_VANISH_X, FPV_VANISH_Y);

    /* Depth-marker cross-walls up to (but not including) back_depth. */
    for(int d = 1; d < back_depth; d++) {
        int lx = FPV_VANISH_X - depth_x_inset[d];
        int rx = FPV_VANISH_X + depth_x_inset[d];
        int ty = FPV_VANISH_Y - depth_y_inset[d];
        int by = FPV_VANISH_Y + depth_y_inset[d];
        canvas_draw_line(canvas, lx, ty, rx, ty);
        canvas_draw_line(canvas, lx, by, rx, by);
    }

    /* Back wall at back_depth. */
    int lx = FPV_VANISH_X - depth_x_inset[back_depth];
    int rx = FPV_VANISH_X + depth_x_inset[back_depth];
    int ty = FPV_VANISH_Y - depth_y_inset[back_depth];
    int by = FPV_VANISH_Y + depth_y_inset[back_depth];
    canvas_draw_frame(canvas, lx, ty, rx - lx + 1, by - ty + 1);
}

/* Place a sprite at the given depth slot, bottom-aligned to the floor
 * line at that depth so it reads as standing on the ground. */
static void place_sprite_at_depth(Canvas* canvas, const uint8_t* xbm, int depth) {
    if(depth < 1 || depth > 4) return;
    uint8_t sz = depth_sprite_size[depth];
    int cx = FPV_VANISH_X;
    int floor_y = FPV_VANISH_Y + depth_y_inset[depth];
    int cy = floor_y - sz / 2;
    draw_sprite_at_depth(canvas, xbm, cx, cy, sz);
}

void render_fpv_demo(Canvas* canvas) {
    canvas_clear(canvas);
    draw_perspective_frame(canvas, 4);
    place_sprite_at_depth(canvas, hearth_low_xbm, 1);
}

void render_fpv_world(
    Canvas* canvas,
    const World* world,
    int player_x, int player_y,
    uint8_t facing) {
    canvas_clear(canvas);
    if(!world) {
        draw_perspective_frame(canvas, 4);
        return;
    }

    int fdx = fpv_facing_dx(facing);
    int fdy = fpv_facing_dy(facing);

    /* Sample the forward column at depths 1..4. The corridor terminates
     * (back wall) at the first blocking tile or at depth 4 if all four
     * tiles ahead are open. Doors are walkable but we treat them as a
     * "depth break" so the player sees the doorway frame. */
    char tile_at_depth[5] = {0};
    int back_depth = 4;
    for(int d = 1; d <= 4; d++) {
        int tx = player_x + fdx * d;
        int ty = player_y + fdy * d;
        if(tx < 0 || tx >= WORLD_COLS || ty < 0 || ty >= WORLD_ROWS) {
            /* Off-grid: in an OPEN biome you'd see the chunk boundary
             * (renders as door-like opening). In a WALLED biome, no
             * exit there. Either way: terminate the corridor. */
            back_depth = d;
            tile_at_depth[d] = TILE_WALL;
            break;
        }
        char t = world->tiles[ty][tx];
        tile_at_depth[d] = t;
        if(world_is_blocking(t)) {
            back_depth = d;
            break;
        }
    }

    draw_perspective_frame(canvas, back_depth);

    /* Render sprites for any tile features (vault, future hearth, etc.)
     * along the forward column. Painted back-to-front so closer sprites
     * overdraw farther ones. */
    for(int d = back_depth; d >= 1; d--) {
        const uint8_t* sprite = sprite_for_tile(tile_at_depth[d]);
        if(sprite) place_sprite_at_depth(canvas, sprite, d);
    }
}
