The advisor caught a real incompleteness in the metric form (ENGINE-DATA's `delta·(SCALE−B[a])` fails the consistency cases; TENSION-MATH's signed mean-form fails the dishonesty case). The form that passes all four cases is a per-axis distance between two *normalized direction vectors*. I've verified that, plus the explicit-drain and integer-normalization corrections, and the cold-start/init handling. Here is the integrated formalization.

---

# THE RECKONING + THE HONEST MIRROR — buildable formalization

## Overview

**How this is modeled.** Identity is a point-and-heading in a 6-axis integer field. You have two things: an **asserted self** (the pillars + your active life-stage class — what you *claim*) and an **enacted self** (your lifetime rollup of deeds — what you've *done*). Both are read as normalized **directions** over `[BODY, CRAFT, SIGHT, MIND, HEART, WILL]`. **Tension is the accumulated divergence of the enacted direction from the asserted direction, attributed per-axis.** When total tension crosses a rigidity-scaled threshold, a **Reckoning** fires at the next Consolidation boundary: a rare, composed, re-centering beat that overrides the age-default life-stage and folds who-you've-become into who-you-claim-to-be.

The **Honest Mirror** is not a second system. Lying to the sheet — claiming an axis your deeds don't support — is *mathematically identical* to acting against your profile: it loads the same per-axis tension vector. There is no separate honesty checker; honesty is enforced by the shape of the data model plus this one metric.

**Three structural decisions, all forced by the task's own constraints (not coin-flips):**

1. **Deeds-vs-BASE, never deeds-vs-deeds-mean.** A metric with no base term literally cannot see a dishonest claim — so the Honest Mirror's deepest enforcement leg would be a no-op. The metric *must* reference the asserted self.
2. **Per-axis vector `T[6]`, never a scalar.** Forced three ways at once: the locked "distance over a 6-axis field, not a scalar" requirement (`04_flow_seamcheck.md:21`); free shift-attribution (the high axes of `T` *are* the directions to re-center toward); and anti-dodge (a scalar with floor-at-0 lets one in-character act launder all cross-axis drift).
3. **Normalized directions, distance form `delta·(D̂[a] − B̂[a])`.** This is the only formula form that passes all four correctness cases (§ The tension metric). Both alternatives the prior drafts carried fail a case.

**Hard precondition (name it loudly).** The metric compares *base* to *deeds*. Today the base is `character_sheet.py`'s d20 sextet (`dex/wis/int_/cha/str_/con`) and deeds are `BODY/CRAFT/SIGHT/MIND/HEART/WILL` (`deeds.h:8-13`). **These are incommensurable.** Build-list #3 — collapse the two stat systems onto the one 6-axis sheet — is a hard precondition. The Reckoning sits strictly *downstream* of the stat-collapse; it cannot be built until `B` and `D` share the 6-axis space.

---

## The alignment blob (representation, init, evolution)

The blob is **two integer direction vectors** over the 6 axes (indices 0–5 per `deeds.h:8-13`). Neither is stored — both are derived in the *same single replay pass* that already rebuilds `DeedsState.delta[6]` (`deeds.c:deeds_load`, ~lines 153–193). One scan, more rollups.

| Vector | Symbol | Raw source | Meaning |
|---|---|---|---|
| **Asserted self** | base `B[6]` → normalized `B̂[6]` | `PillarEvent`s (the Becoming) + active `ClassEntry` life-stage preset | *Who you claim to be* |
| **Enacted self** | deeds `D[6]` → normalized `D̂[6]` | the existing `deeds.delta[]` int16 lifetime rollup (`deeds.c:181`) | *Who your actions say you are* |

`effective_axis = base + deeds.delta` (`deeds.c:98`) is **unchanged** — the blob adds no field; it is a *read* of two vectors that already exist.

### Normalization (the one place a float would sneak in — pin it integer)

Both vectors are projected to a fixed integer scale `SCALE` (e.g. 1000), so a near-zero deed history and a thousand-deed history are comparable as *headings*:

```
B̂[a] = B[a] * SCALE // ΣB        # integer floor division, fixed axis order 0..5
D̂[a] = (D[a] + prior[a]) * SCALE // (ΣD + Σprior)
```

This division is **integer floor, evaluated in fixed axis order** — it is the single float-temptation on the truth path and is pinned as **golden-vector #1**. Everything downstream is add / multiply / compare.

### Init — the blob is *born as your claim* (solves the cold-start)

A naive normalized `D̂` is unstable when `D≈0`: the first deed makes the enacted direction 100% one axis, which would spike tension on a newborn — breaking the locked "young = elastic, no drama" property. Fix: seed the enacted direction with the **asserted base as a prior**.

```
prior[a] = B̂[a] * PRIOR_TOTAL // SCALE     # a small fixed pseudo-count distributed by the claim
```

- **At birth** (`D≈0`): `D̂ ≈ B̂` → every divergence term ≈ 0 → no tension, fully elastic. *You begin as who your pillars say you are.*
- **At maturity** (`ΣD ≫ PRIOR_TOTAL`): the prior is dust; `D̂` is your real deed distribution. *You become what you repeatedly do.*

This is principled, not a patch: the blob is **initialized to the base and shaped by deeds** — born as your claim, sculpted by your life. Inertia is free (when `ΣD` is large, one deed barely moves `D̂`).

### Evolution

- `D̂` drifts as deeds accumulate (slowly — inertia grows with `ΣD`).
- `B̂` is mostly static, moved only by **(a)** an honest re-Becoming (append `PillarEvent`s) or **(b)** a Reckoning's life-stage override (append `ClassEntry`). Both are append-only, latest-wins.
- There is **no profile snapshot** to freeze and no separate trajectory vector. The decisions-log "profile = position + trajectory" model is realized as `B̂` (position/claim) read against the *gradient* `D̂ − B̂` (trajectory). No snapshot lifecycle → determinism stays trivial.

---

## The tension metric (the concrete integer against-profile formula + worked example)

A deed adds `delta` to axis `a`. The tier-3 reader accumulates a **per-axis distance between the enacted and asserted directions**:

```
on DeedEvent(axis a, delta d):
    contrib = d * (D̂[a] - B̂[a])          # D̂ read BEFORE applying this deed (load-bearing)
    T[a]    = clamp(T[a] + contrib, 0, T_AXIS_CAP)
    D[a]   += d                           # now apply the growth
    # (axis-growth tier-1 and goal-shape tier-2 read the same deed — "one deed, three readers")
fired? = (Σ T[a]) >= THRESHOLD            # checked only at a Consolidation boundary
```

**Read `D̂` *before* applying the deed.** This makes consistency *structurally* zero, not a tuning knife-edge: when you've lived exactly your claim, `D̂[a] = B̂[a]` and `contrib = 0` for *every* deed. A pattern must establish (a one-deed lag) before drift strains — thematically, one act is not a betrayal; a pattern is.

`contrib` is **signed**: a deed on an axis you've *under-lived* (`D̂[a] < B̂[a]`) **drains** tension there (you're acting back toward your claim — reconciliation); a deed on an axis you've *over-lived* (`D̂[a] > B̂[a]`) **builds** it. Per-axis floor at 0.

