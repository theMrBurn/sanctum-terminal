# Module 03 — 3D Wireframe Pipeline

The graphical soul of Elite. Ship vertex tables, edge tables (which
vertices connect with lines), face tables (for backface culling), the
matrix-multiply projection, the line drawer, and the clipper. The
Cobra Mk III flying out of a black void at 4 fps on a BBC was made of
these parts.

Estimated time: **3–5 evenings.**

---

## Goal

Implement, in your own code:

```c
typedef struct {
    int16_t x, y, z;
} vertex_t;

typedef struct {
    uint8_t v0, v1;        // vertex indices
    uint8_t f0, f1;        // face indices (for culling)
    uint8_t visibility_byte;
} edge_t;

typedef struct {
    uint8_t   num_vertices;
    uint8_t   num_edges;
    uint8_t   num_faces;
    vertex_t  vertices[];
    edge_t    edges[];
    /* face normals etc. */
} ship_t;

void project_and_render(ship_t *ship,
                        int16_t orient_matrix[9],
                        int16_t pos[3],
                        framebuf_t *fb);
```

**Verification:** load the Cobra Mk III data from the emulator's RAM
into your code. Render it at a few canonical orientations (front,
side, top). Compare your output against screenshots of the BBC's
title-screen Cobra. They should be visually identical at matching
poses.

---

## What you'll discover

- The vertex / edge / face data layout is **byte-packed**, often
  with 4-bit fields and shared nibbles — Braben squeezed
- Ship rotation is **integer fixed-point with periodic
  renormalisation**, not floats and not "proper" fixed-point. The
  orientation matrix drifts; a normalisation pass corrects it every
  ~256 frames or so. The drift never grows large enough to be
  visible.
- The line drawer is **Bresenham**, but bit-packed for the BBC's
  Mode 4 screen layout
- Hidden-line removal uses **face-pair visibility**: each edge knows
  the two faces it belongs to; if both faces are back-facing, the
  edge is hidden
- Backface culling computes a face's screen-projected normal Z and
  skips faces with Z < 0
- Clipping is **per-edge in screen space** (Liang-Barsky-ish, but
  hand-rolled)

---

## Suggested approach

### Step 1 — find the Cobra data block

It's named — search the disassembly for `COBRA` or any string-like
ASCII. Or break on the title screen's ship-init routine and dump the
memory it reads from.

Once found, extract:
- Vertex table (count + (x, y, z) triplets in 16-bit ints)
- Edge table (count + (v0, v1, f0, f1, vis) quintuplets)
- Face table

Write them out as a C struct literal in your code. Now you have *the
Cobra* sitting in your source file.

### Step 2 — render at the identity orientation

Project each vertex with the simplest possible:

```
screen_x = (x * focal_length) / z + screen_centre_x
screen_y = (y * focal_length) / z + screen_centre_y
```

Draw lines between vertex pairs given by the edge table. No culling,
no clipping yet. Just lines.

This should already look recognisably like a Cobra outline.

### Step 3 — apply rotation

Pull the 9-entry orientation matrix from the BBC's ship state. Apply
to each vertex before projection. Now rotate the matrix and re-render.

This is where the fixed-point cleverness lives. Don't normalise yet —
let it drift to confirm it does.

### Step 4 — backface cull + edge visibility

For each face, compute the (transformed) face normal. Skip back-facing
faces.

For each edge, look at its two face indices. If both are back-facing,
skip. (This is the BBC trick — you only have to test face visibility,
not edge-by-edge geometry.)

### Step 5 — clip + draw

Clip each visible edge to the screen rectangle. Bresenham-draw the
clipped segment.

### Step 6 — verify against BBC

Take a screenshot of the BBC's title-screen Cobra at a fixed
orientation. Set your code's matrix to the same. Diff visually. Should
overlay perfectly.

---

## Your notes

### Cobra data block (transcribed)

```
vertices: [
  ( ?, ?, ? ),
  ...
]
edges: [
  ( v0, v1, f0, f1, vis ),
  ...
]
faces: [
  ...
]
```

### Orientation matrix layout

(how does Braben encode the 3x3? Where in memory?)

### The renormalisation routine

(when does it fire, and what does it do exactly?)

---

## Verification log

Render Cobra at these orientations and screenshot-diff against BBC:
- Identity (face-on)
- 90° yaw
- 90° pitch
- 45/45/45 (the title-screen-ish pose)

---

## When stuck

- If the Cobra "explodes" (vertices going to wrong places) you've
  almost certainly got the matrix multiply transposed. Try the
  other convention.
- If lines are off-by-one or pixel-offset, your projection
  centre or focal length is slightly off — the BBC uses specific
  values worth tracing.
- Visibility flags in the edge table are subtle. Some edges only
  appear above a certain distance (cf. the cockpit detail on
  approach). Note these as you find them.

---

## Onward

→ `MODULE_04_TRADE_ECONOMY.md` — back to seeds; market generation,
price fluctuation, illegal goods, the per-system commodity table.
