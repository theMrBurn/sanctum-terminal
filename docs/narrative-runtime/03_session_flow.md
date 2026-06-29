# Canonical Session Flow

## Overview

The Sanctum runtime is **one machine wearing different weather**. Underneath every session is a single hub-and-spoke state machine (Terminal's `game_state.py`, four states: `CHARACTER_CREATION / HUB / REFLECTIVE / ENGAGEMENT`) sitting atop **one predicate-gated beat engine** (the `consequences` substrate: `trigger → resolution → Effect[]` over `ConsequenceInstance{context, progress}`), driven by **one atomic event — the deed** (Flipper's append-only `deeds` ledger). Story is swappable DATA authored as config rows on that spine; the engine is affect-neutral and never imposes a mood. Quests, expeditions, dialogs, the 9 goal-shapes, the 8 modifier-cards, the prologue, and the Reckoning are all the same thing: consequence instances riding on `world.session_frame`, not new states or lifecycles.

The structural thesis is **one deed, three readers**. Every committed action emits a deed, and that single deed is read by (1) **axis-growth** — the always-grant intrinsic reward across BODY/CRAFT/SIGHT/MIND/HEART/WILL; (2) the active **goal-shape accumulator** if its `theme_mask` overlaps; (3) the **identity tension accumulator** if the act runs against your alignment blob. One write, three ledgers. These are three tiers of the *same* bounded `net_passes`-to-threshold primitive: tier-1 beat comprehension, tier-2 session goal-shape, tier-3 cross-session identity → the Reckoning. No new resolution math is ever invented; shapes, cards, and the Reckoning only parameterize the one accumulator.

Nothing terminates, because the **write-back spine runs at two altitudes**: a beat resolves by re-engaging its PO source, which seeds the next beat (micro); whatever a sitting did not reach is written back as next session's opening framing questions and/or the Carried Thing (macro). "Questions are the grammar at every scale" is therefore the literal no-dead-end proof — a shortfall is never game-over, it is a reframed question. Truth is `base_seed` + append-only input-log, state derived by replay; all cross-session marks (Scar, Bond, Carried Thing, identity shift) are input events replayed as overlays, never seed mutation, never per-chunk storage. The felt north star is **"return to a lit room"**: the world was running before you sat down, it moves only when you move, and silence is load-bearing. The whole flow is operable text-first through **one DialPrompt N-option grammar** on a number-row keymap (`1-9/0` jump-select, `←→/h-l` move, Enter commit, Esc back-to-hub, `.` drill, `s` summon stats, `:` command line, `?` legend; zero F-keys), with reveal-tiers AMBIENT → GLANCE → SUMMON.

---

## Stages

### 1. Boot (load-or-fork)

- **Trigger:** Every app launch, before anything is dwellable. A transient bracket, not a screen.
- **What happens:** Derive `base_seed` from the `real_self` id (stable, never stored as authority). Open or create the append-only input-log + deeds log; scan deeds to rebuild the int16 axis-delta rollup in RAM. RAM-only per-session deeds caps reset here (the session boundary). If a log exists, **replay** it to derive current world/character/identity state; if none (or unreadable), this is the first-ever case.
- **Player input:** None — implicit (presence of a save).
- **Engine events:** `DeedsState{delta[6], session_counts=0, loaded}`; a derived in-memory state snapshot or a "no character yet" signal; a boot `StateEvent(register=system)`. No RNG draws yet.
- **Components:** `save_io`/`save_state` (tolerant versioned loader), `deeds_init/deeds_load`, `game_state.initial()` vs `fresh_character()`, `deltas.c` replay.
- **Loop closure (success):** Clean log replays → returning player lands at HUB → route to **Session-Open**. First-ever (no log) → route to **First Light / Draft**.
- **Loop closure (failure):** Corrupt/partial log → tolerant loader rebuilds from `base_seed` + the salvageable prefix, drops only unreadable trailing events, continues. A broken save degrades to onboarding; it never bricks.
- **Law check:** ✅ Both branches reach a dwellable state. A missing log *is* the first-ever case, not an error.

### 2. First Light & The Becoming — Draft (first life only)