### Why this exact form — the four-case correctness gate

This is the metric's acceptance test. Both forms the prior drafts carried fail a case; only the direction-distance form passes all four:

| # | Claim `B̂` | Live `D̂` | Required | `delta·(SCALE−B[a])` (unsigned) | `delta·(mean−B[a])` (signed-mean) | **`delta·(D̂−B̂)` (this)** |
|---|---|---|---|---|---|---|
| 1 | axis X | axis X | ≈0 (calm) | **FAILS** (every deed adds) | ok | **0 structurally** ✓ |
| 2 | axis X | axis Y | rises | ok | ok | rises ✓ |
| 3 | balanced | balanced | ≈0 (calm) | **FAILS** | ok | **0 structurally** ✓ |
| 4 | balanced | lopsided | rises (dishonesty) | ok | **FAILS** (flat claim → all terms 0) | rises ✓ |

Case 4 is the Honest-Mirror discriminator: *a flat claim lived as a single-axis life MUST generate tension.* The signed-mean form is blind to it (a flat claim has every `mean−B[a]=0`). The direction-distance form catches it because `D̂[Z]` climbs above the flat `B̂[Z]`.

### The late-claim impulse (stock + flow)

The per-deed flow catches *living against your claim*. A symmetric one-shot **impulse** catches *claiming beyond your life* the instant a re-Becoming moves the base — so a late dishonest claim registers immediately, not only on the next deed:

