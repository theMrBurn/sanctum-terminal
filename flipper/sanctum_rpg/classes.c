/*
 * classes.c — see classes.h.
 *
 * Class catalog values lifted from inheritance §5 ("PC: rogue, monk,
 * philosopher; each has 6 stats + 4 starting abilities"), normalized so each
 * PC class sums to 66 = 10×6 baseline + 6 build-points-worth. Wanderer is
 * baseline 10×6 = 60 — the player allocates 6 points themselves.
 *
 * The "4 starting abilities" are the world-verbs the class begins with;
 * inheritance §5 specifies the same 4 for all classes (OBSERVE MARK PARLEY
 * REMEMBER) at first. Class-specific *active* abilities (monk far-strike,
 * rogue stealth, philosopher's parley bonus, etc.) live in the next slice
 * (verbs + abilities); the mask seam is set up here.
 */

#include "classes.h"

#include <stddef.h>

/* Slice 48.F2 — You-only pivot. CLASS_YOU is ROLE_PC; Rogue/Monk/
 * Philosopher are ROLE_NPC (kept as seed data for spec 49 PARLEY +
 * encounter content). The DISPLAYED character name on the sheet comes
 * from CharacterState.name, NOT from CLASS_YOU.name — the class label
 * "You" is the type; the user's name is the identity.
 *
 * Slice 48.F1 axes preserved one-to-one through the F2 rename: the v0.4
 * Rogue's STR=9 still lands as BODY=9. */
const ClassDef CLASS_CATALOG[CLASS_COUNT] = {
    /* name           tagline             BODY CRAFT SIGHT MIND HEART WILL  verbs               role */
    [CLASS_YOU] = {
        "You", "the one who walks",        10,   10,   10,   10,   10,   10, VERBS_STARTING_MASK, ROLE_PC,
    },
    [CLASS_ROGUE] = {
        "Rogue", "swift, sharp-eyed",       9,   14,    8,   14,   12,    9, VERBS_STARTING_MASK, ROLE_NPC,
    },
    [CLASS_MONK] = {
        "Monk", "balanced, focused",       12,   13,   12,    8,    8,   13, VERBS_STARTING_MASK, ROLE_NPC,
    },
    [CLASS_PHILOSOPHER] = {
        "Philosopher", "wise tongue",       8,    8,   14,   13,   14,    9, VERBS_STARTING_MASK, ROLE_NPC,
    },
};

const ClassDef* class_def(uint8_t class_id) {
    if(class_id >= CLASS_COUNT) return NULL;
    return &CLASS_CATALOG[class_id];
}

int class_stats_sum(const ClassDef* c) {
    if(!c) return 0;
    return (int)c->body + (int)c->craft + (int)c->sight + (int)c->mind +
           (int)c->heart + (int)c->will;
}
