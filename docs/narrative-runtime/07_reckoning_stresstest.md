Verified everything load-bearing. Here is the stress-test.

---

# Adversarial stress-test — THE RECKONING + THE HONEST MIRROR

**Scope read:** `deeds.{h,c}` (sanctum-engage), `character_sheet.py` / `character_classes.py`, `reflective/state_machine.py` + `magnets.py`, `consequences/effects.py` + `predicates.py`, `game_state.py` (sanctum-terminal). Cross-repo hazards involve `permanent-objects` (independent repo).

Findings are graded: **🔴 BLOCKS BUILD** · **🟠 BYTE-EQUAL LEAK** (violates locked decision #1) · **🟡 FRAGILITY** (unpinned-constant risk hidden behind "open question") · **🔵 DESIGN-THESIS** (works as built, but the thesis is narrower than advertised) · **⚪ CROSS-REPO**.

---

## 🔴 BLOCKS BUILD

### B1 — The RESIST doorway is design-fiction; without it the Reckoning is a dead end (hunt f)
The doc's no-dead-end guarantee rests on a `ReckoningEvent{kind:refuse}` branch. **It does not exist in the FSM.** `reflective/state_machine.py` exposes exactly `enter / place_magnet / remove_magnet / commit / exit / pick_rule` — no refuse/abort operation, and `exit()` is called only by effect handlers (`effects.py:155,168`), never by player intent. The hp_zero precedent *requires* a successful `commit` to leave reflective (regen+restore are gated on `reflective_committed_from_hp_zero`). If the Reckoning inherits that shape, a player who wants to refuse the shift **cannot leave** — forced one-way override, which contradicts decision #3 ("rare, *choice-driven*").
**Fix:** wire an explicit player-facing abort that calls `apply_reckoning_refusal` (partial-drain + harden) then `exit()` → HUB. The `(REFLECTIVE, HUB)` edge already exists and is even commented "commit / **abort** back to hub" (`game_state.py:57`) — the transition is legal; the *operation that triggers it on refuse* is missing. Build it or the centerpiece is a trap.

### B2 — Concurrent reflective-entering consequences clobber an in-progress beat (hunt f)
`_enter_reflective` bails on an illegal transition by calling `_sm.exit(world)` (`effects.py:155`). If a Reckoning fires at a Consolidation boundary while the world is *already* `REFLECTIVE` (e.g. an hp_zero beat is live, or the player voluntarily engaged the fridge), `game_state.transition(HUB→REFLECTIVE)` raises `ValueError` → the bail runs `_sm.exit()` → **the in-progress beat's magnet pool, composition, and attempt count are wiped.** The player loses a composition they were mid-way through, and the Reckoning silently fails to enter.
**Fix:** the Reckoning's pending-predicate must check `world.game_state.state != REFLECTIVE` and *defer* (it already has a Session-Close backstop — use it) rather than attempt-and-clobber. Never let one reflective-entering consequence call `_sm.exit()` on a world another one owns. Serialize reflective entry.

---

## 🟠 BYTE-EQUAL LEAKS (decision #1 — the hardest law here)

### L1 — `compose_pool` / `pick_rule` use Mersenne Twister; FNV-seeding does **not** buy C↔Python byte-equality (sharpest leak in the set)
The file-map action "FNV-of-line-id seed" understates the work. `magnets.compose_pool` calls `rng.sample(cfg.thematic, n)` and `pick_rule` calls `rng.choice(...)` — both are CPython's MT19937 plus CPython's *specific* `sample`/`choice` algorithms. **Seeding `random.Random(fnv_int)` still runs MT**, and the C twin will not reproduce CPython's sampling byte-for-byte. The two repos are independent git trees (your own note) with only the golden corpus binding them — so this diverges silently the first time the corpus is regenerated on one side.
**Fix:** on the truth path, replace the selection *primitive*, don't reseed it. Selection = `idx = fnv(line_id, i) % len(pool)` over the `sorted()` vocabulary, reimplementable identically in C. Reserve `random.Random` for pure presentation only. This is the real content of build-list #4 — call it "port the selection algorithm off MT," not "seed the RNG."

### L2 — `concentration(D) = max(D) − median(D)` injects a half-integer (median of 6 axes)
The rigidity input is on the truth path (it scales `THRESHOLD`, which decides firing). `median` of an **even** count (6 axes) is the mean of the two middle values → `(a+b)/2` → non-integer when `a+b` is odd → a float reaches `THRESHOLD`. The doc writes this as a throwaway "e.g.", but instantiated literally it is a decision-#1 violation.
**Fix:** use an integer-safe spread — `max(D) − min(D)`, or `2*median` kept in fixed-point, or `Σ|D[a] − mean_floor|`. Pin it as a golden vector; never let `median/2` touch rigidity.

### L3 — `_regen_world` reseed is non-deterministic on the respawn/truth path (adjacent, but the Reckoning rides this chain)
`effects.py:87` does `_random.randint(0, 2**31-1)` for the default `reseed:"random"`. The next expedition's seed is state-deriving (seed-is-truth), yet it's drawn from an unlogged RNG → not replayable. Pre-existing, but the Reckoning shares the consequence-effects chain, and any beat that triggers a regen inherits the non-determinism.
**Fix (flag to render/consequence owner):** the regen seed must be derived from the chronicle (FNV of the triggering line-id) or appended as an explicit input event, never `randint`. Also: `_enter_reflective` defaults to unseeded `random.Random()` when `seed is None` (`effects.py:135`) — the Reckoning path must **always** pass `seed_source`; add a preflight assert so a forgotten seed fails loud, not silent.

**Verification step for all three:**
```
grep -rEn "random\.(random|Random|uniform|randint|sample|choice)|median|statistics|[0-9]\.[0-9]" \
  core/systems/reckoning/   # → zero on the truth path
```
plus a golden vector asserting C and Python emit byte-identical pool/shift/threshold for a fixed line-id.

---

## 🟡 FRAGILITY — the punt to "open question #1 (rarity)" hides three structural risks, not just a tuning knob

### F1 — Per-axis `T_AXIS_CAP` ceiling vs. rigidity-scaled threshold: elders may be **unable to Reckon from drift** (hunt a, "never")
Total tension is `Σ T[a]`, each axis **clamped at `T_AXIS_CAP`**. Directional drift concentrates into ~1–2 axes, so the *reachable* tension from pure against-profile living is ≈ `1–2 × T_AXIS_CAP` — a hard ceiling. `THRESHOLD = BASE + rigidity·SLOPE` grows with age. **If `THRESHOLD` can exceed ~`2 × T_AXIS_CAP`, an elder can never cross it by drifting** — only the scalar feeders can push over. The Reckoning then fires on deck-luck, not identity, inverting the design intent. The doc never shows a constant regime where "rare but reachable" holds at every age; it punts to open-Q#1, but this is a *structural* relationship, not a dial.
**Fix:** add an acceptance criterion: `THRESHOLD(age_max) < drift_axis_count · T_AXIS_CAP` for the intended drift width, **or** explicitly accept feeder-dominated late game (and then fix F2). Make `acts_to_fire(age)` monotonic *and finite* a golden vector.

### F2 — Feeders fire the Reckoning but cannot **aim** it → directionless elder shift (hunt a + b)
Feeders are written `T_total += WEIGHT` (scalar), but the shift direction reads "top axes of `T[6]`." Two gaps: (a) the firing quantity is **ambiguous** — is the test `Σ T[a]` (per the worked example) or `Σ T[a] + feeders`? Pin it. (b) Given F1, an elder whose per-axis `T` is ~0 crosses *only* via feeders → the shift reads an **all-zero `T[6]`** → FNV tie-break → **re-centers the elder into a random life-stage.** A tide-weight Reckoning that picks your new self by coin-flip is the worst possible failure for the name's gravity.
**Fix:** either feeders deposit *directionally* into `T[a]` (the Scar/Carried-Thing know their axis), or a feeder-triggered fire has a defined fallback (re-center toward `D̂`, or **no class change** — drain only). Never let the shift read a zero vector.

### F3 — "Consistency → `Σ T` = 0 **structurally**" is false under integer-quantized discrete deeds (hunt a)
Discrete capped deeds cannot track a 5:1:1:1:1:1 ratio exactly, so `D̂[a]` wobbles around `B̂[a]` and `contrib` is nonzero even for a perfectly on-profile life. With the per-axis floor-at-0, the accumulator is **noise-floored, not zero** — so cases 1 & 3 of your four-case gate are "≈0 in the continuous idealization," not "0 structurally." (I'm *not* claiming a guaranteed positive ratchet — both `B̂` and `D̂` are floor-divided, so truncation can bias `D̂` either way; the defensible claim is that consistency yields noise, which couples rarity fragilely to the decay rate.)
**Fix:** a **deadband** — treat `|D̂[a] − B̂[a]| ≤ ε` as `contrib = 0`. This kills quantization noise regardless of sign while preserving real-drift detection, and decouples rarity from decay tuning. Add a golden vector: a maximally-consistent 200-deed life keeps `Σ T = 0` *with* the deadband (without it, assert it stays `≤ noise_bound`).

### F4 — `PRIOR_TOTAL` is one knob pulled two opposite ways (hunt a + prologue)
Large `PRIOR_TOTAL` → young-elastic (suppresses early tension, the locked property). But that *same* suppression makes the prologue "feel tension once" beat **numerically invisible** — one against-character deed barely moves a prior-pinned `D̂`, so `to_reckoning` won't visibly tick and the by-doing teaching dies. Calibration coupling, not a fatal flaw: name it so it isn't tuned in isolation.
**Fix:** the prologue nudge likely needs an authored *impulse* (a scripted one-shot `T` bump on the teaching choice) rather than relying on the organic flow at `D≈0`. Tune `PRIOR_TOTAL` for elasticity; teach tension with a scripted beat.

---

## 🔵 DESIGN-THESIS — works as built, but narrower than the prose claims

### D1 — The Reckoning is a class-respec exploit (hunt b — undefended)
The override appends a `ClassEntry`; `stat_preset_for_history` is **most-recent-wins** (`character_sheet.py:131`); presets are **power-differentiated** (monk WIS 16 vs rogue WIS 12). A min-maxer deliberately drifts off-axis to *force* a Reckoning that re-centers into a stronger preset. Crucially, **the "reward is the earned beat not the number" defense does not cover this** — the deeds are real, so the respec'd stats are *earned*, not fabricated. Cheapest for a **young** player (low threshold → fast fire), so early-game respec-via-Reckoning is the live vector.
**Fix is your open-Q#4, so decide it as a guardrail not a flavor call:** either presets are **lateral/thematic, not power-tiered** (no stat to chase), or Reckoning stages **stack** (abilities accrete, base doesn't strictly replace). "Replace + power-tiered presets" is the exploitable combination; pick at most one.

### D2 — Re-claim pre-empts the Reckoning → rigidity rations the involuntary path but not the voluntary dodge (hunt b)
A deliberate player re-Becomes toward their drift every session: the honest-correction impulse is ≈0, standing tension decays, and the weighty Reckoning **never fires for them.** This is *not* "the centerpiece never fires" (most players won't micro-manage their pillars, so it fires for the majority) — the precise finding is: **rigidity rations the involuntary Reckoning but places no cost on the voluntary re-claim that pre-empts it.** So the trigger surface is "persistent self-denial," narrower than the prologue teaches ("act against profile → Reckoning"), and a rigid elder can still costlessly re-author their claim, undercutting "rigidity resists the shift."
**Fix:** if the Reckoning's rarity is load-bearing, gate re-Becoming's *downward/toward-drift* relief by rigidity too (an old self resists re-authoring), or accept the narrower trigger explicitly and align the prologue copy to teach "denial," not "drift."

---

## ⚪ CROSS-REPO

### C1 — Anti-grind reduces to PO-id minting integrity (hunt b)
"You can't farm real life" holds only if `DEED_PO_COMPLETE` (uncapped, one-shot-per-PO-id) is gated by *authentic* PO issuance. `PoEntry` lives in the separate `permanent-objects` repo (independent git tree — no propagation). If PO ids can be minted freely there, the uncapped lever farms PO rows, not life. And per the user-sovereignty rule, `permanent-objects` deliberately does **not** validate/auto-correct user input — so there's a real tension between "don't police the user's vocabulary" and "PO completion must be costly to mint."
**Fix (contract, not code-in-this-repo):** define the cross-repo contract for what makes a PO-id eligible to mint a deed (e.g. tied to a real calendar/almanac event with a past timestamp), and have `DEED_PO_COMPLETE` **fail-soft to a capped local axis grant** when the PO source is offline — never grant uncapped growth from an unverifiable source.

### C2 — Restart "marked" is false for a serial restarter (hunt e)
Abandon-to-dodge-a-Reckoning is *dominated* (abandoning forfeits all of `D`; the Reckoning merely re-centers you toward who you already are — strictly cheaper to *take* it), so that vector is weak — leave it. The real gap: if `AbandonEvent` lives in the *old* lineage's log and the new `base_seed` lineage starts clean, **a serial restarter looks pristine on every new life.** "Heavy/marked/rare" is then narrative vibes with no mechanical trace. This is *not* an argument for a sunk-cost dark-pattern (the project rightly refuses that) — it's that the mark must be *true*.
**Fix:** carry an **abandonment count** forward as a visible meta-mark on the new lineage (a quiet line on the stats page: "lives set down: 2"). Respects the anti-dark-pattern value (no klaxon, no countdown) while making "this is real" structurally true.

---

## Graceful-degradation verdict (hunt c)
**Rigidity degrades cleanly** — `age_term→0`, `concentration(D)+FLOOR` carries it, total function at `age=0`/`D=0`, no div-by-zero. Green at the type level, *as the doc claims*. **But the override fold degrades badly:** when the macro `cluster→life-stage` table is light ("structural-now/tuned-later"), an unmapped `T`-cluster appends a `ClassEntry` whose name isn't in `CLASSES`, and `stat_preset_for_history` **silently falls back to `rogue`** (`character_sheet.py:131-138`: `cls if cls is not None else CLASSES["rogue"]`). So a Reckoning that promises to re-center you toward your drifted axes instead **silently resets you to rogue.** The decision-#2 "degrades gracefully when macro is light" guarantee fails precisely on the layer that *needs* the macro table.
**Fix:** the 6-cluster→life-stage table must be **total before the Reckoning ships** (not tuned-later), **or** the override fails *closed* — drain `T` and re-center `B̂` toward `D̂` with **no class change** when the cluster is unmapped. Never silent-fallback to rogue.

---

## Genuine green-lights (the parts that survive the assault)
- **Deeds-vs-base, and the case-4 discriminator.** The core insight is sound: a deeds-vs-mean metric is provably blind to a flat-claim/single-axis life (case 4 → all terms 0), and the direction-distance form catches it. This is the load-bearing idea and it holds. Keep the four-case table as the metric's acceptance test.
- **`no set_stat` makes a stat-slider *unrepresentable*.** Verified: `CharacterSheet` is generated from `class_history` + presets; there is no axis setter anywhere; the sheet is `replay(log)`. The "no hidden edit" enforcement is architectural, not policed — strongest leg of the Honest Mirror.
- **Riding the existing REFLECTIVE FSM instead of inventing a state.** `_enter_reflective` + the `_ALLOWED_TRANSITIONS` guard already exist; the Reckoning adds no new game_state. Correct reuse (modulo B1/B2, which are about *operations on* that FSM, not the choice to reuse it).
- **The B-prior cold-start init.** Born-as-your-claim, sculpted-by-deeds is principled, not a patch — it makes young-elastic emergent and gives inertia for free as `ΣD` grows. Right direction.
- **The explicit drain event.** Correctly recognizing that a per-deed *flow* accumulator would instantly re-fire unless the `ReckoningEvent` carries a `T→residue` reset *at its own log position* — and that re-centering `B̂` only governs *future* contributions — is exactly right and replay-safe. This is a green, not a flaw; the golden vector "no instant re-fire after position *p*" should lock it.

---

## One contract note
Per workspace §4 (50/50) this is the code-half design material; the matching propose→ratify entry to `SHARED_STATE.md` / the Phase-2 spec is a **human-ratified commit** drafted when the metric/constants stabilize — not something to pin mid-flight. The build order is also a hard chain: **stat-collapse (build-list #3) blocks everything** — `B` is today's `dex/wis/int_/cha/str_/con` (`character_sheet.py`) and `D` is `BODY/CRAFT/SIGHT/MIND/HEART/WILL` (`deeds.h:25-30`); they are incommensurable, so the metric cannot be built until both share the 6-axis space. The Reckoning sits strictly downstream of that collapse.

**First verification to run before any build:** the float/MT grep above over `core/systems/reckoning/`, plus the C↔Python golden-vector for pool/shift/threshold on a fixed line-id — because L1 (MT non-portability) and L2 (median) will pass a Python-only self-test and still diverge on the Flipper twin.