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
    TM_MONOLITH,   /* one raw stone: no courses, a single long crack. No glyph
                    * uses it since the menhir became a prop; kept for the
                    * dungeon styles' wall materials. */
    TM_BRICK,      /* crypt: regular brick courses, a burial niche on some tiles */
    TM_TIMBER,     /* mine: rough stone shored with timber posts + lintels */
    TM_FRAME,      /* manor: plaster in a dark timber frame, a brace on some tiles */
    TM_ASHLAR,     /* keep: big dressed blocks, an arrow slit on some tiles */
    TM_CARVED,     /* abbey: smooth stone, a lancet window on some tiles */
    TM_STYLE_WALL, /* "this region's wall": resolved by the renderer from the
                    * world's style (StyleDef.wall_material). Plain walls and
                    * secrets use it, so a crypt's walls are brick. */
} SlabMaterial;

typedef struct {
    char glyph;
    uint8_t form;       /* TerrainForm */
    uint8_t material;   /* SlabMaterial, for SLAB */
    uint8_t plan;       /* prop / floor plan index (terrain.c) */
    uint8_t span;       /* PROP footprint, tiles per side: 1 = one tile; 2 = a
                         * 2x2 block of the glyph drawn as ONE billboard at
                         * the block's centre */
    const char* name;   /* what the player examines ("sarcophagus"); NULL for
                         * TM_STYLE_WALL slabs, named by the style instead */
    uint8_t scale;      /* PROP billboard size in tiles (square, bottom-anchored):
                         * 1 = wall height; 2 = a tree or menhir that stands
                         * over the walls. Independent of the footprint. */
    int8_t step_fuel;   /* torch fuel on stepping onto it (spec 50 §L): scree
                         * -1 ("loose footing"), glowcap +2 (harvested) */
    uint8_t step_flags; /* TSF_* */
    const char* step_msg; /* status line on stepping onto it, or NULL */
} TerrainDef;

#define TSF_CONSUMED 0x01u  /* stepping onto it harvests it: tile -> floor (a delta) */

/* What stepping onto a tile does. */
typedef struct {
    int8_t fuel;
    bool consumed;
    const char* message;
} TerrainStep;

/* True (and `out` filled) if stepping onto `glyph` has an effect. */
bool terrain_step(char glyph, TerrainStep* out);

/* Torch fuel after a step effect, clamped to 0..max. */
uint16_t terrain_step_fuel(uint16_t fuel, int8_t delta, uint16_t max);

#define TERRAIN_VARIANTS 4
#define TERRAIN_SPAN_MAX 2

/* Floor plans (TF_FLOOR defs' `plan`): what render_fpv marks on the ground.
 * Numbered apart from the prop plans so the two can never collide. */
#define TERRAIN_PLAN_MOSS  32
#define TERRAIN_PLAN_SCREE 33
#define TERRAIN_PLAN_FLAG  34   /* cracked flagstone: joints */
#define TERRAIN_PLAN_RAILS 35   /* mine rails: sleepers */
#define TERRAIN_PLAN_GRASS 36   /* tall grass: blades */
#define TERRAIN_PLAN_PLANKS 37  /* plank floor: board seams */

/* Every def, in table order — tests and the shot harness iterate this, so
 * a new row can't escape the identity / opacity / golden checks. */
int terrain_count(void);
const TerrainDef* terrain_at(int i);

/* The def for a glyph, or NULL for plain floor / non-terrain tiles. */
const TerrainDef* terrain_def(char glyph);

/* Does a first-person ray stop at this tile? SLABs do; so does any
 * movement-blocking glyph without a def (safe default: unknown solid
 * things stay walls). PROPs and FLOORs never do. */
bool terrain_stops_ray(char glyph);

/* What a terrain glyph is called when examined, in a region of `wall_name`
 * walls (StyleDef.wall_name). NULL if the glyph has no def. */
const char* terrain_name(char glyph, const char* wall_name);

/* Slab material for a ray-stopping glyph (TM_STONE if it has no def). May
 * return TM_STYLE_WALL, which the caller resolves from the world's style. */
SlabMaterial terrain_material(char glyph);

/* Compose a PROP glyph into `size`-px square planes (8..PIXKIT_MAX_PX),
 * bottom-anchored. Returns false (planes cleared) if not a prop. */
bool terrain_compose_prop(char glyph, uint8_t variant, int size, uint8_t* ink, uint8_t* mask);
