"""Distance-based phosphor falloff for wireframe entities.

Battlezone-style: full intensity within `near`, linear fade to MIN_GLOW
at `far`, never fully dark. Bounds default to `cfg.NEAR_DIST` and
`cfg.FAR_FADE` (4m / 60m), but the brain's `manifest.fog.near` /
`manifest.fog.far` override them per frame so TensionCycle's per-state
fog values drive the player's actual visibility envelope.

Closes the chain that PR 15 (activity_loop → TensionCycle pacing) was
emitting into a vacuum:

    activity_loop dominant class
       → TensionCycle pace_multiplier
       → cycle state transitions (timing)
       → manifest.fog.near / far  (per-state lerped values)
       → THIS MODULE  (consumes each frame)
       → entity render intensity (player feels the cycle)

Per PR 16 — the missing wire.

Falls back to cfg constants when bounds are unset (no manifest received
yet, or biome doesn't run TensionCycle). State is module-level so
existing call sites in main.py keep their argument signature
(intensity is a function of distance only — no plumbing required at
each call).
"""
from __future__ import annotations

from clients.vector_terminal import config as cfg


# Active bounds. None means "fall back to cfg constants."
_near: float | None = None
_far:  float | None = None


def set_bounds(near: float | None, far: float | None) -> None:
    """Update the active fog bounds. Either or both may be None to
    fall back to cfg constants. Defensive cast to float; the brain
    manifest may emit ints, None, or omit the key entirely.

    Sanity: if `near >= far`, ignore the update (broken signal —
    would invert the gradient). Caller's previous bounds (or fallback)
    persist."""
    global _near, _far
    n: float | None = None
    f: float | None = None
    if near is not None:
        try:
            n = float(near)
        except (TypeError, ValueError):
            n = None
    if far is not None:
        try:
            f = float(far)
        except (TypeError, ValueError):
            f = None
    # Reject invalid pairs — keep prior state to avoid jitter.
    if n is not None and f is not None and n >= f:
        return
    _near = n
    _far  = f


def reset() -> None:
    """Forget any dynamic bounds — falls back to cfg constants. Used
    on disconnect / first-frame setup / tests."""
    global _near, _far
    _near = None
    _far  = None


def active_bounds() -> tuple[float, float]:
    """Current effective (near, far). Reads dynamic state if set,
    cfg constants otherwise. Useful for HUD readouts + tests."""
    near = _near if _near is not None else cfg.NEAR_DIST
    far  = _far  if _far  is not None else cfg.FAR_FADE
    return near, far


def intensity(dist: float) -> float:
    """Phosphor falloff intensity at `dist`. Full bright within `near`,
    linear fade to `cfg.MIN_GLOW` at `far`, capped at MIN_GLOW past
    that. Never returns 0 — the wireframe identity keeps a faint glow
    on distant edges.
    """
    near, far = active_bounds()
    if dist <= near:
        return 1.0
    if dist >= far:
        return cfg.MIN_GLOW
    span = max(0.01, far - near)             # guard against degenerate equal bounds
    t = (dist - near) / span
    return max(cfg.MIN_GLOW, 1.0 - t * (1.0 - cfg.MIN_GLOW))
