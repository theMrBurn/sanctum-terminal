/* pixkit — the shared 1-bit pixel rules of the visual composer.
 *
 * Every procedurally drawn thing (creatures in figure.c, terrain props in
 * terrain.c) goes through the same clean-up, so the whole game obeys one
 * set of pixel-art rules (proposed composer rule 9, cluster discipline):
 *   tighten()     — no lone pixels, spurs or one-pixel notches in a silhouette
 *   despeckle()   — no isolated dot of either tone inside a body
 *   mirror_half() — a thing that faces the viewer is one half, reflected
 *
 * Planes are XBM layout (LSB-first, rows padded to a byte), at most
 * PIXKIT_MAX_PX square. Integer-only, allocation-free. */
#pragma once

#include <stdbool.h>
#include <stdint.h>

#define PIXKIT_MAX_PX 32
#define PIXKIT_PLANE_BYTES ((PIXKIT_MAX_PX + 7) / 8 * PIXKIT_MAX_PX)   /* 128 */

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

/* Bresenham line in plane pixels. */
void line_px(Plane* p, int x0, int y0, int x1, int y1, int v);

/* Where (x, y) sits in its vertical run of the mask: 0 top .. 15 bottom. */
int column_v(const Plane* m, int x, int y);

void tighten(Plane* m);
void despeckle(Plane* ink, const Plane* m);
void mirror_half(Plane* a, Plane* b);
