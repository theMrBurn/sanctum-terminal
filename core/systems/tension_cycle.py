"""
core/systems/tension_cycle.py

The Train — render tension/resolution cycle.

A loop that any scenario can trigger AT WILL to manage the relationship
between entity budget, atmosphere, and player experience. Not passive —
the scenario decides when to board the train, and the train drives the
fog/ambient/entity lifecycle until the cycle completes.

The cycle: OPEN → BUILDING → TENSION → TUNNEL → DUMP → REBIRTH → OPEN

Each state is config-as-code: fog range, ambient light, spawn behavior.
Transitions are smooth lerps. The budget (entity_count / max_entities)
informs state, but the scenario can also force transitions via hooks.

Hooks (input/output):
    on_state_change(old, new)  — scenario reacts to transitions
    on_dump()                  — scenario can run cleanup, save, spawn remedy
    on_rebirth()               — scenario can seed new content post-flush
    should_advance(budget)     — scenario can override automatic advancement
    force_state(state_name)    — scenario forces a specific state immediately

Usage:
    cycle = TensionCycle(config=CAVERN_CYCLE)
    cycle.on_state_change = my_handler
    cycle.on_dump = my_flush_handler
    # In tick loop:
    envelope = cycle.tick(dt, entity_count, max_entities)
    # envelope has .fog, .ambient, .state, .budget, .should_dump
"""

import math


# -- Default cycle configs -----------------------------------------------------
# Swap these per scenario for different pacing feels.

CAVERN_CYCLE = {
    # Thresholds calibrated for real entity counts (~11K start, ~19K explored).
    # Budget = entity_count / MAX_ENTITIES (25K).
    # Walking to a new tile adds ~4K entities = ~0.16 budget jump.
    "open": {
        "fog": (8.0, 28.0),
        "ambient": (0.32, 0.28, 0.26),
        "budget_floor": 0.0,
        "budget_ceiling": 0.50,
    },
    "building": {
        "fog": (7.0, 22.0),
        "ambient": (0.24, 0.20, 0.18),
        "budget_floor": 0.50,
        "budget_ceiling": 0.60,
    },
    "tension": {
        "fog": (5.0, 16.0),
        "ambient": (0.16, 0.13, 0.11),
        "budget_floor": 0.60,
        "budget_ceiling": 0.72,
    },
    "tunnel": {
        "fog": (3.0, 10.0),
        "ambient": (0.08, 0.06, 0.05),
        "budget_floor": 0.72,
        "budget_ceiling": 0.82,
    },
    "dump": {
        "fog": (2.0, 5.0),
        "ambient": (0.03, 0.02, 0.02),
        "budget_floor": 0.82,
        "budget_ceiling": 1.0,
        "hold_seconds": 2.5,
    },
    "rebirth": {
        "fog": (5.0, 18.0),
        "ambient": (0.18, 0.15, 0.13),
        "budget_floor": 0.0,
        "budget_ceiling": 0.15,
        "hold_seconds": 4.0,
    },
}

STATE_ORDER = ["open", "building", "tension", "tunnel", "dump", "rebirth"]


class CycleEnvelope:
    """Snapshot of the cycle's current output — what the renderer should apply."""
    __slots__ = ("state", "fog", "ambient", "budget", "should_dump",
                 "lerp_t", "transitioning")

    def __init__(self):
        self.state = "open"
        self.fog = (15.0, 42.0)
        self.ambient = (0.20, 0.16, 0.14)
        self.budget = 0.0
        self.should_dump = False
        self.lerp_t = 1.0           # 0.0 = just entered state, 1.0 = fully settled
        self.transitioning = False


