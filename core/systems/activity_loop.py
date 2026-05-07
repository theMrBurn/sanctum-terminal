"""Activity loop — universal "what is the player doing" substrate.

Every make-brain + every gameplay system emits one of seven activity-class
signals. The loop accumulates them in saturating counters and fires
threshold-crossing rewards via StateEvent. Substrate per the
2026-05-05 hardware-discipline lock — see `feat_make-brain-ping-pong.md`
PR 9 + the SNES-discipline framing in that session's chat.

Old-dev discipline (the rules that shape this module)
-----------------------------------------------------
1. **Counters not logs in hot path.** The runtime currency is `int[7]`,
   saturating at COUNTER_MAX. The full ActivityEvent stream gets
   appended to a telemetry log (vault.activity_log, future PR) but
   that log is **never read for gameplay**. Reading from a log means
   re-iterating it; saturating counters answer in O(1).

2. **Tables not handlers.** REWARD_TABLE is a static tuple of
   `(class, threshold, kind, register)` rows. Edits require brain
   restart. Polled each tick via edge detection — no callbacks, no
   chains, no per-emit dispatch.

3. **Edge detection over event handlers.** Threshold crossings fire by
   comparing prev[c] < threshold ≤ count[c]. The loop owns prev[];
   producers don't know rewards exist.

4. **Single owner of the tick.** Producers call `emit(class, intensity)`.
   The loop owns `tick(dt)`. Producers and consumer are decoupled —
   no callbacks, no mutual dependency.

5. **No allocation in hot path.** `emit()` mutates one int. `tick()`
   walks REWARD_TABLE (fixed length) and one int per class. No lists
   built per call.

6. **Rotating slot-decay.** Each class's counter loses 1 per
   DECAY_PERIOD_SECONDS, but **only one class decays per period** —
   they cycle through the 7 slots. Amortizes work; emergent "preference
   half-life" comes free from the rotation.

7. **Saturating at COUNTER_MAX.** Counters cap at 255 (one byte —
   honoring the actual SNES discipline). Sustained activity in one
   class can't pump that class's count past peers; threshold-fires
   become non-trivially rare and meaningful.

What this module does NOT do
----------------------------
- No tension-cycle reading. TensionCycle wires to PreferenceCounters
  in a later PR.
- No effect beyond StateEvent emission. Stat changes / encounter
  weighting / reward sound design all flow through StateEvent
  consumers, not through the activity loop directly.
- No persistence (yet). Counters reset on brain reboot. A future PR
  can persist a snapshot to vault.activity_state if multi-session
  preference memory becomes load-bearing.

Cross-references
----------------
- `design_state_events`         — reward emission target
- `feedback_factor_of_7`        — the 7-slot invariant
- `feedback_default_to_active_branch` — why this lives on the
  ping_pong feature branch
- `design_creature_engagement`  — informs HUNT class register
  (Cairn-flavored, not D&D combat)
- `design_reflective_loop`      — UNWIND class connection
- `design_lexicon_architecture` — future RITUAL producer (voice_recognized)
- `design_journal_quest_pipeline` — future RITUAL producer (daily care)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.systems.state_events import StateEventBuffer


# ---------------------------------------------------------------------------
# The seven classes — pinned. Ordering matters: it indexes into counters
# and into the slot-decay rotation.
#
# Renaming or reordering these is a real migration; reward table rows index
# by IntEnum value, telemetry log rows store the integer, and any future
# persisted snapshot pickles the index. Treat as opcodes.
# ---------------------------------------------------------------------------

class ActivityClass(IntEnum):
    HUNT   = 0   # track, strike, take                      (Cairn predator)
    MAKE   = 1   # build, craft, refine, place, combine
    SNEAK  = 2   # avoid, evade, observe-unseen
    UNWIND = 3   # sit, reflect, cozy mode, fridge/magnets   (reflective loop)
    SOLVE  = 4   # decode, choose, arrange, dial-finalize
    WANDER = 5   # traverse, find, discover, scan            (frame composer)
    RITUAL = 6   # seal pillar, vow, voice-recognize, daily-care, mark


CLASS_COUNT = len(ActivityClass)   # 7 — pinned by `feedback_factor_of_7`


# ---------------------------------------------------------------------------
# Tunables — all named, all at file top per AGENTS.md hard rule.
# ---------------------------------------------------------------------------

# One byte, honoring SNES discipline. Sustained activity caps; preference
# memory is bounded.
COUNTER_MAX: int = 255

# How often a single class decays by 1. With CLASS_COUNT=7 classes
# rotating through one slot per period, full-sweep = 7 × DECAY_PERIOD_SECONDS.
# At 30s/slot: full sweep 3.5 min, saturated counter drains in ~14.9 hours
# of zero activity in that class — multi-session preference memory horizon.
DECAY_PERIOD_SECONDS: float = 30.0

# Telemetry log capacity in memory. Append-only; older entries drop off
# the head when full. Vault persistence is out of scope for PR 9.
MAX_TELEMETRY_BUFFER: int = 256

# UNWIND producer cadence (PR 10) — `BrainWorld` accumulates dwell-time
# (low-input seconds) and emits one UNWIND tick per slice. Sized so the
# REWARD_TABLE thresholds below correspond to legible session durations:
#   30 emits  × 10s = 300s = 5 minutes  → "recognized"
#   100 emits × 10s = 1000s = ~16.7 min → "deepened"
# Reading the slice + thresholds together is how the rationale stays in
# one place — keep them adjacent if either is tuned.
DWELL_UNWIND_SLICE_SECONDS: float = 10.0


# ---------------------------------------------------------------------------
# Reward table — static. (class, threshold, state-event kind, register)
#
# Polled each tick via edge detection. Rows fire ONCE per crossing — the
# loop tracks prev_count and only fires when prev[c] < threshold ≤ count[c].
#
# PR 9 ships HUNT rows only — that's the one wired producer. Other classes
# get rows as their producers come online (workroom seed_create → MAKE,
# journal-quest daily complete → RITUAL, reflective_loop entry → UNWIND).
# Adding a row = adding a row. No code changes.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RewardRow:
    cls:       ActivityClass
    threshold: int
    kind:      str             # StateEvent.kind
    label:     str             # StateEvent.label (top line, ALL CAPS)
    detail:    str | None      # StateEvent.detail (optional second line)
    register:  str             # StateEvent register; reuses state_events vocab


# Imported as a string to dodge a circular import at module load — the
# state_events module is light, but we still defer the dependency. Real
# emit-time uses the constant from state_events.RITUAL.
_REG_RITUAL = "ritual"


REWARD_TABLE: tuple[RewardRow, ...] = (
    RewardRow(ActivityClass.HUNT,   50,  "hunt_recognized",
              "HUNT — RECOGNIZED",   None, _REG_RITUAL),
    RewardRow(ActivityClass.HUNT,   200, "hunt_deepened",
              "HUNT — DEEPER",       None, _REG_RITUAL),
    RewardRow(ActivityClass.MAKE,   25,  "make_recognized",
              "MAKE — RECOGNIZED",   None, _REG_RITUAL),
    RewardRow(ActivityClass.MAKE,   100, "make_deepened",
              "MAKE — DEEPER",       None, _REG_RITUAL),
    RewardRow(ActivityClass.UNWIND, 30,  "unwind_recognized",
              "UNWIND — RECOGNIZED", None, _REG_RITUAL),
    RewardRow(ActivityClass.UNWIND, 100, "unwind_deepened",
              "UNWIND — DEEPER",     None, _REG_RITUAL),
    RewardRow(ActivityClass.RITUAL, 30,  "ritual_recognized",
              "RITUAL — RECOGNIZED", None, _REG_RITUAL),
    RewardRow(ActivityClass.RITUAL, 100, "ritual_deepened",
              "RITUAL — DEEPER",     None, _REG_RITUAL),
    RewardRow(ActivityClass.WANDER, 25,  "wander_recognized",
              "WANDER — RECOGNIZED", None, _REG_RITUAL),
    RewardRow(ActivityClass.WANDER, 100, "wander_deepened",
              "WANDER — DEEPER",     None, _REG_RITUAL),
    RewardRow(ActivityClass.SOLVE,  20,  "solve_recognized",
              "SOLVE — RECOGNIZED",  None, _REG_RITUAL),
    RewardRow(ActivityClass.SOLVE,  80,  "solve_deepened",
              "SOLVE — DEEPER",      None, _REG_RITUAL),
)


# ---------------------------------------------------------------------------
# PreferenceCounters — saturating int[7] with rotating slot-decay.
#
# Producers call .emit(class, intensity). The loop calls .tick(dt). Reads
# (e.g., for telemetry summary) call .snapshot(). All operations are O(1)
# in CLASS_COUNT (which is 7 — effectively constant).
# ---------------------------------------------------------------------------

@dataclass
class PreferenceCounters:
    counts:        list[int] = field(
        default_factory=lambda: [0] * CLASS_COUNT
    )
    # Time accumulator; when it crosses DECAY_PERIOD_SECONDS, the next
    # slot in rotation gets decremented. Resets after each decay.
    _decay_accum:  float = 0.0
    _decay_slot:   int = 0     # which class to decay next on a fired period

    def emit(self, cls: ActivityClass, intensity: int = 1) -> None:
        """Add intensity to a class counter, saturating at COUNTER_MAX.

        intensity should be a small positive int (1 for routine actions,
        3 for boss/heavy moments). Negative intensities are clamped to 0.
        """
        if intensity <= 0:
            return
        idx = int(cls)
        new_value = self.counts[idx] + intensity
        if new_value > COUNTER_MAX:
            new_value = COUNTER_MAX
        self.counts[idx] = new_value

    def tick(self, dt: float) -> None:
        """Advance the decay accumulator. When a full period has passed,
        decrement the current slot (if > 0) and rotate to the next.

        Multiple periods per tick are handled correctly — drains the
        accumulator in a loop. In practice dt is small, so this is O(1)
        per call almost always.
        """
        if dt <= 0.0:
            return
        self._decay_accum += dt
        while self._decay_accum >= DECAY_PERIOD_SECONDS:
            self._decay_accum -= DECAY_PERIOD_SECONDS
            if self.counts[self._decay_slot] > 0:
                self.counts[self._decay_slot] -= 1
            self._decay_slot = (self._decay_slot + 1) % CLASS_COUNT

    def snapshot(self) -> dict[str, int]:
        """Per-class count map for telemetry / console readout. O(7)."""
        return {cls.name: self.counts[int(cls)] for cls in ActivityClass}


# ---------------------------------------------------------------------------
# ActivityLoop — owns the tick. Polls PreferenceCounters against
# REWARD_TABLE; fires StateEvents on threshold crossings.
# ---------------------------------------------------------------------------

@dataclass
class ActivityLoop:
    prefs:        PreferenceCounters
    state_events: "StateEventBuffer"

    # Cached previous-tick counts for edge detection. Same shape as
    # prefs.counts. Updated at the END of each tick — a rising-edge
    # threshold crossing fires once per crossing.
    _prev_counts: list[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self._prev_counts:
            self._prev_counts = list(self.prefs.counts)

    def tick(self, dt: float) -> list[str]:
        """Advance the loop one tick.

        1. Decay slot rotation (delegated to prefs.tick).
        2. Edge-detect each REWARD_TABLE row.
        3. Fire StateEvents for crossings.
        4. Update _prev_counts.

        Returns the list of fired reward kinds (for tests + telemetry).
        """
        self.prefs.tick(dt)
        fired: list[str] = []
        counts = self.prefs.counts
        for row in REWARD_TABLE:
            idx = int(row.cls)
            prev = self._prev_counts[idx]
            curr = counts[idx]
            if prev < row.threshold <= curr:
                self.state_events.emit(
                    row.kind, row.label, row.detail, row.register,
                )
                fired.append(row.kind)
        # Slot-by-slot copy avoids list realloc; CLASS_COUNT is 7.
        for i in range(CLASS_COUNT):
            self._prev_counts[i] = counts[i]
        return fired


# ---------------------------------------------------------------------------
# Module-level singletons — producers call `emit_activity()` directly,
# no need to hand-thread a prefs reference through every handler. This
# is the old-dev convention: one fixed RAM location for the registry.
#
# BrainWorld.__init__ calls `install(state_events, vault=...)` to
# construct the pair + bind telemetry. Tests use `_reset_for_tests()`
# between cases.
# ---------------------------------------------------------------------------

_PREFS: PreferenceCounters | None = None
_LOOP:  ActivityLoop | None = None
_VAULT: object | None = None     # optional vault for activity_log telemetry


def install(
    state_events: "StateEventBuffer",
    vault: object | None = None,
) -> tuple[PreferenceCounters, ActivityLoop]:
    """Construct the singleton counters + loop. Idempotent — repeat
    calls return the same instances (so brain restarts in long-running
    test processes don't leak state).

    Pass `vault` to enable activity_log telemetry append on every emit
    (per `.claude/audit_2026-05-06.md` A6). Telemetry is fail-safe — if
    the append raises, the emit still succeeds.
    """
    global _PREFS, _LOOP, _VAULT
    if _PREFS is None or _LOOP is None:
        _PREFS = PreferenceCounters()
        _LOOP = ActivityLoop(_PREFS, state_events)
    if vault is not None:
        _VAULT = vault
    return _PREFS, _LOOP


def emit_activity(
    cls: ActivityClass,
    intensity: int = 1,
    primitive: str = "emit",
    source_brain: str = "brain",
    payload: dict | None = None,
) -> None:
    """Producer-facing one-liner. Silent no-op when not installed
    (tests, partial boots, biomes without an activity-loop wiring).

    Bumps the saturating counter (gameplay-load-bearing) AND appends a
    row to vault.activity_log if an activity-log-enabled vault is
    installed (telemetry-only, never read for gameplay).
    """
    if _PREFS is None:
        return
    _PREFS.emit(cls, intensity)
    if _VAULT is not None:
        try:
            _VAULT.activity_log_append(
                int(cls), primitive, intensity, source_brain, payload,
            )
        except Exception:                # noqa: BLE001 — telemetry is non-load-bearing
            pass


def tick(dt: float) -> list[str]:
    """Brain-server-facing one-liner. Returns fired reward kinds, or
    empty list when not installed."""
    if _LOOP is None:
        return []
    return _LOOP.tick(dt)


def summary() -> dict:
    """Console / debug readout. Per-class counts + pending threshold
    distance for each REWARD_TABLE row."""
    if _PREFS is None:
        return {"installed": False}
    counts = _PREFS.counts
    rewards: list[dict] = []
    for row in REWARD_TABLE:
        idx = int(row.cls)
        rewards.append({
            "class":     row.cls.name,
            "threshold": row.threshold,
            "current":   counts[idx],
            "remaining": max(0, row.threshold - counts[idx]),
            "fired":     counts[idx] >= row.threshold,
            "kind":      row.kind,
        })
    return {
        "installed": True,
        "counts":    _PREFS.snapshot(),
        "rewards":   rewards,
    }


def _reset_for_tests() -> None:
    """Test-only: clear singletons so each test starts clean."""
    global _PREFS, _LOOP, _VAULT
    _PREFS = None
    _LOOP = None
    _VAULT = None
