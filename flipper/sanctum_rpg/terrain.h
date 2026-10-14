/* terrain — the visual composer for the ground and what stands on it.
 *
 * Every terrain glyph has a FORM, which decides how first-person view
 * draws it (doctrine proposal: "terrain has a form", SHARED_STATE
 * 2026-10-14):
 *
 *   SLAB   — structure. Stops the ray; drawn as a full-height wall face
 *            in its MATERIAL (coursed stone, fluted column, monolith).
 *   PROP   — a thing standing in the open (standing stone, cairn, boulder,
 *            deadfall, scrub, glowcap). Does NOT stop the ray: it is
 *            composed as an opaque billboard, so what's behind shows
 *            above and around it.
 *   FLOOR  — lies on the ground (moss, scree). A marking on the floor.
 *
 * Form is a RENDER fact only. Movement and top-down FOV still read
 * walkability/sight from stamps.c / world.c, so a cairn still blocks
 * your path and the top-down view's line of sight.
 *
 * Props go through pixkit's rules (tighten, despeckle) like creatures.
 * Deterministic and integer-only; `variant` comes from the tile's hash. */
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "pixkit.h"

typedef enum { TF_NONE = 0, TF_SLAB, TF_PROP, TF_FLOOR } TerrainForm;

typedef enum {
    TM_STONE = 0,  /* coursed stone: chamber walls, secrets */
    TM_COLUMN,     /* carved column: vertical flutes, no courses */
    TM_MONOLITH,   /* one raw stone: no courses, a single long crack */
} SlabMaterial;

typedef struct {
    char glyph;
    uint8_t form;       /* TerrainForm */
    uint8_t material;   /* SlabMaterial, for SLAB */
    uint8_t plan;       /* prop / floor plan index (terrain.c) */
} TerrainDef;

#define TERRAIN_VARIANTS 4

/* Floor plans (TF_FLOOR defs' `plan`): what render_fpv marks on the ground. */
#define TERRAIN_PLAN_MOSS  7
#define TERRAIN_PLAN_SCREE 8

/* The def for a glyph, or NULL for plain floor / non-terrain tiles. */
const TerrainDef* terrain_def(char glyph);

/* Does a first-person ray stop at this tile? SLABs do; so does any
 * movement-blocking glyph without a def (safe default: unknown solid
 * things stay walls). PROPs and FLOORs never do. */
bool terrain_stops_ray(char glyph);

/* Slab material for a ray-stopping glyph (TM_STONE if it has no def). */
SlabMaterial terrain_material(char glyph);

/* Compose a PROP glyph into `size`-px square planes (8..PIXKIT_MAX_PX),
 * bottom-anchored. Returns false (planes cleared) if not a prop. */
bool terrain_compose_prop(char glyph, uint8_t variant, int size, uint8_t* ink, uint8_t* mask);
