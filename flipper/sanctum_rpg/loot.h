/*
 * loot.h — typed item kinds + weighted loot roll.
 *
 * Mirrors sanctum-engage's kind_config.json vocabulary (glyphs, classes)
 * — see SANCTUM_ENGAGE_INHERITANCE.md §1. Per the "never if kind ==="
 * rule, kinds are a `static const` table, not switch statements.
 *
 * Data shape locked here per spec 43 §14.4: every kind carries WEIGHT
 * (loot drop probability) and VALUE (abstract worth) NOW, even though
 * encumbrance (v0.3.6) and economy don't consume them yet — retrofitting
 * the data shape later is the painful path the veteran flagged.
 *
 * Pure module: no Flipper SDK deps. Host-testable via `make test`.
 */

#pragma once

#include <stdint.h>

#include "biome.h"
#include "rng.h"

/* Object class — subset of kind_config.json's 9 classes that produce
 * loot. Used later (v0.3.4) to let biomes shift class weights. */
typedef enum {
    KC_CRYSTALLINE = 0,
    KC_LIFE,
    KC_ENCOUNTER,
    KC_ORGANIC,
    KC_CLASS_COUNT,
} KindClass;

/* Kind flags (bitmask). */
#define KF_PICKUPABLE 0x01
#define KF_CONSUMABLE 0x02

typedef struct {
    uint8_t     id;
    char        glyph;       /* canonical kind_config.json ascii glyph */
    const char* true_name;   /* shown once identified */
    const char* unid_name;   /* shown before identification (v0.4 use loop) */
    uint8_t     cls;         /* KindClass */
    uint8_t     weight;      /* loot drop weight (relative) */
    uint16_t    value;       /* abstract worth (credits on pickup for now) */
    uint8_t     flags;       /* KF_* */
    uint8_t     biomes;      /* affinity bitmask: which biomes spawn this kind */
    uint8_t     fuel;        /* torch fuel granted on pickup (0 = not a light) */
} KindDef;

/* The catalog. Indexed by id (id == array index). */
extern const KindDef KIND_CATALOG[];
extern const int KIND_COUNT;

/* Lookups. Return NULL if not found. */
const KindDef* kind_by_id(uint8_t id);
const KindDef* kind_by_glyph(char glyph);

/* Is this tile glyph a pickupable item? (Fast path for world_try_move.) */
int loot_is_item_glyph(char glyph);

/* Weighted pick of a loot kind id for a biome. Deterministic for a given
 * rng state. Only KF_PICKUPABLE kinds with weight>0 whose biome affinity
 * includes `biome` participate. */
uint8_t loot_roll(Rng* r, Biome biome);

/* Convenience: the glyph for a kind id (or '.' if invalid). */
char loot_glyph(uint8_t kind_id);
