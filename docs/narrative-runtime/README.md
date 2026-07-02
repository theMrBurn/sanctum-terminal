# Sanctum Narrative-Mechanics Runtime — design dossier

> **The pivot:** deprecate the Sanctum Terminal *game's* visual velocity and rebuild it as a
> **story-agnostic narrative-mechanics runtime** — fully playable in **text alone**, with visuals
> added later as illustrations of beats (Atlus / Wildermyth style). The Flipper RPG
> (`sanctum-engage/flipper/sanctum_rpg/`) is the proven baseline; we **reuse-and-simplify** the
> existing logic across both codebases rather than rewrite. The rules engine is the product; text
> is the cheapest window onto it.

This folder is the **design dossier** that precedes the engine spec. It is design/research material,
not yet a ratified spec (that is the next step — propose→ratify per the workspace protocol).

## Documents
| File | What it is |
|---|---|
| [`00_decisions_log.md`](00_decisions_log.md) | The full working log — every decision and its rationale, in order. |
| [`01_engine_audit.md`](01_engine_audit.md) | Audit of both codebases: keep / simplify / deprecate, the state-loop model, gaps. |
| [`02_goal_shapes_and_cards.md`](02_goal_shapes_and_cards.md) | The 9 goal-shapes + 8 modifier-cards (tabletop-derived), fit-checked against the design law. |
| [`03_session_flow.md`](03_session_flow.md) | The canonical 12-stage end-to-end session flow. |
| [`04_flow_seamcheck.md`](04_flow_seamcheck.md) | Adversarial seam-check of the flow (grounded in real code, with line numbers). |
| [`05_spec_engine.md`](05_spec_engine.md) | **The engine spec (DRAFT)** — I/O contract, data model, FSM, accumulator, the Reckoning, trade/ledger, session-open, determinism, build order. |
| [`06_reckoning_formalization.md`](06_reckoning_formalization.md) | The Reckoning + honest-mirror math (blob, integer tension metric, age² rigidity). |
| [`07_reckoning_stresstest.md`](07_reckoning_stresstest.md) | Adversarial stress-test of the Reckoning math (build-blockers, byte-equal leaks, exploits). |

## The hard design law
**State changes, never binary if/then. No dead ends — only loops that close and transition state,
on _both_ success and failure. Failure is a doorway, never GAME OVER.**

## Locked decisions
- **World model:** beat-graph primary, over a procgen spatial seed-world kept as *data* (coherence +
  reachability), never required to render.
- **Resolution:** one comprehension **accumulator** (fight / understand / parley / study / flee all
  pay; flee partial). Damage is one axis among several.
- **Reward:** always-grant intrinsic axis-growth + optional loot. **No payless beat.**
- **Axes:** BODY / CRAFT / SIGHT / MIND / HEART / WILL (deeds nudge them by *how* you act).
- **Truth:** seed + append-only input-log, state derived by replay. Cross-session marks are overlay
  events, never seed mutation, never per-chunk storage.
- **Engine:** one consequence beat-engine (`trigger → resolution → effects`) + a deeds event-log
  beneath it; a **4-state FSM** (`CHARACTER_CREATION / HUB / REFLECTIVE / ENGAGEMENT`). Goal-shapes,
  cards, the prologue, and the Reckoning are all **data** on that spine.
- **"One deed, three readers":** every committed action emits one deed, read by axis-growth, the
  active goal-shape accumulator, and identity tension — three tiers of one accumulator primitive.
- **Determinism:** no runtime LLM; integer-FNV on the byte-equal C↔Python path.
- **Verbatim passthrough:** user-authored content (notes, dates, reminders, alerts, PO entries) is
  stored and *used* as-is and, when surfaced back to the user, rendered **verbatim** — never
  interpreted, summarized, or rephrased. Engine-generated narration is a *separate* text class with
  no such constraint. (Workspace-protocol §2 user-sovereignty, applied to runtime output.)

## The experience (Phase 1, complete)
The pull is a **goal**, and the goal's *shape* is the variable. Sessions open with a **series of
questions** (sourced from the user's **Permanent Objects**). Consequence layer = **the Reckoning**
(a rare, rarity-weighted identity shift; felt-through-world but always inspectable on a pure stats
page). Onboarding = a diegetic **prologue** that teaches each name by *doing* it (place one stone →
"the Cairn"). All assembled into the 12-stage flow in `03_session_flow.md`.

## Build list (from the seam-check → feeds the spec)
1. **Beat-layer reachability** — port `carve_egress` to the beat graph (prove every seeded beat
   reachable, or carve a connecting beat) **before** any chaining goal-shape.
2. **Persistence/overlay port** — seed+input-log replay + delta-overlay; precondition for *every*
   cross-session card.
3. **One stat sheet** — collapse Terminal's two stat systems into the single 6-axis sheet.
4. **Determinism gates** — port the float-RNG sites (`rewards.py`, `reflective/magnets.py`, the
   `worth_knowing > 0.45` resonance gate, the resolver injectable) to integer-FNV behind golden vectors.
5. **Engine gaps** — wire abilities into the resolver; implement or cut `DEFEND`; build the bounded
   theme-vocabulary bridge.
6. **Prologue gaps** — teach the reflective-compose grammar before The Fall needs it; give the
   Reckoning a one-line by-doing reveal.
7. **Tension tuning** — the against-profile distance metric over the 6-axis blob + the rigidity
   curve; needs a golden-vector pass against real PO data.
8. **Cross-repo PO source contract** — `PoEntry` lives in `permanent-objects` (separate repo);
   define and version the boundary.

## Also locked (this session)
- **The Reckoning** (identity/tension) is formalized (`06`) and stress-tested (`07`): per-axis integer
  tension = the deed's projection onto your mean-centered self; `age²` rigidity → **7 Reckonings per
  lifetime**; **stack, not replace**; refusal has teeth (residue + a Scar); lifetime `D̂`.
- **The honest mirror**: no `set_stat` exists (a stat-slider is unrepresentable); `DEED_PO_COMPLETE`
  is the *only* uncapped growth ("you can't farm real life"); restart = abandoning a life.
- **Trade / economy is CORE, not optional**: the seed is the data *and* the currency — an addressable
  seed-ledger where a trade transfers an *address* that expands byte-identically on a peer. **EXCHANGE
  = engagement + ledger**; everything offerable, skill-gated, honest-by-tension.
- **Session-open = a daily baseline / drift-diagnostic check** ("Voight-Kampff") + a passive
  presentation-side clock.

## Status
Phase 1 (experience & flow) complete. Phase 2 (the engine spec, [`05`](05_spec_engine.md)) is **drafted**
— §5/§3.7/§2.1 filled, build order sequenced, four Reckoning tuning calls settled. **Next:** the
stat-vocab collapse (build #1, blocks everything), then down the build order; and the two deferred
passes still queued — the seed-ledger/trade formalization and the cultural-eccentric voice/name pass
(incl. the "Cairn" unify-or-split).
