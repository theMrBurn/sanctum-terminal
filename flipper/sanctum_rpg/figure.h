/* figure — the visual composer: creature data in, pixels out.
 *
 * Every creature is DRAWN from what the game already knows about it — its
 * family (body plan), its trait (element, flags, stat deltas), and what it
 * is doing (pose) — instead of being a hand-authored sprite. One function,
 * deterministic, integer-only, no allocation, never touches the game's rng.
 *
 * Output is TWO planes in XBM layout (LSB-first, rows padded to a byte):
 *   ink  — set where the figure is dark (LCD segment on)
 *   mask — set wherever the figure is OPAQUE. mask ⊇ ink. A renderer writes
 *          background where mask=1 && ink=0 (eyes, pale hide, highlights),
 *          so nothing behind a creature shows through it.
 *
 * Detail is set by a RenderBudget, never by the caller's game logic. Only
 * the flipper_1bit tier exists today; richer tiers may ADD detail but must
 * keep the 1-bit silhouette and trait cue (identity first).
 *
 * Doctrine: proposed "Visual composer — one art system, detail by budget"
 * (docs/handoffs/SHARED_STATE.md, 2026-10-14). This C module is canonical;
 * other ports conform to test_render.c's golden. */
#pragma once

#include <stdbool.h>
#include <stdint.h>

typedef struct {
    uint8_t width, height;   /* figure box, px */
    uint8_t bit_depth;       /* 1 | 2 | 8 | 24 */
    uint8_t color;           /* bool */
    uint8_t anim_frames;     /* distinct frames per pose */
    uint8_t texture;         /* bool */
} RenderBudget;

#define FIGURE_MAX_PX 32
#define FIGURE_PLANE_BYTES ((FIGURE_MAX_PX + 7) / 8 * FIGURE_MAX_PX)   /* 128 */

extern const RenderBudget RENDER_BUDGET_FLIPPER_1BIT;   /* 32x32, 1-bit, 2 frames */

typedef enum {
    POSE_IDLE = 0,   /* CR_IDLE */
    POSE_MOVE,       /* CR_APPROACH — legs/wings in stride */
    POSE_FLEE,       /* CR_FLEE — turned away, low */
    POSE_STRIKE,     /* CR_ENGAGE — the attack tell */
    POSE_DEAD,
    POSE_COUNT,
} FigurePose;

/* Map the live creature FSM state to a pose (alive creatures only). */
FigurePose figure_pose_for_state(uint8_t creature_state);

/* Compose {family, trait} in `pose`, animation `frame` (wrapped to the
 * budget's anim_frames), into caller buffers of FIGURE_PLANE_BYTES each.
 * Returns false (planes cleared) for an unsupported budget or bad ids. */
bool figure_compose(
    const RenderBudget* budget, uint8_t family_id, uint8_t trait_id,
    FigurePose pose, uint8_t frame, uint8_t* ink, uint8_t* mask);