- **Trigger:** First-ever boot (no input-log). FSM state = `CHARACTER_CREATION`. Re-enterable later from HUB via the Pillar of Reflection.
- **What happens:** No menu, no title card. You open into a single **lit place and one present-tense line** — the register set before a rule exists. The very first act is answering one quiet dial (teaching *commit* by doing). Then you come into being by answering a short series of pillar questions about who you have been (years / a marking day / what you are called; name defaults to `$USER`). Identity is folded as an append-only event stream: each answer appends a `PillarEvent`; the sheet is **derived** (latest-event-per-pillar), so it is re-doable and never destructive. The six axes are derived and shown felt-first. **This is the macro-question the whole life rhymes with** — the question-grammar lesson, taught by living it.
- **Player input:** DialPrompts (RITUAL register): `1-9`/`←→` highlight, Enter commit; Esc steps back a pillar; NARROW cascade for ranges (age); `s` previews the sheet-in-progress.
- **Engine events:** `PillarEvent` appended → draft re-folds; on finalize, canonical `CharacterSheet` over the 6 axes; age clock zeroed at birth-age; neutral alignment blob initialized; any value-rule RNG uses integer-FNV.
- **Components:** `character_draft.py` (PillarEvent fold), `pillars/*`, `dial_prompt.py`, `character_sheet.py`, `game_state.transition(CHARACTER_CREATION → HUB)`.
- **Loop closure (success):** Required pillars satisfied → finalize emits the sheet → **Prologue** (first life) or, on re-entry from HUB, back to HUB.
- **Loop closure (failure):** Incomplete/abandoned draft self-loops in DRAFT (append another event, re-fold). There is no invalid sheet — it is always derived from whatever events exist.
- **Law check:** ✅ Event-sourced derivation makes "wrong" impossible; the only exit is forward.

### 3. Prologue — teaching beats (first life only)

- **Trigger:** Immediately after first finalize, while the input-log carries no `prologue_complete` event. Short-circuited for any returning character. Runs at HUB as a fixed-seed goal-shape (Large-Iterative) authored entirely as `'prologue'`-tagged config rows — **not a separate tutorial code path**.
- **What happens:** The tutorial is the loop teaching itself, one concept per beat, **by doing**, and every evocative name is *earned by the act before it is spoken*. No D&D-manual lecture, no "Tip:", no glossary — that is a hard voice rule. You act once and watch an axis nudge → the word *deed* is named in the doing. You face one gentle beat and pick verbs → you see the *comprehension accumulator* fill at its lowest stakes. You place one stone on a small pile → the game names it a *cairn*. You speak one limit aloud → *Going Without* becomes a thing you've done, not a card you read. The final teaching beat re-seeds the next line (the *write-back*) and surfaces the framing-question grammar, handing directly to Session-Open. The keymap is introduced incrementally at the exact beat each key first becomes useful.
- **Player input:** DialPrompt choices on a guaranteed-good path; the player performs each taught verb at least once.
- **Engine events:** Each beat = a `ConsequenceInstance` resolving with a guaranteed deed + `StateEvent`; the prologue is canon (real appended events). The terminal beat appends `prologue_complete` and a write-back seeding session 1's first question. AMBIENT vitals/axis strip is permanently lit on completion.
- **Components:** `consequences` substrate (prologue rows), `deeds.c` (first axis grants), `encounter_resolver` (net_passes, on rails), the Cairn stone primitive, the Going-Without verb-cap, the write-back adapter, reveal-tiers.
- **Loop closure (success):** Final teaching beat completes → fold into **Session-Open**.
- **Loop closure (failure):** A refused/mis-acted teaching beat does not stall — it re-surfaces with a broader hint (self-loop). The prologue cannot be failed out of; the only exit is forward.
- **Law check:** ✅ Onboarding obeys the same no-dead-end law it teaches — a fumble is itself a deed.

### 4. Session-Open — framing questions (shape + drift + cards + carry)

