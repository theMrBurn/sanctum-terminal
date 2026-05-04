# Spec — creature engagement (Undertale × Wario Ware × Dragon Quest)

**Status:** PINNED 2026-05-02. Design only — implementation deferred until
ARPG environmental loop is dialed in.
**Companion:** `design_engagement_primitive`, `design_orb_encounters`,
`design_won't_tolerate`.

## The split

| Target | Verb | Resolution |
|---|---|---|
| **Environmental** (pots, crystals, columns, logs, etc.) | mouse-left smash, KEYS 1-4 cast, future ranged shot | **ARPG** — instant, dice silent, toast + entity disappears |
| **Creature** (orbs, future NPCs / hostile mobs / spirits) | contact (walk into) OR mouse-engage | **Engagement** — opens a mini-game / dialog / puzzle in an overlay; resolved by satisfying a rule under constraints |

Hack-and-slash on creatures is not in the design. Defeating a creature
is **solving its puzzle**, not depleting its HP. This holds line with
`design_won't_tolerate`: no extractive mechanics, no slaughter framing.

## What an "engagement" is

An engagement is the same shape as the reflective fridge primitive
(per `design_engagement_primitive`):

```
{
    rule_id:       str          # e.g. "compose_three", "pattern_match", "acrostic"
    rule_args:     dict         # rule-specific tuning (target_count, timing, etc.)
    pool:          list[str]    # available pieces / responses / verbs to pick
    ac_predicate:  str          # "checked when COMMIT fires; True = win, False = NOT YET"
    overlay_kind:  str          # which renderer to use (`reflective`, `dialog`, `rhythm`, ...)
}
```

The state machine, AC validation, and StateEvent emission already exist
(`core/systems/reflective/state_machine.py`). For creatures, we expose
the same machinery via a registry keyed on creature kind.

## Per-kind engagement registry

New config table (proposed location: `config/creature_engagements.json`):

```json
{
    "orb_red":      { "rule": "compose_three", "pool": "social_postures_5",  "overlay": "reflective" },
    "orb_blue":     { "rule": "pattern_match", "pool": "symbols_7",          "overlay": "rhythm" },
    "orb_violet":   { "rule": "acrostic",      "pool": "lexicon_words_8",    "overlay": "dialog" },
    "rat_skitter":  { "rule": "rhythm_three",  "pool": "rhythm_beats_4",     "overlay": "rhythm" },
    "wandering_scout": { "rule": "dialog_tree", "pool": "scout_dialog",      "overlay": "dialog" }
}
```

Each entry says: when contact fires for this kind, open `overlay`
running `rule` over `pool`. The runtime composes the engagement state
(same shape as `world.reflective`) and transitions `game_state` to
REFLECTIVE (or a new sibling state, see Q1 below).

## Engagement type catalog (V1+)

