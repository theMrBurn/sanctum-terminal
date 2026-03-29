"""
core/systems/pickup_system.py

Two-press [E] pickup: Hold -> Stow
The Philosopher Monk lifts a book.
The world notices what you choose to hold.

State machine:
    IDLE --[E]+nearest--> HELD --[E]--> STOWING --tween done--> IDLE
                           |
                          [G] drop --> IDLE  (world_pos restored, no punishment)

Wiring (in CreationLab / main app):
    self.inventory = Inventory()
    self.pickup    = PickupSystem(
        camera         = self.cam,
        inventory      = self.inventory,
        get_nearest_fn = self._nearest_pickupable,
    )
    self.accept("e", self.pickup.on_e_pressed)
    self.accept("g", self.pickup.on_drop_pressed)
    self.taskMgr.add(
        lambda t: (self.pickup.update(globalClock.getDt()), t.cont)[1], "Pickup"
    )

get_nearest_fn must return {"obj": dict, "node": NodePath} or None.
obj must have: id, name, weight (optional, defaults to 0.5), category.
"""

from __future__ import annotations

import math
from enum import Enum, auto
from typing import Callable, Optional


# -- Constants -----------------------------------------------------------------

HOLD_OFFSET      = (0.0, 2.2, -0.35)   # camera-relative: ahead, slightly low
HOLD_BOB_FREQ    = 1.4                  # Hz
HOLD_BOB_AMP     = 0.04                 # metres
HOLD_LERP_SPEED  = 12.0                 # position smoothing (units/s)
STOW_DURATION    = 0.28                 # seconds for fly-to-slot tween
PICKUP_RADIUS    = 1.8                  # metres -- match proximity label threshold


# -- State ---------------------------------------------------------------------

class PickupState(Enum):
    IDLE    = auto()
    HELD    = auto()
    STOWING = auto()


# -- Tween ---------------------------------------------------------------------

class _Tween:
    """Smoothstep position tween between two world points."""

    def __init__(self, start: tuple, end: tuple, duration: float):
        self.start    = start
        self.end      = end
        self.duration = duration
        self.elapsed  = 0.0
        self.done     = False

    def tick(self, dt: float) -> tuple:
        self.elapsed = min(self.elapsed + dt, self.duration)
        t = self.elapsed / self.duration
        t = t * t * (3.0 - 2.0 * t)
        if self.elapsed >= self.duration:
            self.done = True
        return tuple(
            self.start[i] + (self.end[i] - self.start[i]) * t
            for i in range(3)
        )


# -- PickupSystem --------------------------------------------------------------