- **Trigger:** The start of every sitting (after Boot-replay, or after the prologue on life one). The macro "return to a lit room" re-entry point. Transient bracket into HUB.
- **What happens:** The PO source is read **first** so there is no cold start; it returns `PoEntry{severity:1-5, theme_mask, people:relation}` rows the questions are built from. A short DialPrompt series (RITUAL register, framed diegetically as intent, never as a settings/loadout menu) sets the session's **GOAL-SHAPE** (1 of 9) and its **thematic drift** (seeds the Pool bias vector), and may **draw MODIFIER-CARDS** via `pool.c` bag-draw. Crucially, **unreached items written back by the previous session surface here as the candidate framing questions** — the room is already wearing your carried state. The Carried Thing / Burden, Scar marks, and Kindred bonds are rehydrated from the input-log as overlays. This is where the session's *weather* is chosen: same engine, tinted elegiac under Cairn + Carried Thing, warm under Tending + Kindred, curious under the Standing Question.
- **Player input:** 3-5 DialPrompts selecting shape, drift, and accept/decline of card draws; Going Without is sworn here as a question; The Turning is read from the almanac here. Strong defaults (`default_index` = your usual shape, a "just begin" option) let a returning player one-key into play.
- **Engine events:** `SessionFrame{goal_shape, theme_mask, cards[], carried[]}` appended; the goal-shape's governing `ConsequenceInstance` (the tier-2 spine accumulator) spawned, plus one instance per drawn card; Pool seeded from `theme_mask`; carded draws + Pool seeding use integer-FNV.
- **Components:** `dial_prompt.py`, the goal-shape registry (9 shapes as config rows), the 8-card deck, `pool.c` bag-draw, the PO source interface (pluggable, tolerant of empty/offline), the write-back overlay replay, the almanac source (The Turning).
- **Loop closure (success):** Questions answered → tier-2 shape + card operators armed → enter **Hub**.
- **Loop closure (failure):** Player declines or the opener-well is empty / PO source offline → engine installs the default shape (Exploration, or Single Goal seeded from the most-recent PO entry) and proceeds to HUB anyway. A returning player cannot decline a Carried Thing — but *chooses how to hold it*, which is itself the first beat.
- **Law check:** ✅ A sitting can never fail to start; an unanswered frame becomes a default frame.

### 5. Hub / The Standing — exploration, the world-clock spine

- **Trigger:** The dwellable centre of every sitting. Entered after Session-Open; returned to from every spoke. Where the player spends most time.
- **What happens:** Contemplative free traversal where **the world advances one tick only when you act**. Each committed action ticks the turn-clock once, drifts the Pool bias, tints time/weather as ambient *input* (not driver), and surfaces beats **relevance-gated**. The optional **EXCHANGE** module (an economy; off by default, forge floor-tier guarantees no wasted pull) is a spoke off HUB here. **The Quiet Between** lives inside this stage: when nothing resonates, the engine does *not* manufacture content — the room stays quiet and the quiet is *textured* (drift shifts, season turns a degree, the carry sits heavier or lighter). Silence is the soul of "a life, not a campaign," not dead air. Zone/beat transitions are a self-loop: crossing a typed transition (door/stairs/edge/secret) regenerates from `(base_seed, cx, cy)`, overlays the input-log, and **proves beat-layer reachability** (`carve_egress` ported to the beat graph) before surfacing the next beat.
- **Player input:** One world-verb per tick from the shared 7-verb grammar (move/OBSERVE/MEDITATE/MARK/PARLEY/KINDLE/REMEMBER-INSCRIBE); Tab focuses the glance strip; `.` drills; `s` summons stats (no tick, free inspection); `:` command line; Esc inert (this is the hub).
- **Engine events:** `advance_turn` → `tick++`, Pool drift step (integer), weather/chronometer tint, `consequences.tick()` trigger phase; a resonant beat spawns a beat `ConsequenceInstance`; a non-resonant tile returns control with a faint familiarity tick.
- **Components:** `game_state` HUB, `advance_turn`, `pool.c` drift + anti-monotony, the resonance gate (`encounter_engine` worth_knowing), beat-layer `carve_egress`, `deltas.c` overlay on regen, the EXCHANGE module (optional).
- **Loop closure (success):** A relevant beat crosses threshold → **Beat / Encounter**. Secondary: rest/milestone → Consolidation; vendor tile → EXCHANGE overlay.
- **Loop closure (failure):** Nothing resonant (silence) → HUB self-loops with a familiarity tick (wandering that finds nothing is still a step). Budget exhausts → route to Session-Close with partial growth booked. The only true failure mode is the engine breaking silence to fill it — which the relevance gate exists to prevent.
- **Law check:** ✅ Every spoke returns here; the hub never terminates; the generator guarantees the well never empties.

### 6. Beat / Encounter — the comprehension accumulator

