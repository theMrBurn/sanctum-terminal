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
#define FPV_VANISH_X     64
#define FPV_VANISH_Y     24

/* Depth-slot wall extents — the trapezoid inset at each depth. Each
 * pair is (x_offset_from_center, y_offset_from_vanishing) — the wall's
 * inner corner at that depth. depth 0 is the screen edge; depth 4 is
 * nearly the vanishing point. */
static const int8_t depth_x_inset[5] = { 64, 48, 32, 20, 10 };
static const int8_t depth_y_inset[5] = { 24, 18, 12,  7,  4 };

/* Sprite scales per depth — how big the sprite renders. */
static const uint8_t depth_sprite_size[5] = { 32, 28, 22, 16, 10 };

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

void render_fpv_demo(Canvas* canvas) {
    canvas_clear(canvas);

    /* Step 1: floor + ceiling lines converging to vanishing point.
     * These define the "tube" we're standing in. */
    /* Top wall edges (ceiling angle) */
    draw_jittered_line(canvas, 0, 0, FPV_VANISH_X, FPV_VANISH_Y);
    draw_jittered_line(canvas, FPV_VIEW_W - 1, 0, FPV_VANISH_X, FPV_VANISH_Y);
    /* Bottom wall edges (floor angle) */
    draw_jittered_line(canvas, 0, FPV_VIEW_H - 1, FPV_VANISH_X, FPV_VANISH_Y);
    draw_jittered_line(
        canvas, FPV_VIEW_W - 1, FPV_VIEW_H - 1, FPV_VANISH_X, FPV_VANISH_Y);

    /* Step 2: depth-marker cross-walls at each Etrian depth slot. Each
     * is a small trapezoid lip suggesting "this is a tile boundary".
     * Drawn as four short lines at the depth's inset frame. */
    for(int d = 1; d < 4; d++) {
        int lx = FPV_VANISH_X - depth_x_inset[d];
        int rx = FPV_VANISH_X + depth_x_inset[d];
        int ty = FPV_VANISH_Y - depth_y_inset[d];
        int by = FPV_VANISH_Y + depth_y_inset[d];
        /* Top edge of the depth slot */
        canvas_draw_line(canvas, lx, ty, rx, ty);
        /* Bottom edge */
        canvas_draw_line(canvas, lx, by, rx, by);
    }

    /* Step 3: back wall — at depth 4 (deepest), draw a closed
     * rectangle. Gives the "corridor terminates here" feel of the
     * Sanctum interior (one room, not infinite corridor). */
    {
        int lx = FPV_VANISH_X - depth_x_inset[4];
        int rx = FPV_VANISH_X + depth_x_inset[4];
        int ty = FPV_VANISH_Y - depth_y_inset[4];
        int by = FPV_VANISH_Y + depth_y_inset[4];
        canvas_draw_frame(canvas, lx, ty, rx - lx + 1, by - ty + 1);
    }

    /* Step 4: place the hearth sprite at depth 2 (mid). Centered on
     * the vanishing point, slightly elevated so it sits on the floor
     * at the right depth — bottom of sprite at depth 2's floor line. */
    {
        int sz = depth_sprite_size[2];
        int cx = FPV_VANISH_X;
        int cy = FPV_VANISH_Y + depth_y_inset[2] - sz / 2;
        draw_sprite_at_depth(canvas, hearth_ember_xbm, cx, cy, sz);
    }

    /* Step 5: ground a "you-glyph" tease in the lower-center — a tiny
     * silhouette telegraphs the player's presence. Placed at depth 0
     * (foreground), scaled small so it doesn't dominate. */
    /* (Skipped for the first demo — the player is the camera; showing
     * a sprite contradicts the FPV idiom. Left as a deliberate
     * decision so the screen reads as "you are here, looking at this".) */
}
