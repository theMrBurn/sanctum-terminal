/* pixkit.c — see pixkit.h. Moved verbatim out of figure.c (2026-10-14);
 * the figure golden pins that the move changed nothing. */
#include "pixkit.h"

#include <string.h>

void line_px(Plane* p, int x0, int y0, int x1, int y1, int v) {
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

/* Where pixel (x, y) sits in its body column: 0 at the top, 15 at the
 * belly. Columns are the mask's vertical runs. */
int column_v(const Plane* m, int x, int y) {
    int top = y, bot = y;
    while(pget(m, x, top - 1)) top--;
    while(pget(m, x, bot + 1)) bot++;
    int span = bot - top;
    return span > 0 ? ((y - top) * 15) / span : 0;
}

/* TIGHTEN the silhouette before it is outlined: drop lone pixels and
 * SPURS (a pixel held by one side only — the nubs an ellipse leaves at its
 * poles), and fill one-pixel notches, the jaggies where primitives meet.
 * Each pass reads a snapshot, so a thin part is trimmed by one pixel per
 * pass instead of unzipping in raster order. */
#define TIGHTEN_PASSES 2
void tighten(Plane* m) {
    uint8_t snap_b[PIXKIT_PLANE_BYTES];
    Plane s = {snap_b, m->w, m->h, m->stride};
    for(int pass = 0; pass < TIGHTEN_PASSES; pass++) {
        memcpy(snap_b, m->b, (size_t)(m->stride * m->h));
        for(int y = 0; y < m->h; y++)
            for(int x = 0; x < m->w; x++) {
                int l = pget(&s, x - 1, y), r = pget(&s, x + 1, y);
                int u = pget(&s, x, y - 1), d = pget(&s, x, y + 1);
                if(pget(&s, x, y)) {
                    if(l + r + u + d <= 1) pset(m, x, y, 0);   /* lone pixel / spur */
                } else if((l && r && (u || d)) || (u && d && (l || r))) {
                    pset(m, x, y, 1);                          /* one-pixel notch */
                }
            }
    }
}

/* DESPECKLE the hide: a pixel whose in-body neighbours are ALL the other
 * tone is noise (a stray dot of light in a dark shell, or of ink in a pale
 * coat) — flip it. Runs before eyes are placed, so eyes are never touched;
 * accent LINES survive because each pixel has a same-tone neighbour. */
void despeckle(Plane* ink, const Plane* m) {
    uint8_t snap_b[PIXKIT_PLANE_BYTES];
    Plane s = {snap_b, ink->w, ink->h, ink->stride};
    memcpy(snap_b, ink->b, (size_t)(ink->stride * ink->h));
    static const int8_t N4[4][2] = {{-1, 0}, {1, 0}, {0, -1}, {0, 1}};
    for(int y = 0; y < ink->h; y++)
        for(int x = 0; x < ink->w; x++) {
            if(!pget(m, x, y)) continue;
            int me = pget(&s, x, y), same = 0;
            bool rim = false;
            for(int k = 0; k < 4; k++) {
                int nx = x + N4[k][0], ny = y + N4[k][1];
                if(!pget(m, nx, ny)) { rim = true; break; }   /* the outline is not noise */
                same += pget(&s, nx, ny) == me;
            }
            if(!rim && same == 0) pset(ink, x, y, !me);
        }
}

/* SYMMETRY: a creature that faces the viewer is one half, mirrored. The
 * right half is the source (profile cues — head, horns — sit on the right),
 * copied over the left about the box's true centre, so line rounding can
 * never make the two sides differ. */
void mirror_half(Plane* a, Plane* b) {
    for(int y = 0; y < a->h; y++)
        for(int x = 0; x < a->w / 2; x++) {
            int xr = a->w - 1 - x;
            pset(a, x, y, pget(a, xr, y));
            pset(b, x, y, pget(b, xr, y));
        }
}