- **Trigger:** A spoke off HUB (FSM `HUB → ENGAGEMENT`), entered when a foe/agent/resonant beat/dilemma crosses the disposition or relevance threshold.
- **What happens:** A live beat resolved by the **comprehension accumulator**, never a binary if/then — and the *same primitive* whether it is a fight, a parley, a study, or a memory to tend; only verbs and tint differ. The antagonist (or memory, or friend) **telegraphs before it acts** (phase → weighted intent → effect), so the threat coils visibly before you choose — what makes turn-driven play contemplative rather than reflexive. Each round the player picks a verb (fight / understand-study / parley / scan / flee / an earned ability); the resolver runs a stat-gated check and adds `net_passes` toward the threshold. **Damage (HP=0) is one axis among several** — a beat is winnable by understanding or parley with zero HP lost. Every round emits a deed → read by all three readers. Card operators fire at their triggers here: Ember ticks per beat, Two-Faced Omen resolves at the accumulator midpoint, the Scar marks at a session-defining cross, the Dread Tower depletes its dread pool on RISK-themed beats. Combat verbs are **not** a bespoke control scheme — a DialPrompt in TENSE register, same `1-9`/Enter grammar.
- **Player input:** One verb per round; `.` inspects the telegraph; `s` checks axes mid-beat; Esc opens a "withdraw?" confirm dial (error prevention in TENSE register — no fat-finger abort).
- **Engine events:** `resolve_action` → `net_passes` written to `ConsequenceInstance.progress` (integer-FNV); orb intent telegraph + action; a deed **staged** per act; `StateEvent(register=tense)`.
- **Components:** `encounter_resolver` (net_passes; dialog stance/posture), `actor.py` (telegraph AI), `deeds.c` (the three-reader event), `pool.c` (Ember/Omen/Dread draws), the card operators, abilities-as-verbs.
- **Loop closure (success):** Threshold met → **Resolution + Write-back**.
- **Loop closure (failure):** Three honest doorways: (a) flee/portal → partial deed (0.25×, learned by walking away) → HUB; (b) HP=0 → **The Fall**; (c) Ember/Dread expiry → the threatened thing *happens* and becomes the next beat (expiry is a doorway). Otherwise self-loop: choose the next verb, accumulator continues.
- **Law check:** ✅ No branch is a terminus; never a single binary if/then.

### 7. Resolution → Intrinsic Reward → Write-back (micro)

- **Trigger:** Any beat resolves — success, flee, or budget/relevance expiry. The resolution phase of the beat's `ConsequenceInstance`. Transient.
- **What happens:** The single most important closure. HOW you resolved (`stance_history`) selects which branch's effects run (mutate flags / heal / `open_dialog_branch`). **Reward is always-grant:** a guaranteed intrinsic axis-growth deed lands — never `rewards=[]` — nudged toward the axis matching how you acted; optional loot is an Effect on top. Completion then **re-engages the beat's SOURCE** (the unified `REMEMBER` + `journal_followup` adapter), which re-files the source and **seeds the next beat** — finishing something is how the next thing is born. Tension toward the Reckoning accumulates here if the verb ran against your alignment blob.
- **Player input:** Mostly engine-driven; one optional acknowledgment dial (REFLECTIVE register) if the beat writes back to a PO source ("re-file this as…"); pure-acknowledgment, never fail-able.
- **Engine events:** Staged deed committed to the append-only ledger (axis delta to rollup); resolution `Effect[]` dispatched in order; a `write_back` input event appended (idempotent FNV line-id); beat marked consumed in a **session-scoped** `resolved_mask` (can re-surface later runs, not permanently spent); optional loot via integer-FNV (float RNG forbidden).
- **Components:** the unified source write-back adapter (pluggable PO sources), `deeds.c` (always-grant), `effects.py` (set_flag/heal/give_item/open_dialog_branch), `resolved_mask`, the alignment-blob tension accumulator.
- **Loop closure (success):** Source re-seeded → **Hub** with a fresh chained beat already seeded → if tension crossed its threshold this resolution, the **Reckoning** is flagged for the next Consolidation boundary.
- **Loop closure (failure):** Not possible — resolution always pays something. A write-back that can't reach its source degrades to a local axis grant (fail-soft), never a payless beat.
- **Law check:** ✅ Always-grant supersedes Terminal's staged-XP wipe; the well never empties.

### 8. The Fall — defeat as doorway

- **Trigger:** HP=0 in an Encounter. Routing strictly obeys `_ALLOWED_TRANSITIONS`: `ENGAGEMENT → HUB` first, then a HUB-side `hp_zero` consequence routes `HUB → REFLECTIVE`. FALLEN is a transient grace-counter phase on world state, **not** a 5th FSM state.
- **What happens:** The headline "failure is a doorway, never GAME OVER" moment. Defeat = diminishment + relocation + a teaching, never a terminus — loss is the cost of having cared, not a buzzer. The player is routed into the **reflective compose-from-a-word-pool** interlude under an acceptance-condition (AC) rule. Composing through it grants recovery; **clean recovery is rewarded** (a WILL-class `FALL_CLEAN` deed). On exit the world reseeds/relocates the player diminished (reduced HP/resources) with a grace window suppressing immediate re-contact.
- **Player input:** The reflective compose grammar — `↑↓`/`1-9` highlight, Enter place, Esc remove last, commit when AC met. Shared grammar means defeat needs **zero new controls**.
- **Engine events:** `consequences.json hp_zero` → `enter_reflective`; on commit-pass: emit RESPAWN, regen/relocate world, restore HP (diminished), grant `FALL_CLEAN` if clean, set grace window.
- **Components:** `reflective/state_machine.py` (AC-gated, no fail-out), `reflective/magnets.py` (seeded compose pool), `reflective/ac_predicates.py`, `player_fall` (no permadeath), `deeds.c`.
- **Loop closure (success):** AC passes → exit to **Hub**, diminished but grown.
- **Loop closure (failure):** A failed commit loops back to composing — the reflective primitive cannot be failed out of; the player sits with it until acceptance passes, then always returns to HUB.
- **Law check:** ✅ Death is structurally converted into a closed loop with a growth hook.