Each is a rule + pool + AC + overlay shape. **Authoring a new game type
= one new rule + one new AC predicate + one new overlay (if the rule
can't reuse `reflective`).** Rough estimates assume the substrate is
ready.

| Type | Description | Rule | AC | Overlay | Effort |
|---|---|---|---|---|---|
| **compose_three** ✅ shipped | Pick 3 magnets from a 31-piece pool. Win on commit. | append-only list | len ≥ 3 | reflective | done |
| **pattern_match** | 3-7 symbols flash in sequence; player replays via dial input within timeout. | sequence buffer | matches expected | rhythm | ~2h |
| **acrostic** | First letters of chosen verbs spell a target word from biome's lexicon. | append-only list | first-letter join == target | dialog | ~2h |
| **rhythm_three** | Press a key in sync with a slow beat 3 times. (Wario Ware micro.) | timing buffer | 3 hits within ε of beat | rhythm | ~3h |
| **dialog_tree** | Branching menu. Player picks one of N responses; tree unfolds. Win condition is reaching a "satisfied" leaf. | menu cursor + history | leaf.flag == "satisfied" | dialog | ~half-day |
| **silhouette_match** | Show a vector silhouette; player rotates a wireframe to match within N degrees. (Visual puzzle.) | yaw state | abs(yaw - target) < ε | rotate | ~half-day |
| **stack_balance** | Place wireframe primitives so a tower doesn't topple under the engagement's gravity sim. (Physics micro.) | placement list | tower stable for 3s | place | ~day (heaviest) |
| **OBSERVE_then_PARLEY** | Use OBSERVE verb 3× to learn the creature's *want*; then PARLEY with that want as the answer. | verb history | last action == OBSERVED.want | dialog | ~half-day |

The 7-verb cairn substrate (OBSERVE / MARK / PARLEY / REMEMBER / +) is
the natural action vocabulary across these. Same verbs, different
arrangements per engagement.

## Contact → engagement flow

Today: `roaming_pool.detect_contact(camera_x, camera_y)` returns the
agent in range; brain calls `encounter.on_orb_contact(...)` which
opens a session via `encounter_session.py`.

After: replace `on_orb_contact` with `on_creature_contact` that:
1. Looks up `creature_engagements[kind]` → engagement config
2. Composes engagement state (`world.engagement = EngagementState(...)`)
3. Transitions `game_state.state` → `ENGAGEMENT` (or reuse REFLECTIVE)
4. Emits `engagement_open` StateEvent (`ENGAGE {kind}`)
5. Vector terminal renders the appropriate overlay
6. On commit success: `roaming.consume(agent.id)`, emit win StateEvent, drop loot per quest reward roll
7. On commit fail: `roaming.flee(agent.id)` retreats N meters, increments attempt_count
8. On abort: depends on rule — some allow abort (low-stakes), some lock until commit (high-stakes)

## Win / lose / abort semantics

Per rule, but the defaults:

- **Win** — commit AC True. Creature consumed. StateEvent toast (`{verb} → {kind}`). Quest reward rolls. Player back at HUB.
- **Lose** — commit AC False. State machine increments `attempt_count`; if `attempt_count >= max_attempts` (rule-specific, default 3), creature flees. Otherwise stays open for retry.
- **Abort** — only allowed for `voluntary` engagements (e.g. dialog with a friendly NPC). Forced engagements (hostile / quest-blocking) lock until win. Same as the reflective hp_zero / voluntary distinction.

## StateEvent shape

Reuse the existing primitive. Per engagement:

| Trigger | Toast |
|---|---|
| Open | `ENGAGE {kind}` |
| Each piece placed / response picked | optional, rule-specific |
| Win | `{verb} → {kind}` (e.g. `OBSERVE → orb_red`) |
| Fail attempt | `NOT YET` |
| Flee | `{kind} retreats` |
| Abort | `LATER` |

These are the placeholder strings; voice authoring is its own arc per
the workroom AC's V1 limitation list.

## Open questions

1. **REFLECTIVE state reuse vs new ENGAGEMENT state.** Reflective is
   semantically about "self-reflection / fridge composition." Creature
   engagements share the *shape* but not the meaning. Two paths:
   - Reuse REFLECTIVE → simpler, but conflates two distinct narrative beats.
   - Add ENGAGEMENT → cleaner, requires another `game_state` transition
     row + parallel state on BrainWorld. ~30 LOC.

   **Recommendation:** add ENGAGEMENT. The reflective fridge stays for
   actual self-reflection / HP=0 path. Engagements are creature
   contact; they need their own narrative tag.

2. **Where does the creature stand visually during the engagement?**
   The orb is in the world; the overlay is screen-space. Two options:
   - World freezes (player can't move, orb stays in place) until commit.
   - World keeps running (other creatures roam, ambient continues) but
     player input is intercepted by overlay.

   **Recommendation:** world keeps running. Matches the "async quests
   evaluate every tick" doctrine. Overlay is non-modal in spirit even
   if input is captured.

3. **Loot vs progression vs lore reveal.** Different engagement
   outcomes should drop different things:
   - Combat-shaped → physical loot (already supported via quest rewards)
   - Dialog-shaped → lexicon entry / NPC reputation / lore unlock
   - Puzzle-shaped → world state mutation (door opens, pillar unlocks)

   **Recommendation:** add an optional `on_win: list[effect_dict]` to
   each engagement entry. Effects routed through the consequences
   engine (already exists). Same shape as quest rewards — extends, not
   replaces.

4. **Multiple kinds → same engagement?** e.g. all `orb_red` use
   compose_three; all `orb_blue` use pattern_match. Or each individual
   creature instance has variation? Rule registry per-kind is
   simplest; instance variation lives in `rule_args` (e.g.
   `target_count: 5` for a tougher orb).

   **Recommendation:** per-kind for V1. Instance variation is an
   advanced authoring need.

5. **Engagement during quest predicate evaluation.** What if the
   player commits an engagement that satisfies a quest predicate
   *and* drops loot? Order of operations matters.

   **Recommendation:** quest tick fires first (quest sees the
   `creature_engaged` event and can mark complete), then loot rolls,
   then state events emit. Same ordering as today's quest reward path.

6. **Engagement as the modding surface.** Per `design_north_star`
   Phase 3 (terminal-as-modding-interface), engagement configs are
   *the* mod hook. A modder writes a JSON entry pointing at their own
   rule/pool/AC and ships a new creature interaction without touching
   engine code.

   **Recommendation:** ship the spec assuming this is true. Make the
   registry hot-reloadable so modders iterate fast.

## Cairn substrate hook

Per `design_cairn_substrate`: 7 verbs (OBSERVE / MARK / PARLEY /
REMEMBER / + 3 others), d20 saves, 3-ability cap, resonance gate.

Each engagement *uses verbs from the player's `verbs_known`*.
A player who hasn't learned PARLEY can't pick the dialog-shaped
engagement at all — it appears greyed out, encouraging them to find
PARLEY first via discovery.

Saves resolve mid-engagement when relevant: e.g. a rhythm engagement
might call for a DEX save (timing tolerance widens by save margin).
The engagement's `rule_args` includes optional `save_required: ["DEX"]`.

## What this looks like in V1 ship terms

1. **PR A** — `EngagementState` dataclass + `engagement` registry +
   `ENGAGEMENT` game state transition. Reuses reflective state machine
   shape; adds the per-kind dispatch.
2. **PR B** — Wire orb contact (replace encounter_session for orbs).
   Author 1 engagement type (`compose_three` already exists, just point
   `orb_red` at it). UAT: walk into orb, fridge-style overlay opens
   tinted differently, commit closes the encounter.
3. **PR C** — Add `pattern_match` engagement + a second creature kind
   that uses it. Now there's variety.
4. **PR D** — Cairn-verb gating. Greyed-out options. Saves rolling.
5. **PR E** — Loot + lore on_win effect dispatch. Multi-result wins.

Estimated: 2-3 sessions for PRs A+B; subsequent PRs can ship
asynchronously as content additions.

## Out-of-scope (forever)

- HP-bar combat against creatures
- Click-to-attack / DPS optimization framing
- Aggro mechanics, threat tables
- Damage numbers, level scaling formulas
- "Kill X creatures" quest verbiage (replace with "engage X creatures")

The engagement model rejects the mechanical-extraction frame. Every
encounter is a *meeting*, not a fight.
