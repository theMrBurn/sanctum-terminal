/*
 * narrative.c — see narrative.h.
 *
 * Bundled mock-PO entries + the quest template catalog. The catalog is a
 * `static const` table per the "never if quest_id ==" rule (spec 43 §14.0).
 * Adding a new template = one new row. Adding a new mock entry = one new
 * row. The producer side (real PO exporter, slice 49.D*) will write JSON
 * with the same shape; the consumer code below doesn't change.
 */

#include "narrative.h"

#include <stdint.h>
#include <stddef.h>
#include <string.h>

#include "pool.h"

/* ─── Mock PO entries (8 hand-authored, sanctum-coherent voice per §C) ──
 * Captured-at and weight metadata are stubbed for v1 (the producer
 * supplies them when the real packet lands). Severity is the v1 lever. */
const PoEntry MOCK_PO_ENTRIES[] = {
    {
        .id = "po-001", .lemma = "kitchen-shelf",
        .subject = "the shelf", .place = "the kitchen", .people = NULL,
        .theme_mask = THEME_CRAFT | THEME_WILL | THEME_HOME | THEME_TOOL,
        .severity = 2,
    },
    {
        .id = "po-002", .lemma = "her-old-letter",
        .subject = "the letter", .place = NULL, .people = "the bond",
        .theme_mask = THEME_HEART | THEME_RITUAL | THEME_BOND,
        .severity = 3,
    },
    {
        .id = "po-003", .lemma = "the-language-set-aside",
        .subject = "the words", .place = NULL, .people = "the kin",
        .theme_mask = THEME_MIND | THEME_KIN | THEME_HEART,
        .severity = 4,
    },
    {
        .id = "po-004", .lemma = "the-path-not-walked",
        .subject = "the path", .place = "the field", .people = NULL,
        .theme_mask = THEME_BODY | THEME_FIELD | THEME_WILL,
        .severity = 2,
    },
    {
        .id = "po-005", .lemma = "the-tool-i-borrowed",
        .subject = "the tool", .place = NULL, .people = "the bond",
        .theme_mask = THEME_CRAFT | THEME_TOOL | THEME_BOND,
        .severity = 1,
    },
    {
        .id = "po-006", .lemma = "the-bell-at-the-shrine",
        .subject = "the bell", .place = "the small room", .people = NULL,
        .theme_mask = THEME_RITUAL | THEME_HOME | THEME_HEART,
        .severity = 3,
    },
    {
        .id = "po-007", .lemma = "the-walk-i-promised",
        .subject = "the walk", .place = "the field", .people = "the kin",
        .theme_mask = THEME_BODY | THEME_KIN | THEME_FIELD | THEME_WILL,
        .severity = 2,
    },
    {
        .id = "po-008", .lemma = "the-book-on-my-table",
        .subject = "the book", .place = "the long room", .people = NULL,
        .theme_mask = THEME_MIND | THEME_ART | THEME_HOME,
        .severity = 1,
    },
};
const int MOCK_PO_ENTRY_COUNT =
    (int)(sizeof(MOCK_PO_ENTRIES) / sizeof(MOCK_PO_ENTRIES[0]));

/* ─── Quest templates (spec 49 §C, axis-symmetric branches per §L.3) ──
 * Each template offers a real choice; neither branch dominates. Branch
 * deeds feed deeds.c's per-session caps so 49 cannot flood spec-48's axes. */