### 9. Consolidation / Settling — growth commits and the age tick

- **Trigger:** A state-change milestone — rest, name-day, or a depth threshold. **Never cron** (schedule by state change, not time). Transient phase off HUB.
- **What happens:** Staged deed/axis deltas roll up into permanent depth; the level ticks off the **AGE clock** — a tick is a *birthday*, not a power-up (level = age, "a life, not a campaign"). Ability slots may unlock into the 3-cap pool (CORE/EQUIPPED/FLOW); RAM-only anti-grind caps rebind to an **in-game epoch** (a game-day), not app lifetime, so they survive replay. Both cadences run: per-act deeds (micro) + life-stage `class_history` prestige (macro). The register is settling, exhalation. This is also the deterministic surfacing point for a pending Reckoning.
- **Player input:** Enter rest, or none (fires on milestone). If a slot unlocks, one AMBIENT-register dial to choose which earned verb enters the active set; Esc defers to next rest; `s` shows the deltas.
- **Engine events:** `consolidate()` folds staged XP → depth; deeds delta committed to lifetime rollup; possible ability unlock; cap reset rebound to in-game epoch; age tick off the day clock; a Reckoning-flag check.
- **Components:** `consolidate()` (encounter_engine), `character_sheet.py` (class_history fold/prestige), `pillars/days.py` (age clock — fixes the inert Flipper level field), `deeds.c`, the 3-cap abilities.
- **Loop closure (success):** Growth commits → if a Reckoning is pending, route to **The Reckoning**; else return to **Hub**, a little older.
- **Loop closure (failure):** No qualifying growth → no-op rest still returns to HUB (an empty rest is still rest); staged deltas, if any, stay staged and re-commit next milestone — nothing is lost.
- **Law check:** ✅ Growth is monotonic and append-only; the spoke always closes to the hub.

### 10. The Reckoning — tier-3 identity interrupt

- **Trigger:** Conditional and **rare**: fires when the tension accumulator crosses its rigidity-scaled threshold. **Deterministic surfacing rule:** always at the next Consolidation boundary after the threshold crosses; Session-Close only as a backstop if the sitting ends first. **Never mid-beat.** Often cross-session. (Distinct from the *Cairn* goal-shape — see Resolved Tensions.)
- **What happens:** Your alignment is a **blob of ever-shifting potential** across the 6 axes — no morality scalar, no D&D grid (Disco Elysium refuses to score a life; so do we). In-character acts deepen the profile; against-character acts accumulate tension on the *same* bounded accumulator as combat, with the Dread Tower's fall, accrued Scar, and Carried-Thing severity as additional feeders. Past threshold a weighty **Reckoning beat** fires — a re-centering ridden on the reflective primitive, **not a number flip**. **Rigidity** grows with age/consistency: the threshold climbs (resists longer) and the eventual shift snaps harder — rarity gives it weight; a Reckoning late in a life is a tide coming in, not a course-correction. Visibility is felt-through-world by default, but the pure stats page is always visitable ("present felt-first, never hide the math"). Reputation = the world's disposition FSM re-reading the new profile.
- **Player input:** The reflective compose/commit grammar — a weighted choice about who you are becoming; `s` shows current-vs-shifting blob. No free-text.
- **Engine events:** A Reckoning `ConsequenceInstance` (trigger = `tension_over_rigidity_threshold`) routes `HUB → REFLECTIVE`; on commit, an append-only profile-shift input event (a Scar-class high-weight mark, replayed as overlay, never seed mutation); tension drains; rigidity +1; disposition FSM re-reads. All tension math integer.
- **Components:** the tier-3 tension accumulator (shared primitive), `reflective/state_machine.py`, the disposition FSM, the Dread Tower / Scar / Carried Thing feeders, the always-visitable stats renderer.
- **Loop closure (success):** Blob re-centres, tension resets, rigidity +1 → return to the surfacing point (HUB or Session-Close), changed at the root.
- **Loop closure (failure):** The player **resists** → the shift is refused, tension partially drains but leaves a residue, rigidity hardens further (it will snap harder next time) → returns cleanly. The Reckoning is deferred, never blocked.
- **Law check:** ✅ Even the consequence layer obeys "a state change, never binary"; routing stays `HUB → REFLECTIVE → HUB`, no spoke-to-spoke jump.

