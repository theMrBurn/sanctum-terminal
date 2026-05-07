"""Weapons — per-weapon-class handlers for the Strike primitive.

Each module in this package owns ONE weapon_class (melee_blade,
melee_blunt, melee_tether, ranged_thrown, ranged_bow, magic_staff,
magic_wand). Handlers expose `on_use(camera_state) -> Strike` and
register themselves with `strike.register_dispatcher(...)` for the
brain's per-tick resolution.

PR 2 ships ranged_thrown only. Subsequent PRs add the rest in the
order: melee_blade (PR 3), melee_tether (PR 4), magic_staff (PR 5).

Activation: brain calls `weapons.activate_v1_weapons(vault)` at boot
to seed default weapon profiles and register dispatchers.
"""
from __future__ import annotations

from core.systems.weapons import ranged_thrown


def activate_v1_weapons(vault) -> None:
    """Seed V1 weapon profiles into vault.profiles and register the
    per-mode dispatchers with the strike substrate. Idempotent — safe
    to call across brain restarts.

    PR 2 activates ranged_thrown; later PRs add melee_blade, etc.
    """
    ranged_thrown.activate(vault)
