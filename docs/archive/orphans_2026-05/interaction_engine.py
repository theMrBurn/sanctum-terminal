"""
core/systems/interaction_engine.py

InteractionEngine -- object lifecycle in the world.

Every interactable object passes through these states:
    DORMANT    -- exists, not near camera, world ignores it
    DETECTABLE -- within detection radius (future: sensor ability range)
    REACHABLE  -- within interaction radius, player can act on it
    HELD       -- lifted, parented to camera
    STOWED     -- in inventory, hidden from world

The engine owns state. Systems (PickupSystem, etc.) own behaviour.
State transitions fire on_state_change so layer_fx can respond
(glow, label, pulse) without the engine knowing about rendering.

PickupSystem is one handler the engine delegates to.
visible_when flag system slots in via register() metadata.
SignalRouter will wire this on boot when built.
"""

from __future__ import annotations

from enum import Enum, auto
from typing import Callable, Dict, Optional


# -- Constants -----------------------------------------------------------------

REACHABLE_RADIUS  = 1.8   # metres -- match pickup_system.PICKUP_RADIUS
DETECTABLE_RADIUS = 8.0   # metres -- future: sensor/sonar abilities extend this


# -- State ---------------------------------------------------------------------

class InteractionState(Enum):
    DORMANT     = auto()   # out of range or hidden
    DETECTABLE  = auto()   # in sensor range, not yet reachable
    REACHABLE   = auto()   # player can act now
    HELD        = auto()   # lifted, parented to camera
    STOWED      = auto()   # in inventory


# -- Record --------------------------------------------------------------------

class _Record:
    """Internal record for one registered node."""

    def __init__(self, node, interaction_type: str, obj: dict):
        self.node             = node
        self.interaction_type = interaction_type
        self.obj              = obj
        self.state            = InteractionState.DORMANT


# -- InteractionEngine ---------------------------------------------------------

class InteractionEngine:
    """
    Owns interaction state for all registered world objects.

    Parameters
    ----------
    camera          : Panda3D NodePath
    render          : Panda3D NodePath (scene root)
    on_state_change : Callable[[node, InteractionState], None]
                      Fired on every state transition.
                      layer_fx subscribes here for glow/label/pulse.
    reachable_radius  : float  -- override from manifest if needed
    detectable_radius : float  -- override from manifest if needed
    """

    def __init__(
        self,
        camera,
        render,
        on_state_change: Optional[Callable] = None,
        reachable_radius:  float = REACHABLE_RADIUS,
        detectable_radius: float = DETECTABLE_RADIUS,
    ):
        self._camera            = camera
        self._render            = render
        self._on_state_change   = on_state_change or (lambda node, state: None)
        self._reachable_radius  = reachable_radius
        self._detectable_radius = detectable_radius
        self._records: Dict[int, _Record] = {}   # id(node) -> _Record

    # -- Registration ----------------------------------------------------------

    def register(self, node, interaction_type: str, obj: dict) -> None:
        """
        Register a world node for interaction tracking.
        interaction_type: "pickup" | "activate" | "harvest" | "inspect" | ...
        obj: the object dict ({id, name, weight, ...})
        """
        self._records[id(node)] = _Record(node, interaction_type, obj)

    def unregister(self, node) -> None:
        """Remove a node from tracking. Safe to call if not registered."""
        self._records.pop(id(node), None)

    def get_state(self, node) -> Optional[InteractionState]:
        """Current interaction state for node, or None if not registered."""
        rec = self._records.get(id(node))
        return rec.state if rec else None

    # -- Tick ------------------------------------------------------------------

    def tick(self) -> None:
        """
        Update interaction states for all registered nodes.
        Call every frame from taskMgr or game_loop.
        Fires on_state_change for every transition.
        """
        cam_pos = self._camera.getPos(self._render)

        for rec in self._records.values():
            node = rec.node

            # Hidden nodes are always DORMANT
            if node.isHidden():
                self._transition(rec, InteractionState.DORMANT)
                continue

            p    = node.getPos(self._render)
            dist = ((p.x - cam_pos.x)**2 + (p.y - cam_pos.y)**2) ** 0.5

            if dist <= self._reachable_radius:
                new_state = InteractionState.REACHABLE
            elif dist <= self._detectable_radius:
                new_state = InteractionState.DETECTABLE
            else:
                new_state = InteractionState.DORMANT

            self._transition(rec, new_state)

    def _transition(self, rec: _Record, new_state: InteractionState) -> None:
        if rec.state is not new_state:
            rec.state = new_state
            self._on_state_change(rec.node, new_state)

    # -- Query -----------------------------------------------------------------

    def nearest(self, interaction_type: str) -> Optional[dict]:
        """
        Returns {"obj": dict, "node": NodePath} for the closest REACHABLE
        node of the given interaction_type, or None.
        This is the contract PickupSystem.get_nearest_fn satisfies.
        """
        cam_pos   = self._camera.getPos(self._render)
        best      = None
        best_dist = self._reachable_radius

        for rec in self._records.values():
            if rec.state is not InteractionState.REACHABLE:
                continue
            if rec.interaction_type != interaction_type:
                continue
            p    = rec.node.getPos(self._render)
            dist = ((p.x - cam_pos.x)**2 + (p.y - cam_pos.y)**2) ** 0.5
            if dist < best_dist:
                best      = rec
                best_dist = dist

        return {"obj": best.obj, "node": best.node} if best else None

    def all_reachable(self, interaction_type: str = None) -> list:
        """
        All REACHABLE nodes, optionally filtered by type.
        Useful for HUD and FX systems.
        """
        return [
            {"obj": r.obj, "node": r.node}
            for r in self._records.values()
            if r.state is InteractionState.REACHABLE
            and (interaction_type is None or r.interaction_type == interaction_type)
        ]

    def all_detectable(self, interaction_type: str = None) -> list:
        """
        All DETECTABLE nodes -- in sensor range but not yet reachable.
        Sonar / sensor ability will surface these to the player.
        """
        return [
            {"obj": r.obj, "node": r.node}
            for r in self._records.values()
            if r.state is InteractionState.DETECTABLE
            and (interaction_type is None or r.interaction_type == interaction_type)
        ]