### 11. Session-Close — goal-shape resolution (exit-trigger)

- **Trigger:** Fires from *inside* the play loop the instant the tier-2 goal-shape resolves OR the turn/relevance budget expires. Resolution is an **exit-trigger, not a post-loop phase**. Close is not a 5th FSM state — the machine stays at HUB.
- **What happens:** The goal-shape resolves in its own idiom, and **both endings route here**: Single (threshold crossed) / Iterative (final link) / Exploration (drift satisfied) / Timed (beaten before the clock) / Vow (fulfil / renew / honorable-forswear) / Cairn (drained to zero by integrate/release) / Tending (graduate or go fallow) / Standing Question (all K-positions lock) / Converging Threads (quorum reached) — or **EXPIRY** (budget runs out first). The close is **quiet** — no victory fanfare, no "Session Complete" scorecard (that is marketing-voice; we do not sell to the player). The instrument simply notes what the day held and what it leaves you carrying. Partial growth is always booked.
- **Player input:** None required (auto-fires); optionally the resolving act of the shape (place the last stone, lock the last position, renew the vow) and one acknowledgment dial per unresolved thread ("let it rest as…"), or Esc to accept defaults.
- **Engine events:** A `SessionClose{resolved, partials[], write_backs[]}` input event appended; deeds committed; `StateEvent(register=ritual)`. No state stored — everything derivable by replay.
- **Components:** the 9 goal-shape resolution rows (integer end-states), the consolidation fold, the session chronicle as input-stream (not a verdict).
- **Loop closure (success):** Shape resolved → may RENEW into a harder follow-up → into **Write-back / The Carry**.
- **Loop closure (failure):** Budget expiry → identical path; the unreached simply becomes a heavier opener / Carried Thing → into **Write-back / The Carry**.
- **Law check:** ✅ Failure is mechanically indistinguishable from success at the closure layer; there is no losing session.

### 12. Write-back / The Carry — macro loop closure

- **Trigger:** At Session-Close, computing what travels forward; **consumed at the next Session-Open**. This is the macro loop closing.
- **What happens:** Completed work re-files its PO source and may renew; **unreached work** — the unfinished chain, abandoned threads, an under-threshold Vow, a forsworn vow's loss, a released/lost memory, a missed Turning, a neglected Bond — is emitted as append-only input events that become (a) next session's opening framing questions and/or (b) the **Carried Thing / Burden** (the explicit consumer of forswear/loss write-backs). A Scar marks a place that will spawn healable beats; a Bond's neglect sediments into distance. **Your choices ARE the save** — never a slot, never a perfect-retry (a time-loop would erase append-only truth). This carry is what makes the next Threshold "return to a lit room" instead of a fresh start.
- **Player input:** None — the engine folds the session's input-log; the player's only input was living the session.
- **Engine events:** Append-only input events (Burden / Scar / Bond-distance / opening-question seeds) written to the log, to be replayed as overlays at the next open; the log flushed (the log IS the save).
- **Components:** the unified write-back adapter, the Carried Thing cross-session consumer, the append-only input-log (truth = seed + replay), `deltas`/`deeds` overlay, the next Session-Open.
- **Loop closure (success):** Carry written → next Boot → Session-Open reads these write-backs as its opening questions → the life continues.
- **Loop closure (failure):** Nothing is failable; even an empty session writes "a quiet day" forward.
- **Law check:** ✅ The only true closure in the system is the one that re-opens; a life never ends in a tombstone, only in tomorrow's questions.

---

## Prologue teaching plan

Every concept is taught **by doing**, and every evocative name is **earned by an act before it is spoken** (hard voice rule: no manual, no glossary, no "Tip:"). Teach the **load-bearing five** in the prologue; let rarer shapes/cards teach themselves on first natural draw via a one-line in-context reveal (keeps the contemplative tone from ballooning into a long on-rails opening).

