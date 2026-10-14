/* Host stand-in for the Flipper SDK's <gui/canvas.h> — test/shot.c only.
 *
 * A Canvas here is a 128x64 1-bit framebuffer in RAM, so renderers that
 * draw through the canvas API (render_fpv.c, and later the composer) can run
 * on the Mac and be written out as images. Semantics follow the firmware:
 * pixel 1 = black (lit LCD segment), canvas_clear whites the screen,
 * canvas_draw_xbm draws only SET bits, LSB-first, rows padded to a byte.
 *
 * Only what the renderers call is implemented. Add calls here as needed. */
#pragma once

#include <stddef.h>
#include <stdint.h>
#include <string.h>

#define SHIM_W 128
#define SHIM_H 64

typedef enum { ColorWhite = 0x00, ColorBlack = 0x01, ColorXOR = 0x02 } Color;

typedef struct {
    uint8_t px[SHIM_H][SHIM_W];
    Color color;
} Canvas;

static inline void shim_put(Canvas* c, int32_t x, int32_t y) {
    if(x < 0 || y < 0 || x >= SHIM_W || y >= SHIM_H) return;
    if(c->color == ColorXOR) c->px[y][x] ^= 1;
    else c->px[y][x] = (c->color == ColorBlack);
}

static inline void canvas_clear(Canvas* c) {
    memset(c->px, 0, sizeof(c->px));
    c->color = ColorBlack;
}

static inline void canvas_set_color(Canvas* c, Color color) { c->color = color; }

static inline void canvas_draw_dot(Canvas* c, int32_t x, int32_t y) { shim_put(c, x, y); }

static inline void canvas_draw_xbm(
    Canvas* c, int32_t x, int32_t y, size_t w, size_t h, const uint8_t* bm) {
    size_t stride = (w + 7) / 8;
    for(size_t j = 0; j < h; j++)
        for(size_t i = 0; i < w; i++)
            if(bm[j * stride + i / 8] & (1u << (i % 8))) shim_put(c, x + (int32_t)i, y + (int32_t)j);
}

static inline void canvas_draw_line(Canvas* c, int32_t x0, int32_t y0, int32_t x1, int32_t y1) {
    int32_t dx = x1 > x0 ? x1 - x0 : x0 - x1, sx = x0 < x1 ? 1 : -1;
    int32_t dy = y1 > y0 ? y0 - y1 : y1 - y0, sy = y0 < y1 ? 1 : -1;
    int32_t err = dx + dy;
    for(;;) {
        shim_put(c, x0, y0);
        if(x0 == x1 && y0 == y1) break;
        int32_t e2 = 2 * err;
        if(e2 >= dy) { err += dy; x0 += sx; }
        if(e2 <= dx) { err += dx; y0 += sy; }
    }
}
