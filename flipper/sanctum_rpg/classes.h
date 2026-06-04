/*
 * classes.h — PC class catalog (slice 1c).
 *
 * The 3 PC classes per inheritance §5: rogue, monk, philosopher. Plus a
 * Wanderer (class_id=0) = the custom/blank build the player can point-buy.
 * Each class supplies a 6-axis block (uint8 each — BODY/CRAFT/SIGHT/MIND/
 * HEART/WILL, renamed from STR/DEX/WIS/INT/CHA/CON in slice 48.F1, see
 * spec 48 §1) + a starting verbs mask (7-bit, one bit per world-verb).
 *
 * The 7 world-verbs (inheritance §5): OBSERVE MEDITATE MARK PARLEY KINDLE
 * REMEMBER INSCRIBE. Players start with 4 (OBSERVE MARK PARLEY REMEMBER) and
 * earn 3 — see VERB_*  bit indices below.
 *
 * Stat budget: every class catalog row sums to 66 (= 10×6 baseline + 6
 * "build points") so all classes are equivalently powered; Wanderer is
 * baseline 10×6=60 and the player allocates 6 points via the stat-buy
 * screen.
 *
 * Pure, host-testable — no <furi.h>.
 */

#pragma once

#include <stdint.h>

/* World-verb bit indices (verbs_mask). */
#define VERB_OBSERVE   0
#define VERB_MEDITATE  1
#define VERB_MARK      2
#define VERB_PARLEY    3
#define VERB_KINDLE    4
#define VERB_REMEMBER  5
#define VERB_INSCRIBE  6

/* Starting mask shared by all classes — OBSERVE | MARK | PARLEY | REMEMBER. */
#define VERBS_STARTING_MASK \
    ((uint8_t)((1u << VERB_OBSERVE) | (1u << VERB_MARK) | \
               (1u << VERB_PARLEY) | (1u << VERB_REMEMBER)))

/* Class identity (slice 48.F2 — You-only pivot per spec 48 §2).
 *   CLASS_YOU (id 0) is the ONLY PC class. The catalog still keeps the
 *   v0.4 classes for NPC archetype use (PARLEY / encounter content via
 *   spec 49); they're flagged ROLE_NPC so the New-Game flow skips them.
 *   CLASS_WANDERER is preserved as a back-compat alias for id 0 — old
 *   saves with class_id=0 load as CLASS_YOU under the new name. */
#define CLASS_YOU         0
#define CLASS_WANDERER    CLASS_YOU /* legacy alias (slice 1c) */
#define CLASS_ROGUE       1
#define CLASS_MONK        2
#define CLASS_PHILOSOPHER 3
#define CLASS_COUNT       4

/* Class role — gates whether the class can be a PC (slice 48.F2). */
typedef enum {
    ROLE_PC  = 0, /* CLASS_YOU only */
    ROLE_NPC = 1, /* Rogue / Monk / Philosopher — seed for spec 49 narrative */
} ClassRole;

typedef struct {
    const char* name;       /* "You", "Rogue", "Monk", ... */
    const char* tagline;    /* one-line flavor */
    uint8_t body, craft, sight, mind, heart, will; /* 6-axis block (slice 48.F1) */
    uint8_t verbs_mask;     /* starting verbs (7-bit) */
    uint8_t role;           /* ROLE_PC or ROLE_NPC (slice 48.F2) */
} ClassDef;

extern const ClassDef CLASS_CATALOG[CLASS_COUNT];

/* Look up a class definition. Returns NULL on out-of-range id. */
const ClassDef* class_def(uint8_t class_id);

/* Sum the 6 axes for budget verification (used by point-buy clamp + tests). */
int class_stats_sum(const ClassDef* c);
