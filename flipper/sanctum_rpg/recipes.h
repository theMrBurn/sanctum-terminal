/*
 * recipes.h — slot-machine crafting (slice 4, spec 46 §3).
 *
 * Each recipe carries inputs (1-2 kinds × required qty), an output kind, and
 * the three base tier weights for the single weighted `rng_range` roll that
 * decides the pull's outcome: JACKPOT (masterwork — bonus quantity), HIT
 * (standard — the item), FLOOR (a sellable oddment OBJECT, never nothing).
 *
 * The user's design (verbatim): "slot machine craft system, super simple,
 * and it notifies us if we have the materials to attempt crafting an item,
 * and at worse it makes a useful object to sell at a shop. like, that simple."
 *
 * Pure module — no Flipper SDK; host-testable via `make test`.
 */

#pragma once

#include <stdint.h>

#include "rng.h"

/* Tier of a single Forge pull. */
typedef enum {
    PULL_FLOOR = 0,  /* oddment — a low-value object, not currency */
    PULL_HIT,        /* the item, standard quality (qty 1) */
    PULL_JACKPOT,    /* the item, masterwork (qty 2 — bonus stack) */
} PullTier;

/* What a recipe makes (spec 50 Q1 §Q.10.1, spec 58 §58.7.1). Restorative
 * recipes are known from the start; the others are hidden until learned. */
typedef enum {
    RC_RESTORATIVE = 0,  /* healing, food, tools */
    RC_POWER,            /* an object of power for a rite (spec 58: the made way) */
    RC_DESTRUCTIVE,      /* poisons, rot, blight (spec 50 Q1 §Q.10) */
} RecipeClass;

/* Sentinel for "no second input." */
#define RECIPE_NO_INPUT 0xFFu

typedef struct {
    const char* name;        /* "Crystal Brew" */
    uint8_t output_kind;     /* KindDef id produced on HIT/JACKPOT */
    uint8_t input_kind_a;
    uint8_t input_qty_a;
    uint8_t input_kind_b;    /* RECIPE_NO_INPUT if unused */
    uint8_t input_qty_b;
    uint8_t weight_floor;    /* base % chance of oddment */
    uint8_t weight_hit;      /* base % chance of standard */
    uint8_t weight_jackpot;  /* base % chance of masterwork — sums to 100 */
    /* Spec 43 §17.3 rule #3 — FLOOR pays a low-value KIND, never currency.
     * Paying currency made the Forge a vendorless mint and removed the
     * liquidation step that makes crafting a CONVERSION. It also could not
     * survive §17.5's denomination: an oddment worth 3 value rounds to ZERO
     * whole shards under the §17.5a rounding law, which would have violated
     * this module's own "never nothing" contract.
     *
     * Table invariant, asserted in `make test`: the oddment's catalog value
     * must be strictly less than the summed value of the recipe's inputs —
     * a FLOOR pull is always a net loss, so it can never be an income verb. */
    uint8_t oddment_kind;    /* KindDef id granted on FLOOR */
    uint8_t cls;             /* RecipeClass; 0 (restorative) for the original rows */
} RecipeDef;

/* Bit in CharacterState.recipes_known for recipe `id`. */
#define RECIPE_BIT(id) ((uint16_t)(1u << (id)))

/* The forge lists only what the player knows: restorative recipes always,
 * the others once learned (`known` = CharacterState.recipes_known). */
int recipe_known(uint8_t recipe_id, uint16_t known);

extern const RecipeDef RECIPE_CATALOG[];
extern const int RECIPE_COUNT;

/* Look up a recipe. NULL on out-of-range id. */
const RecipeDef* recipe_def(uint8_t recipe_id);

/* Do the held inventory counts satisfy this recipe? */
int recipe_craftable(const RecipeDef* r, const uint8_t* inv_qty, int inv_len);

/* One weighted roll → tier. Weights sum should be 100; if not, `total` is
 * derived from the recipe's three weights. Deterministic from `rng`. */
PullTier recipe_pull(Rng* rng, const RecipeDef* r);