const QuestTemplate QUEST_TEMPLATES[] = {
    /* T1 — CRAFT/WILL entries: TEND / LET_GO */
    {
        .id = 1,
        .theme_match = THEME_CRAFT | THEME_WILL | THEME_TOOL,
        .min_severity = 1,
        .intro          = "you remember %lemma%. it weighs.",
        .branch_a_label = "tend",
        .branch_b_label = "let go",
        .resolution_a   = "you put down the time. %subject% took shape.",
        .resolution_b   = "you saw %subject% for what it had become.",
        .branch_a_deed  = DEED_QUEST_TEND,    /* HEART +2 */
        .branch_b_deed  = DEED_QUEST_LET_GO,  /* WILL  +2 */
    },
    /* T2 — HEART/RITUAL/BOND entries: SPEAK / WITHHOLD */
    {
        .id = 2,
        .theme_match = THEME_HEART | THEME_RITUAL | THEME_BOND,
        .min_severity = 2,
        .intro          = "the words you didn't say sit close.",
        .branch_a_label = "speak",
        .branch_b_label = "hold",
        .resolution_a   = "you spoke. %people% heard, however it lands.",
        .resolution_b   = "you held the words. they keep, for now.",
        .branch_a_deed  = DEED_QUEST_SPEAK,    /* HEART +2 */
        .branch_b_deed  = DEED_QUEST_WITHHOLD, /* WILL  +2 */
    },
    /* T3 — BODY/FIELD entries: tend the path (TEND) or release it (LET_GO) */
    {
        .id = 3,
        .theme_match = THEME_BODY | THEME_FIELD,
        .min_severity = 1,
        .intro          = "the path waits. you remember %lemma%.",
        .branch_a_label = "walk",
        .branch_b_label = "rest",
        .resolution_a   = "you walked %subject%. the day's count went up.",
        .resolution_b   = "you let it wait. the path is patient.",
        .branch_a_deed  = DEED_QUEST_TEND,    /* HEART +2 */
        .branch_b_deed  = DEED_QUEST_LET_GO,  /* WILL  +2 */
    },
    /* T4 — MIND/KIN entries: SPEAK / WITHHOLD */
    {
        .id = 4,
        .theme_match = THEME_MIND | THEME_KIN,
        .min_severity = 2,
        .intro          = "%people% would have known %subject%.",
        .branch_a_label = "speak",
        .branch_b_label = "study",
        .resolution_a   = "you said it out loud. it was true once said.",
        .resolution_b   = "you sat with it longer. the words sharpened.",
        .branch_a_deed  = DEED_QUEST_SPEAK,    /* HEART +2 */
        .branch_b_deed  = DEED_QUEST_WITHHOLD, /* WILL  +2 */
    },
    /* T5 — generic small moments: TEND / LET_GO. Wide theme net = always
     * something to surface even if the chunk doesn't match a richer pair. */
    {
        .id = 5,
        .theme_match = THEME_HOME | THEME_ART | THEME_TOOL | THEME_BOND,
        .min_severity = 1,
        .intro          = "%lemma%. small but it stays.",
        .branch_a_label = "tend",
        .branch_b_label = "leave",
        .resolution_a   = "you tended it. small things accrete.",
        .resolution_b   = "you let it stay where it was.",
        .branch_a_deed  = DEED_QUEST_TEND,
        .branch_b_deed  = DEED_QUEST_LET_GO,
    },
};
const int QUEST_TEMPLATE_COUNT =
    (int)(sizeof(QUEST_TEMPLATES) / sizeof(QUEST_TEMPLATES[0]));

/* ─── Integer hash (FNV-1a-flavored, 3-input). Byte-equal port target. ── */
static uint32_t narrative_hash32(uint32_t a, uint32_t b, uint32_t c) {
    uint32_t h = 0x811C9DC5u;
    h = (h ^ a) * 16777619u;
    h = (h ^ b) * 16777619u;
    h = (h ^ c) * 16777619u;
    /* avalanche */
    h ^= h >> 16;
    h *= 0x85EBCA6Bu;
    h ^= h >> 13;
    return h;
}

void narrative_anchor(uint32_t campaign_seed, uint8_t entry_id,
                      int8_t* chunk_x_out, int8_t* chunk_y_out) {
    /* ±8 chunks each axis (§R.5 v1). 16-cell range, then re-center. */
    uint32_t hx = narrative_hash32(campaign_seed, 0xA1A1A1A1u, (uint32_t)entry_id);
    uint32_t hy = narrative_hash32(campaign_seed, 0xB2B2B2B2u, (uint32_t)entry_id);
    if(chunk_x_out) *chunk_x_out = (int8_t)((hx % 16u) - 8u);
    if(chunk_y_out) *chunk_y_out = (int8_t)((hy % 16u) - 8u);
}

bool narrative_eligible(const PoEntry* entry, const QuestTemplate* tpl) {
    if(!entry || !tpl) return false;
    if((entry->theme_mask & tpl->theme_match) == 0u) return false;
    if(entry->severity < tpl->min_severity) return false;
    return true;
}