| Concept | Taught by doing | Name earned when |
|---|---|---|
| **Commit (the core verb)** | The cold-open First Light dial — one unfailable choice; attending *is* the begin. | Implicit; the keymap's first lesson, before any vocabulary. |
| **The question-grammar** | The Becoming/Draft pillar questions — you come into being *by answering questions about who you've been*. | Named as "questions are how this place speaks" only after you've answered several. |
| **The comprehension accumulator** | One gentle beat with multiple verbs; you *see* the threshold fill over 2 successes. | "comprehension"/threshold surfaced at the moment it visibly fills. |
| **The deed / always-grant axis reward** | Act once; an axis quietly nudges; "you just did X — that was a *deed*" lands as it happens. | The word "deed" appears in the doing, never defined first. |
| **The write-back spine** | A teaching beat that re-engages its source and *re-seeds the next line*. | Felt as "finishing this made the next thing" — no jargon needed. |
| **One modifier-card (Going Without)** | You speak one small limit aloud and feel a verb close to you. | "Going Without" / "vow" earned by having sworn it. |
| **The Cairn (one stone)** | You place a single stone on a small pile. | The game names it "a cairn" *as your hand places the stone* — so the later Cairn goal-shape already means something. |
| **Reveal-tiers / stats** | The AMBIENT strip lights with your first axis; then `s` is taught as "look at what you've become." | "summon" / stats page introduced last, when there is finally something to look at. |

A fumbled teaching beat is itself a deed (you learn by the fumble) and re-surfaces gently — the prologue cannot be failed out of, modeling the no-dead-end law by experiencing it once. The final beat appends `prologue_complete` and seeds session 1's first framing question.

---

## Resolved tensions

- **"The Reckoning" name collision.** The goal-shapes deck once renamed its retrospective drain-to-zero shape "The Reckoning," colliding with the consequence/identity layer of the same name. **Resolved per the locked brief:** the goal-shape is **The Cairn** (taught by placing one stone in the prologue); **The Reckoning** is *only* the rare tension→identity-shift layer. The two never share a surface name. Final player-facing wording routes through cultural-eccentric (user-vocabulary-is-canonical).

- **FSM: four states, not more.** Systems and player-op lenses described SESSION_OPEN/CLOSE, CONSOLIDATION, EXCHANGE, FALLEN, and the Reckoning as if states. **Engine-grounding lens wins:** the FSM stays `CHARACTER_CREATION / HUB / REFLECTIVE / ENGAGEMENT`. Session-Open/Close are transient brackets; Consolidation is a transient milestone phase; the Fall's FALLEN is a grace-counter on world state; the Reckoning and the Fall both ride the existing REFLECTIVE state; goal-shapes/cards ride `world.session_frame` as ConsequenceInstances. All routing obeys `_ALLOWED_TRANSITIONS` — no spoke-to-spoke edges (defeat is `ENGAGEMENT → HUB → REFLECTIVE`).

- **Draft before or after Prologue?** Lenses split 2–2. **Resolved on the hard engine constraint:** prologue beats land deeds on axes, which requires a finalized `CharacterSheet`, and the prologue runs at HUB while Draft is the `CHARACTER_CREATION` state. So **Draft (The Becoming) precedes the prologue's teaching beats**, and the Draft's pillar questions *are* the prologue's first lesson (the question-grammar, taught by living it) — folding the feel-lens instinct that "you come into being by answering questions" without violating the FSM.

- **Reckoning surfacing timing.** Flagged as potentially arbitrary (Session-Close one time, Consolidation another). **Resolved to a lawful rule:** always at the next Consolidation boundary after the threshold crosses; Session-Close is only a backstop if the sitting ends first; never mid-beat. Its timing reads as lawful, not random.

- **The Quiet Between as a "stage."** It is the soul of "a life, not a campaign" but is *not* an FSM state. **Resolved:** it is a named, load-bearing *felt movement inside the Hub* — the resonance gate returning control to HUB with textured ambient drift. Defended as load-bearing; the only failure mode is the engine breaking silence to fill it, which the relevance gate prevents.

- **Always-grant vs Terminal's staged-XP wipe.** **Resolved by the lock:** always-grant supersedes the wipe everywhere, including defeat (the `FALL_CLEAN` recovery deed). No `rewards=[]`, no XP-strip; failure is teacher, never tax.

- **EXCHANGE / economy.** **Resolved:** an optional spoke off HUB, off by default; the runtime is fully playable with zero economy; if enabled, the forge floor-tier makes "no wasted pull" literal. Market is a module, not a pillar.