```
on PillarEvent / ClassEntry moving B̂_old -> B̂_new:
    for a in 0..5:
        T[a] += clamp_low0( (B̂_new[a] - D̂[a]) * CLAIM_W )    # claimed MORE than you've lived → spike
```

An honest correction (`B̂_new` toward `D̂`) yields gap ≈ 0 → no spike, and may even let standing tension decay. So a re-Becoming is either **honest-and-relieving** or **dishonest-and-self-punishing**. Together, flow + impulse catch both directions: *acting against your claim* and *claiming beyond your acts*. The system gently pressures your **claim to match your deeds, in either direction** — and the honest resolution is always to re-claim toward the truth (the Honest Mirror's sanctioned adjustment path).

### Worked example (the vector reads its own story)

HEART-claiming elder, `SCALE=1000`. Pillars give `B = [1,1,1,1,5,1]`, `ΣB=10` → `B̂ = [100,100,100,100,500,100]`. A life lived in HEART has `D̂ ≈ B̂` → `T = [0,0,0,0,0,0]` (consistent → calm, structurally).

A session spent acting *against* the tender self (caps per `deeds.c`: STRIKE BODY+1 cap 5, FORGE_HIT CRAFT+1 cap 3):

| Deed (in order) | axis | `D̂[BODY]` *before* (climbing as BODY accrues) | `contrib = 1·(D̂−B̂)` | `T[BODY]` |
|---|---|---|---|---|
| STRIKE #1 | BODY | 100 (= B̂) | 0 | 0 |
| STRIKE #2 | BODY | 108 | +8 | 8 |
| STRIKE #3 | BODY | 117 | +17 | 25 |
| STRIKE #4 | BODY | 126 | +26 | 51 |
| STRIKE #5 | BODY | 134 | +34 | 85 |

Three FORGE_HITs similarly bank `T[CRAFT] ≈ 30`. One in-character PARLEY (HEART, `D̂[HEART] ≈ B̂[HEART]`) contributes ≈ 0 and **cannot drain BODY/CRAFT** (per-axis floor). End-of-session `T = [85, 30, 0, 0, 0, 0]`, total **115**.

**The vector tells the story without extra bookkeeping:** the drift is into BODY (85) then CRAFT (30). When this eventually crosses threshold, the Reckoning re-centers *toward BODY/CRAFT* — the elder who kept choosing the blade and the hammer over the word *becomes*, at the Reckoning, a maker/fighter. The asymmetry is the design goal, not a loophole: the one tender act couldn't launder the drift; to avoid tension you must actually *stay* HEART.

---

## Rigidity (curve, threshold scaling, graceful-degrade contract)

Rigidity must make Reckonings **rarer with age** and **bigger when they finally land**, and it must be a **total function defined at every input** including `age=0` and all-zero deeds.

```
rigidity(age, D[6]) =
      RIGIDITY_FLOOR
    + K_AGE  * age_term(age)            # MACRO — age from class_history
    + K_CONS * concentration(D)         # MICRO — how single-axis your life is

THRESHOLD = BASE_THRESHOLD + rigidity * RIGIDITY_SLOPE
```

- **`concentration(D)`** = an integer spread of the *enacted* vector (e.g. `max(D) − median(D)`). A focused life resists shifts harder. **Use `D` (enacted), not `B` (claimed)** — basing it on the claim would be gameable via a cheap re-Becoming.
- **Rarity-with-age has two engines under this metric, and that changes the curve from the earlier drafts:**
  1. **Inertia (emergent, free):** because `D̂` is normalized, each deed moves the heading *less* as `ΣD` grows → tension-per-act *falls* with age → acts-to-fire *rises* with age, even with a flat rigidity. This was not true under the unnormalized mean-metric, so TENSION-MATH's `age²` argument is re-derived here: inertia already supplies growth, so **`age_term` defaults to linear, not quadratic.** A quadratic term risks making late-life Reckonings effectively impossible.
  2. **`K_AGE · age_term`:** adds resistance on top of inertia.
- **"Snaps harder"** falls out: discharge magnitude ≈ tension-at-fire ≈ `THRESHOLD`, which grows with age. A Reckoning at 60 is a tide; at 14, a ripple.

**Graceful-degradation contract (decision #2 guardrail, satisfied at the type level).** When the macro layer is light (young age, a single `ClassEntry`), `age_term → 0` and rigidity is carried entirely by `concentration(D) + FLOOR`. Never undefined, never divide-by-zero, always monotonic. Rigidity is **derived, not stored** — the flow's "rigidity +1 on commit" emerges from replay because a `ReckoningEvent` raises a reckoning-count term feeding rigidity. No counter field.

**Young = elastic** is emergent, not special-cased: early `D̂ ≈ B̂` (prior-dominated) → tiny divergences, and `THRESHOLD ≈ BASE_THRESHOLD` is low → the profile reshapes fluidly through ordinary deed accumulation without ever needing a Reckoning. The system grows its own gravity.

---

## Firing the Reckoning (trigger, timing, riding REFLECTIVE, re-center + override)

The Reckoning invents **no new FSM state**. It reuses the consequence→reflective path *exactly* as `hp_zero` does (`effects.py:_enter_reflective`), which already performs the atomic `HUB → REFLECTIVE` transition and bails safely on an illegal one. Routing stays `HUB → REFLECTIVE → HUB`, honoring `_ALLOWED_TRANSITIONS` (no spoke-to-spoke edge).

**Timing — lawful boundary, never mid-beat.** Firing is decided by a derived flag but *surfaced* only at the next **Consolidation boundary** (Stage 9), with **Session-Close as backstop** (`03_session_flow.md:116,176`). A new predicate `reckoning_pending_at_consolidation` is true iff the derived flag is set **and** a Consolidation boundary event is present — so it fires at the lawful boundary, not an arbitrary tick (closes the seam-check "fires on tick vs on-entry" hazard). `one_shot` prevents re-spawn while the beat is live. The threshold is read at the boundary → same input-log replays to the same firing tick → byte-equal.

**Chronicle-seeded entry (required for byte-equality).** Firing is pure-integer deterministic, but the *beat content* (`pick_rule`, `compose_pool`) currently calls `random.Random()` (`reflective/state_machine.py:42,53`; `magnets.py`), which diverges C↔Python. `enter_reflective` must seed the RNG from an **integer-FNV of the tension-crossing line-id**, passed via a `seed_source` arg. This subsumes the open-seam port of `magnets.py` off float RNG (build-list #4): the magnet pool is selected by integer-FNV over a bounded vocabulary, golden-vector gated. **FNV is the *only* place RNG appears, and only for selection — never in the metric.**

**The beat re-centers the profile and overrides the life-stage.** On reflective **COMMIT** (`apply_reckoning_shift` in `effects.py`, append-only — *never sets a stat*):

1. **Shift direction = the high axes of `T`.** Take the top-1/top-2 axes of the tension vector (the drifted-toward cluster).
2. **Macro life-stage override.** A data-driven `axis-cluster → life-stage(class)` table maps the winning `T`-cluster to a `ClassEntry`. Appending it makes it the **most-recent** entry; `stat_preset_for_history` already implements *"most recent class wins"* (`character_sheet.py:131-138`), so the **base re-centers** toward the drifted axes. This is decision #3's override: the life-stage changes because of *how you acted*, not a birthday. The AGE path stays the slow default (`default_class_history`); the Reckoning is the rare, choice-driven, use-evolving override — and it is **zero new mechanism**, just a `ClassEntry` row the existing latest-wins fold already understands.

   ```python
   def class_history_from_chronicle(age, reckoning_events):
       history = default_class_history(age)              # AGE driver (slow template)
       for ev in reckoning_events:                       # RECKONING driver (overrides)
           history.append(ClassEntry(ev.new_stage, levels=1, started_at_age=ev.at_age))
       return history
   ```

3. **The drain is NOT free — it is an explicit event.** Because tension is a per-deed *flow* accumulator (not a stateless snapshot), re-centering `B̂` only changes contributions *after* the Reckoning's log position; tension banked from pre-Reckoning deeds would re-fire immediately. So the `ReckoningEvent` does **both**: (a) re-center the base going forward, and (b) carry an explicit `T → residue` reset *at its own log position*. Re-centering then keeps it drained (future deeds on the now-claimed axes see `D̂ ≈ B̂` → calm); the explicit reset clears the banked amount. Both effects are replayed deterministically.
4. **Harden + re-read:** the reckoning-count term ticks (rigidity +1, persisted as the event itself); the disposition FSM re-reads the new `B̂` (reputation = the world re-reading you).

**The RESIST branch (the no-dead-end failure doorway, `03_session_flow.md:122`).** A `ReckoningEvent{kind:refuse}` partial-drains `T` (leaves a `residue`), hardens rigidity *more* (snaps harder next time), and returns cleanly to HUB. Deferred, never blocked — a loop that transitions state on failure, per the hard law. Refusing is **a way to age, not a wrong answer** (becoming set in your ways is a life).

---

## Tension feeders (deck wiring)

The against-profile flow is the primary feeder. The deck cards add scalar impulses, all integer, all weights in `config/reckoning.json` (data-driven — decision #2):

```
on ScarEvent:                T_total += SCAR_WEIGHT
on CarriedThing{severity}:   T_total += severity * CARRY_WEIGHT      # severity 1..5
on DreadFall:                T_total += DREAD_FALL_WEIGHT
```

These are scalar adds to the total (they represent undirected strain), distinct from the directional per-axis flow. They are *conditional cards*, not guaranteed events — so **a perfectly consistent life simply does not Reckon, and that is intended** (do not claim feeders force an eventual Reckoning). The Dread Tower's *session-transforming fall* (vs a heavier Ember) remains a flagged flow gap from the seam-check; this layer only wires its tension contribution.

All feeders read at the same Consolidation boundary; ordering is by log position → byte-equal.

---

## The honest mirror (the 5 enforcement mechanisms, made concrete)

The sheet is a **mirror of who you are**, not a build to optimize. Enforcement is *architectural* — mostly the shape of the data model — not a runtime policeman. The game is **never the authority on your honesty**; it only reflects. (The moment it judges, it becomes external authority and the player stops caring — the same logic as the verbatim-passthrough rule, turned inward.)

1. **Derive-don't-set.** There is **no `set_stat`, no axis setter anywhere.** The only writes to identity are append-only events: `PillarEvent`, `DeedEvent`, `ReckoningEvent`. A stat-slider is *unrepresentable* — no event type carries an output number. The sheet is always `replay(log)`. The exploit surface does not exist.
2. **Honest adjustment = correcting INPUTS, not outputs.** Re-doing the Becoming (re-enterable from HUB) appends fresh `PillarEvent`s; the latest-wins fold absorbs them. This is the *only* adjustment path, and it is the impulse source (§ tension metric): an adjustment claiming more than your deeds support **immediately spikes tension**; an honest correction (claim moves *toward* deeds) *relieves* it. Same integer rewards honesty and destabilizes inflation.
3. **No hidden edits.** Every adjustment is a visible append-only event on the always-visitable stats page. There is no other channel.
4. **Dishonesty → tension → Reckoning (the deepest, quietest leg).** A "claim" routes through the Becoming's narrative lean → an axis vector; it is scored by the *same* distance metric. Claiming HEART you never earned, atop a deed-history of strikes, is mathematically identical to *acting* against type — it loads `T` and bends you toward a Reckoning you didn't earn and won't enjoy. The game never says "you're lying"; it just *leans*, the way the prologue taught it to. **Keep it quiet** — no "are you sure," no "this won't count." Hollowness teaches; warnings preach.
5. **Reward is the earned beat, not the number.** Real behavior emits a `DeedEvent` → the always-grant axis-growth beat with acknowledgement and write-back (`03_session_flow.md:84`). A bare claim emits *tension*, not a beat — a hollow number with no ack, no write-back, a spring quietly winding. "A number without a beat" is unrepresentable; a raw edit yielding a hollow number literally cannot occur. **Design the silence, not a warning** — the absence of the earned beat is the entire teacher.

**Anti-grind / the uncapped lever.** `deeds.h` per-session caps are RAM-only, reset on the session boundary (`deeds.c:202`) — in-game farming is capped. Add **`DEED_PO_COMPLETE` — uncapped, one-shot-per-PO-id** (same pattern as `DEED_RECIPE_LEARNED`, `deeds.h:43`). **Real-world accomplishment routed through Permanent Objects is the only uncapped path to growth** — you can't farm real life. This makes "in-game goals completed by real-world tasks" mechanically true. *(Cross-repo: `PoEntry` lives in the separate `permanent-objects` repo — build-list #8; `DEED_PO_COMPLETE` must fail-soft to a local axis grant when the PO source is offline.)*

**Restart = abandoning a life, never New Game.** A restart does **not** delete the log; it appends a heavy, visible `AbandonEvent` and forks a new `base_seed` lineage. The new life starts at age 0 / elastic, and **does not inherit `D`** — you throw away the accumulated self. The deterrent is **opportunity cost (losing who you became), not a lockout.** Frame it as a hand coming off a shoulder, not a klaxon: *"This life is real. Beginning again does not unmake it — it sets it down."* **No manufactured sunk-cost, no "are you sure you want to throw away everything," no countdown** — that would be the exact retention dark-pattern the project refuses. The loss is *true* because the record is real (`character_sheet.py:109`, "carry one from each chapter of life"), so the weight needs no guilt word.

---

## Visibility & the stats page

Felt-through-world by default (reputation = the world reading your `B̂` via the disposition FSM), **but a pure stats page is always visitable** ("present felt-first, never hide the math"). It is a **pure read over replay-derived state** — no tick, free inspection (`s` summon):

```
B  / B̂   (pillars + life-stage)     ← asserted self
D  / D̂   (deeds.delta rollup)       ← enacted self
effective = B + D                    ← effective_axis()
T[6]      (per-axis tension)         rigidity   (derived)
threshold = BASE + rigidity·SLOPE
to_reckoning = threshold - Σ T       ← the raw distance, shown
```

**Float is permitted ONLY for presentation** (a bar-fill ratio) — never any value on the truth path (decision #1). The frame is **"the instrument reading itself"** (Elite '84 cockpit readout), not a debug dump: naked integers under an inhabited header, never an engineer-voice sentence like `tension: 47/52`. The numbers are bare; the *frame* is in-world. `deeds.c`'s grep-able `log.txt` lines (`deeds.c:226`) double as the audit trail — every contributing event is inspectable.

---

## Prologue teaching (the by-doing reveal)

The Reckoning currently has **no diegetic teaching** — the largest "evocative name not earned by doing" relative to its weight (`04_flow_seamcheck.md:52-53`). Two beats, both engine-narration class, both now *demonstrable* precisely because tension is deed-vs-**base** (a deeds-mean metric would read ≈0 here and teach nothing):

1. **The against-character nudge (feel tension once, sub-threshold).** After the Becoming establishes a lean (say HEART/quiet-tending), one prologue beat offers a choice clearly *against* it where both options pay (no dead end — both are deeds). Taking the hard-against move is a real `DeedEvent`; the AMBIENT blob strip *visibly tilts* and `to_reckoning` ticks **down by one** as it happens. `BASE_THRESHOLD` guarantees it **cannot fire here** — the player feels the spring wind once, with no consequence. One line lands, the name not yet spoken: *"That wasn't like you. The instrument noticed. It is leaning a little, now, where you leaned."* ("The instrument noticed" = the reality-anchor register — the world half-reads you.)
2. **The one-line by-doing reveal (first real fire).** When tension first crosses threshold, the mechanic self-reveals in context — one line, name earned by arrival: *"All this leaning has a name. This is a Reckoning. Few lives have many."* — then straight into the composed beat. "Few lives have many" does the rarity-framing in four words; that second sentence is the *entire* explanation the player ever gets, and it's enough because they already *felt* it in the prologue. **No "Reckonings occur when…" tutorial sentence ever appears.**

**Also route the prologue's first compose beat (the Cairn-stone) through the *actual* `reflective/magnets.py` compose primitive**, not a stand-in — so the compose/commit grammar is muscle-memory before the first Fall *or* Reckoning needs it under stress (closes the companion seam-check gap). Composing your first line should be a quiet act (placing a stone) so composing your hardest line (a Reckoning) reuses a gesture your hands already trust. **The engine frames before and acknowledges after — it never edits, wraps, or adjectives the player's composed line.** Their words, their weight.

---

## Determinism plan (integer + golden vectors)

Everything on the truth path is integer and golden-vector gated (spec 53):

- **Metric** (`B̂/D̂` normalization, per-axis flow, impulse, feeders, rigidity, threshold, firing): pure integer — deterministic by replay order, **no FNV needed**. The normalization divide is **integer floor in fixed axis order** — the one float-temptation, pinned as **golden-vector #1**.
- **Selection** (Reckoning beat variant, magnet pool, tie-break when two `T`-axes are equal): **integer-FNV over a bounded vocabulary**, seeded from the chronicle line-id — the *only* place RNG appears, and it must be FNV, not `random` (the open seam, build-list #4). Forces the `magnets.py` / `pick_rule` port.
- **Decay** (slow deterministic, per-axis floor 0, at each Consolidation boundary, before the firing check): replayable as a pure function of the input-log epoch ticks (`03_session_flow.md:106`) — no wall-clock. `DECAY` must be *slow* relative to tension-generation, or sustained drift never fires; a one-off slip heals.
- **Float ban — verification step (pre-build and CI):**
  ```
  grep -rEn "random\.(random|Random|uniform)|[0-9]\.[0-9]" core/systems/reckoning/   # → zero on truth path
  ```
- **The discriminating golden vectors** (assert these, or the centerpiece has silently regressed to deeds-vs-deeds):
  1. **Four-case gate** (§ tension metric): cases 1 & 3 → `Σ T` stays 0 *structurally*; cases 2 & 4 → `Σ T` strictly rises. **If case 4 ever returns ≈0, the metric is broken.**
  2. **Normalization** = integer floor, fixed order — byte-equal C↔Python.
  3. **Rarity:** `acts_to_fire(age)` monotonically increasing.
  4. **Drain:** a `ReckoningEvent` at log position *p* leaves `Σ T ≤ residue` immediately after *p* (no instant re-fire).
- **C↔Python twin:** the Python metric (`core/systems/reckoning/metric.py`, new) and the C twin (`sanctum-engage/.../reckoning.{h,c}`, new) are **independent git repos** — neither propagates to the other. The byte-equal contract is enforced *only* by the shared golden-vector corpus; both repos must be re-vectored together or they diverge silently.

**File map**

| Concern | File | Action |
|---|---|---|
| Integer metric (blob/tension/rigidity) — Python | `core/systems/reckoning/metric.py` *(new)* | pure integer, no float; mirrors `reflective/` shape |
| Tunables | `config/reckoning.json` *(new)* | `SCALE, PRIOR_TOTAL, T_AXIS_CAP, K_AGE/age_term, K_CONS, BASE_THRESHOLD, RIGIDITY_SLOPE/FLOOR, DECAY, CLAIM_W, SCAR/CARRY/DREAD weights` |
| Trigger predicate | `consequences/predicates.py` | add `reckoning_pending_at_consolidation` |
| Shift/refuse effects | `consequences/effects.py` | add `apply_reckoning_shift`, `apply_reckoning_refusal` (append-only; never set a stat) |
| Reckoning consequence row | `config/consequences.json` | add `reckoning_identity_shift` (one_shot) |
| Chronicle-seeded entry | `reflective/state_machine.py` + `magnets.py` | FNV-of-line-id seed; integer magnet pool, golden-vector gated |
| Reflective rule for the beat | `config/reflective/rules.json` | add the Reckoning compose rule |
| Macro override fold | `core/systems/character_sheet.py` | `class_history_from_chronicle` layering `ReckoningEvent` on `default_class_history` |
| Uncapped PO deed | `sanctum-engage/.../deeds.{h,c}` | add `DEED_PO_COMPLETE` (uncapped, one-shot-per-id) |
| Integer metric — C twin | `sanctum-engage/.../reckoning.{h,c}` *(new)* | mirrors `deeds.c` replay; host-testable; golden-vectored |
| **Precondition** | `core/systems/character_sheet.py` | **build-list #3 stat-collapse — blocks everything above** |

---

## Open questions for the user

Decided-and-written above (do not need your input): the four-case metric form, read-before-apply, the B-prior init, the explicit drain event, integer normalization, per-axis vector, deeds-vs-base, linear-default age term, `concentration(D)` for rigidity. These are technical calls forced by the constraints.

What genuinely needs *your* judgment:

1. **Rarity target.** How rare is a Reckoning — once per ~N sessions / ~N in-game years? This is a **hard acceptance criterion**, not just tuning: the name's entire weight (and the voice design) rests on it almost never firing. It anchors the constant pass. *(My default suggestion: on the order of a handful per *lifetime*, never per session.)*
2. **Late-life sharpness vs honest generalism.** Under this normalized metric the blob tracks your actual deed distribution and does **not** mechanically flatten with age (TENSION-MATH's §9 flattening was an artifact of the *un*normalized mean-metric — parked, not pasted). But a real choice remains: should old deeds keep defining you forever, or fade? **(a)** accept lifetime `D̂` (the old polymath genuinely generalizes), or **(b)** recency-weight `D̂` over the last N epochs (late-life identity stays sharp, old chapters forgotten). Default (a); (b) is a one-line, replayable upgrade. *Decide before the golden-vector pass.*
3. **Decay rate / residue.** How fast do old betrayals heal, and does a refused Reckoning leave 0 or a standing residue? Sets whether reconciliation is forgiving or grudging.
4. **Does a Reckoning's life-stage override stack or replace?** A second Reckoning later — does its `ClassEntry` simply become the new most-recent (replace), or do prior Reckoning stages persist in `class_history` as carried chapters (stack, feeding `earned_abilities`)? Affects how a long, much-Reckoned life accumulates ability breadth.

*Per workspace §0/§4 (50/50) and `00_decisions_log.md:205`: this is the code-half design material for the Phase-2 engine spec. The matching propose→ratify update to `SHARED_STATE.md`/the dossier spec is a human-ratified commit, drafted when the spec stabilizes — not pinned to memory mid-flight.*