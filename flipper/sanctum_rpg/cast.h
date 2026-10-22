/*
 * cast.h — the ranged scanner: the reticle that grows a trigger (spec 46
 * §5.1; the user's calls, 2026-10-22).
 *
 * In the look cursor, OK on a creature SCANS it while there's more to learn
 * about its kind at your OBSERVE, and FIRES a cast once there isn't: you
 * identify it, then you can strike it from where you stand. Range is your
 * light (a lit tile is in line of sight).
 *
 * Casts are EARNED, never given (spec 46 §5.1): completing a deep scan
 * (tier 3) of a creature teaches the cast of its element — you grow by
 * studying the world, never by grinding kills (spec 45 §4.6). With none
 * known, the reticle stays scan-only.
 *
 * A cast costs MP, which comes back one point every MP_REGEN_TURNS turns.
 * Damage = power + MIND / CAST_MIND_DIV - foe def / 8, at least 1 (spec 46
 * §5.1, INT read as MIND per spec 48). Pure, integer, host-tested.
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "creatures.h"

#define MP_REGEN_TURNS  6    /* one MP back every this many turns */
#define CAST_MIND_DIV   4    /* MIND's share of a cast's damage */
#define CAST_PROVOKE    255  /* a creature struck from range turns on you */

/* Copy (DRAFT: not in any spec's catalog; voice law §C.5; the user's call). */
#define CAST_LINE_LEARNED "the %s stays with you."
#define CAST_LINE_LANDS   "the %s finds it."
#define CAST_LINE_EMPTY   "nothing left in you."

typedef struct {
    const char* name;     /* what the player learns ("sending") */
    uint8_t element;      /* Element: whose deep scan teaches it */
    uint8_t power;
    uint8_t mp_cost;
} CastDef;

typedef enum { CAST_SENDING = 0, CAST_EMBER, CAST_RIME, CAST_COUNT } CastId;

extern const CastDef CAST_TABLE[CAST_COUNT];

#define CAST_BIT(c) ((uint8_t)(1u << (c)))

/* OK on a creature in the look cursor: fire (true) or scan (false)? Scan
 * while a scan would still teach something about its family at this
 * OBSERVE; fire once it wouldn't, if a cast is known. */
bool cast_fires(uint8_t observe, uint8_t scan_diff, int bestiary_grade, uint8_t casts_known);

/* The cast a deep scan of a creature of `element` teaches, or -1 if none. */
int cast_taught_by(uint8_t element);

/* The cast fired: the strongest known that MP can pay for, or -1. */
int cast_pick(uint8_t casts_known, uint16_t mp);

/* Damage of cast `c` at a foe of defence `def`, by a caster of MIND `mind`. */
int cast_damage(int c, uint8_t mind, uint8_t def);

/* MP after turn `turn` ends: one back every MP_REGEN_TURNS, up to max. */
uint16_t cast_mp_regen(uint16_t mp, uint16_t max_mp, uint32_t turn);