- **Prologue scope.** Feel-lens wanted every name earned; systems-lens warned of bloat. **Resolved:** prologue teaches the load-bearing five (+Going Without +Cairn-stone because they earn high-frequency names); rarer shapes/cards self-teach on first natural draw with a one-line reveal.

---

## Open seams

- **Beat-layer `carve_egress` is the single biggest unbuilt invariant.** `carve_egress` proves *spatial* reachability today; the beat graph has no equivalent. If the write-back spine ever seeds a beat whose preconditions are unsatisfiable from the current state, you get a silent dead end that violates the core law. A real "prove every seeded beat reachable, or carve a connecting beat" check must exist **before** any chaining shape (Iterative, Converging Threads, Standing Question) is trusted.

- **Tension-accumulator tuning is unspecified and high-risk.** "Against-profile" must be a distance metric over a 6-axis potential field (not a scalar). Too sensitive → Reckonings fire constantly (losing rarity/weight); too dull → they never fire. The rigidity curve compounds this. Needs a golden-vector tuning pass with real PO data; the name's weight depends on Reckonings staying genuinely rare.

- **Multiple parallel tier-2 accumulators.** Standing Question and Converging Threads run 2–4 live goal-shape accumulators at once. "One deed, three readers" assumes a single active goal-shape accumulator; these need the deed routed to N parallel accumulators by theme overlap, plus the cross-pollination draw on abandonment. A real extension of the routing rule, not a free parameterization — flag for the spec author.

- **Determinism conformance on tier-2/tier-3 math.** Any shape/card/tension math on the byte-equal C↔Python path must use integer-FNV, not float. The reflective compose pool (`reflective/magnets.py`) and the reward roll (`rewards.py`) currently use float RNG — port both, and gate with the golden-vector harness (spec 53). The Vow tick (popcount) and Converging quorum must be integer-specced from the start.

- **One stat vocabulary / check rule is still contingent.** The whole accumulator economy assumes deeds map cleanly onto the 6 axes and that the resolver reads the same sheet. Terminal's two disconnected stat systems (PlayerState's d20-saves vs CharacterSheet's 6 stats) must be collapsed **first**, or "how you acted → which axis grows" has no single source of truth. Final axis names need cultural-eccentric sign-off.

- **Engine gaps that block stages as written.** (a) Abilities are authored but no resolver reads them — the "verb set expands as abilities are earned" loop must be built; (b) DEFEND is an inert verb (no state change) — implement `pending_flags['defend_halves']` or cut it; (c) a bounded theme-vocabulary bridge (project the open learned lexicon onto a finite byte-equal vocabulary) must exist or goal-shape/card/Pool selection is not byte-equal.

- **Cross-repo PO source contract + persistence migration.** `PoEntry` comes from permanent-objects (separate repo) while the runtime lives in sanctum-engage / sanctum-terminal; the contract must be defined and versioned as a boundary (the Cairn and Session-Open read PO history first, falling back to generic seed if offline). Separately, Terminal progression is currently session-only and tile mutations are lost on LRU eviction — the seed+input-log replay + overlay port (`deltas.c` model) is a substantial precondition for **any** cross-session card (Scar / Bond / Carried Thing) and must be sequenced before they ship.

- **Spatial-vs-graph world call.** The flow assumes a beat-graph backed by the hybrid generator stack (spatial seed-world kept as DATA, never required to render). If a literal spatial overworld survives, door-coherence (canonical-edge hashing) and graded traversal carry; if not, only `carve_egress`'s abstract reachability kernel ports to the beat layer. The Beat/Zone-Transition stage is written to work either way, but the call should be made before building it.

- **Verbatim user-input passthrough (CORRECTED 2026-06-29 — supersedes the earlier "wife's-voice sample" framing, which mis-read the AC as a literary style).** The real rule: any USER-AUTHORED content (note / date / reminder / alert / scheduled item / PO entry) is stored and USED as-is; the engine may key logic/routing off it but NEVER alters it; when surfaced back to a user it is rendered VERBATIM (the user's exact words) — never interpreted, summarized, re-enumerated, or rephrased. Engine-GENERATED narration (templated beats, system flavor) is a SEPARATE text class with no verbatim constraint. Rationale (user): people follow their OWN words; an app-reworded reminder reads as external authority and gets ignored, self-authored reads as self-authority and gets followed. This is the workspace-protocol §2 user-sovereignty line applied to runtime OUTPUT, and it resolves the audit's template-vs-verbatim conflict PER-CLASS (verbatim for user-authored, template for engine). **NO voice sample is required from the user — this is a system rule, not a copy style.**