void narrative_substitute(char* out, size_t cap, const char* tpl_str,
                          const PoEntry* entry) {
    if(!out || cap == 0) return;
    if(!tpl_str || !entry) { out[0] = '\0'; return; }
    size_t i = 0;
    const char* p = tpl_str;
    while(*p && i + 1 < cap) {
        if(*p != '%') {
            out[i++] = *p++;
            continue;
        }
        /* Walk to closing %. */
        const char* end = strchr(p + 1, '%');
        if(!end) {
            out[i++] = *p++;
            continue;
        }
        size_t slot_len = (size_t)(end - (p + 1));
        char slot[16];
        if(slot_len == 0 || slot_len >= sizeof(slot)) {
            /* malformed %slot% → pass the % through */
            out[i++] = *p++;
            continue;
        }
        memcpy(slot, p + 1, slot_len);
        slot[slot_len] = '\0';

        const char* val = NULL;
        if(strcmp(slot, "lemma") == 0)        val = entry->lemma;
        else if(strcmp(slot, "subject") == 0) val = entry->subject;
        else if(strcmp(slot, "place") == 0)   val = entry->place;
        else if(strcmp(slot, "people") == 0)  val = entry->people;

        if(val) {
            while(*val && i + 1 < cap) out[i++] = *val++;
        } else {
            /* Unknown / empty slot → emit "—" to keep the line readable. */
            if(i + 1 < cap) out[i++] = '-';
        }
        p = end + 1;
    }
    out[i] = '\0';
}

bool narrative_pick_for_chunk(uint32_t campaign_seed, int chunk_x, int chunk_y,
                              uint32_t resolved_mask,
                              uint8_t* entry_out, uint8_t* template_out) {
    return narrative_pick_for_chunk_pooled(
        campaign_seed, chunk_x, chunk_y, resolved_mask, NULL,
        entry_out, template_out);
}

/* A theme is "foreground" when its packed weight is ≥ this threshold.
 * Per spec 50 §4.4 — at the threshold, the theme is loud enough that the
 * narrative consumer prefers entries matching it. */
#define THEME_FOREGROUND_THRESHOLD 8

bool narrative_pick_for_chunk_pooled(
    uint32_t campaign_seed, int chunk_x, int chunk_y,
    uint32_t resolved_mask, const Pool* pool,
    uint8_t* entry_out, uint8_t* template_out) {
    /* Compute the Pool's foreground theme bitmask once. */
    uint16_t foreground = 0;
    if(pool) {
        for(int t = 0; t < POOL_THEMES; t++) {
            if(pool_theme_weight(pool, t) >= THEME_FOREGROUND_THRESHOLD) {
                foreground |= (uint16_t)(1u << t);
            }
        }
    }

    /* Walk entries; the anchor hash is deterministic per (seed × entry),
     * so a given chunk can only ever be one entry's anchor. */
    for(int ei = 0; ei < MOCK_PO_ENTRY_COUNT; ei++) {
        if(resolved_mask & (1u << ei)) continue;
        int8_t ax = 0, ay = 0;
        narrative_anchor(campaign_seed, (uint8_t)ei, &ax, &ay);
        if((int)ax != chunk_x || (int)ay != chunk_y) continue;

        /* Find a matching template, scored by min_severity + theme alignment. */
        const PoEntry* e = &MOCK_PO_ENTRIES[ei];
        int best = -1;
        uint32_t best_score = 0;
        uint16_t aligned_mask = (uint16_t)(e->theme_mask & foreground);
        /* popcount for uint16: small constant time loop. */
        uint32_t align_count = 0;
        for(uint16_t m = aligned_mask; m; m >>= 1) align_count += (m & 1u);

        for(int ti = 0; ti < QUEST_TEMPLATE_COUNT; ti++) {
            const QuestTemplate* t = &QUEST_TEMPLATES[ti];
            if(!narrative_eligible(e, t)) continue;
            uint32_t score = (uint32_t)t->min_severity * 4u + align_count * 2u;
            if(best < 0 || score > best_score) {
                best = ti;
                best_score = score;
            }
        }
        if(best < 0) continue;
        if(entry_out) *entry_out = (uint8_t)ei;
        if(template_out) *template_out = (uint8_t)best;
        return true;
    }
    return false;
}