class TensionCycle:
    """The Train. Trigger at will, drives render tension/resolution.

    Scenarios call tick() each frame when the cycle is active.
    When inactive (not boarded), tick() returns a static open envelope.
    """

    def __init__(self, config=None):
        self._config = config or CAVERN_CYCLE
        self._state = "open"
        self._prev_state = "open"
        self._lerp_t = 1.0
        self._lerp_speed = 3.0      # seconds to blend between states — matched to walk pace
        self._hold_timer = 0.0
        self._active = False         # train is boarded
        self._envelope = CycleEnvelope()

        # -- Hooks -- scenario wires these
        self.on_state_change = None  # fn(old_state, new_state)
        self.on_dump = None          # fn() — called once when dump triggers
        self.on_rebirth = None       # fn() — called once when rebirth begins
        self.should_advance = None   # fn(budget) -> bool, override auto-advance

        self._dump_fired = False
        self._rebirth_fired = False

    @property
    def state(self):
        return self._state

    @property
    def active(self):
        return self._active

    @property
    def budget(self):
        return self._envelope.budget

    def board(self):
        """Start the train. Call this to begin the cycle."""
        self._active = True
        self._set_state("open")

    def disembark(self):
        """Stop the train. Returns to static open state."""
        self._active = False
        self._set_state("open")
        self._lerp_t = 1.0

    def force_state(self, state_name):
        """Force a specific state immediately. Scenario override."""
        if state_name in self._config:
            self._set_state(state_name)
            self._lerp_t = 1.0  # skip transition

    def tick(self, dt, entity_count, max_entities):
        """Advance the cycle. Returns CycleEnvelope with current fog/ambient/state.

        Call every frame. When not active, returns static open envelope.
        """
        env = self._envelope
        budget = entity_count / max(1, max_entities)
        env.budget = budget

        if not self._active:
            cfg = self._config["open"]
            env.state = "open"
            env.fog = cfg["fog"]
            env.ambient = cfg["ambient"]
            env.should_dump = False
            env.lerp_t = 1.0
            env.transitioning = False
            return env

        # Check if budget pushes us to next state
        cfg = self._config[self._state]

        # Hold timer — dump/rebirth MUST wait before advancing, regardless of budget
        hold = cfg.get("hold_seconds", 0)
        if hold > 0:
            if self._lerp_t >= 1.0:
                self._hold_timer += dt
            if self._hold_timer < hold:
                # Still holding — don't advance, even if budget says so
                pass
            else:
                idx = STATE_ORDER.index(self._state)
                next_idx = (idx + 1) % len(STATE_ORDER)
                self._set_state(STATE_ORDER[next_idx])
        else:
            # Normal budget-driven advancement
            should = True
            if self.should_advance:
                should = self.should_advance(budget)
            if should and budget > cfg.get("budget_ceiling", 1.0):
                idx = STATE_ORDER.index(self._state)
                next_idx = (idx + 1) % len(STATE_ORDER)
                self._set_state(STATE_ORDER[next_idx])

        # Fire hooks
        if self._state == "dump" and not self._dump_fired:
            self._dump_fired = True
            if self.on_dump:
                self.on_dump()
            env.should_dump = True
        else:
            env.should_dump = False

        if self._state == "rebirth" and not self._rebirth_fired:
            self._rebirth_fired = True
            if self.on_rebirth:
                self.on_rebirth()

        # Lerp toward current state's values
        if self._lerp_t < 1.0:
            self._lerp_t = min(1.0, self._lerp_t + dt / max(0.01, self._lerp_speed))
            env.transitioning = True
        else:
            env.transitioning = False

        target = self._config[self._state]
        prev = self._config[self._prev_state]
        t = self._ease(self._lerp_t)

        # Lerp fog
        env.fog = (
            prev["fog"][0] + (target["fog"][0] - prev["fog"][0]) * t,
            prev["fog"][1] + (target["fog"][1] - prev["fog"][1]) * t,
        )

        # Lerp ambient
        env.ambient = tuple(
            prev["ambient"][i] + (target["ambient"][i] - prev["ambient"][i]) * t
            for i in range(3)
        )

        env.state = self._state
        env.lerp_t = self._lerp_t
        return env

    def _set_state(self, new_state):
        if new_state == self._state:
            return
        old = self._state
        self._prev_state = old
        self._state = new_state
        self._lerp_t = 0.0
        self._hold_timer = 0.0

        # Reset hook guards on state entry
        if new_state != "dump":
            self._dump_fired = False
        if new_state != "rebirth":
            self._rebirth_fired = False

        if self.on_state_change:
            self.on_state_change(old, new_state)

    @staticmethod
    def _ease(t):
        """Smooth ease-in-out for natural transitions."""
        return t * t * (3.0 - 2.0 * t)