class PickupSystem:
    """
    Manages two-phase [E] pickup for world objects.

    Parameters
    ----------
    camera          : Panda3D NodePath
    inventory       : Inventory instance
    get_nearest_fn  : Callable[[], Optional[dict]]
                      Returns {"obj": dict, "node": NodePath} or None.
    on_held_fn      : Callable[[dict], None]   -- fired when lift completes
    on_stowed_fn    : Callable[[dict], None]   -- fired when stow completes
    on_dropped_fn   : Callable[[dict], None]   -- fired on drop
    on_fail_fn      : Callable[[str], None]    -- fired with reason string
    """

    def __init__(
        self,
        camera,
        inventory,
        get_nearest_fn:  Callable,
        on_held_fn:      Optional[Callable] = None,
        on_stowed_fn:    Optional[Callable] = None,
        on_dropped_fn:   Optional[Callable] = None,
        on_fail_fn:      Optional[Callable] = None,
    ):
        self._camera      = camera
        self._inventory   = inventory
        self._get_nearest = get_nearest_fn
        self._on_held     = on_held_fn    or (lambda obj: None)
        self._on_stowed   = on_stowed_fn  or (lambda obj: None)
        self._on_dropped  = on_dropped_fn or (lambda obj: None)
        self._on_fail     = on_fail_fn    or (lambda reason: None)

        self.state:       PickupState     = PickupState.IDLE
        self._held_obj:   Optional[dict]  = None
        self._held_node:  object          = None
        self._held_world_pos: tuple       = (0.0, 0.0, 0.0)
        self._current_pos: tuple          = HOLD_OFFSET
        self._bob_t:      float           = 0.0
        self._tween:      Optional[_Tween] = None

    # -- Public API ------------------------------------------------------------

    def on_e_pressed(self) -> str:
        if self.state is PickupState.IDLE:
            return self._try_lift()
        if self.state is PickupState.HELD:
            return self._begin_stow()
        return "busy"

    def on_drop_pressed(self) -> str:
        if self.state is PickupState.HELD:
            return self._drop()
        return "nothing_held"

    def update(self, dt: float) -> None:
        if self.state is PickupState.HELD:
            self._update_hold(dt)
        elif self.state is PickupState.STOWING:
            self._update_stow(dt)

    @property
    def held_obj(self) -> Optional[dict]:
        return self._held_obj

    @property
    def is_busy(self) -> bool:
        return self.state is not PickupState.IDLE

    # -- Lift ------------------------------------------------------------------

    def _try_lift(self) -> str:
        nearest = self._get_nearest()
        if nearest is None:
            self._on_fail("nothing_nearby")
            return "nothing_nearby"

        obj  = nearest["obj"]
        node = nearest["node"]
        w    = obj.get("weight", 0.5)

        if not self._inventory.has_space(weight=w):
            self._on_fail("inventory_full")
            return "inventory_full"

        self._held_world_pos = self._get_world_pos(node)
        node.reparentTo(self._camera)
        node.setPos(*HOLD_OFFSET)

        self._held_obj    = obj
        self._held_node   = node
        self._bob_t       = 0.0
        self._current_pos = HOLD_OFFSET
        self.state        = PickupState.HELD
        self._on_held(obj)
        return "lifted"

    # -- Hold update -----------------------------------------------------------

    def _update_hold(self, dt: float) -> None:
        self._bob_t += dt
        bob_z  = math.sin(self._bob_t * HOLD_BOB_FREQ * 2.0 * math.pi) * HOLD_BOB_AMP
        target = (HOLD_OFFSET[0], HOLD_OFFSET[1], HOLD_OFFSET[2] + bob_z)
        f      = min(HOLD_LERP_SPEED * dt, 1.0)
        cx, cy, cz = self._current_pos
        tx, ty, tz = target
        self._current_pos = (cx + (tx-cx)*f, cy + (ty-cy)*f, cz + (tz-cz)*f)
        self._held_node.setPos(*self._current_pos)

    # -- Stow ------------------------------------------------------------------

    def _begin_stow(self) -> str:
        w = self._held_obj.get("weight", 0.5)
        if not self._inventory.has_space(weight=w):
            self._on_fail("inventory_full")
            return "inventory_full"

        start = self._get_world_pos(self._held_node)
        end   = self._hud_anchor()
        self._tween = _Tween(start=start, end=end, duration=STOW_DURATION)
        self.state  = PickupState.STOWING
        return "stowing"

    def _update_stow(self, dt: float) -> None:
        pos      = self._tween.tick(dt)
        progress = self._tween.elapsed / self._tween.duration
        scale    = max(1.0 - progress * 0.85, 0.05)
        self._held_node.setPos(self._camera, *pos)
        self._held_node.setScale(scale)
        if self._tween.done:
            self._finish_stow()

    def _finish_stow(self) -> None:
        obj = self._held_obj
        self._inventory.pickup(obj)
        self._held_node.hide()
        self._held_node.setScale(1.0)
        self._tween     = None
        self._held_obj  = None
        self._held_node = None
        self.state      = PickupState.IDLE
        self._on_stowed(obj)

    # -- Drop ------------------------------------------------------------------

    def _drop(self) -> str:
        render = self._camera.getParent()
        self._held_node.reparentTo(render)
        self._held_node.setPos(render, *self._held_world_pos)
        self._held_node.setScale(1.0)
        obj = self._held_obj
        self._held_obj  = None
        self._held_node = None
        self.state      = PickupState.IDLE
        self._on_dropped(obj)
        return "dropped"

    # -- Helpers ---------------------------------------------------------------

    def _get_world_pos(self, node) -> tuple:
        """World-space position of node relative to render."""
        render = self._camera.getParent()
        p = node.getPos(render)
        return (p.x, p.y, p.z)

    def _hud_anchor(self) -> tuple:
        """
        World-space point the stow tween aims at.
        Override or monkey-patch after HUD cards are laid out:
            ps._hud_anchor = lambda: real_slot_world_pos
        """
        return (0.0, 10.0, -5.5)
