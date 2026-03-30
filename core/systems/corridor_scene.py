"""
core/systems/corridor_scene.py

CorridorScene -- 8 doors, 1 correct, minute detail as clue.

The correct door has a single detail that differs from the others.
The detail type escalates by tier:
  Tier 1: visual (you can SEE it)
  Tier 2: spatial (you have to THINK about it)
  Tier 3: temporal (you have to WAIT for it)
  Tier 4+: behavioral (the door reads YOU)
"""

from __future__ import annotations

import random


# -- Detail pools by tier ------------------------------------------------------

_TIER_DETAILS = {
    1: {  # VISUAL -- you can see it
        "type": "visual",
        "details": [
            {"id": "hinge_color",     "desc": "The hinge catches light differently."},
            {"id": "door_crack",      "desc": "A thin line of light bleeds through the edge."},
            {"id": "dust_pattern",    "desc": "The dust near the threshold is disturbed."},
            {"id": "shadow_angle",    "desc": "The shadow falls at a different angle."},
            {"id": "frame_wear",      "desc": "The frame is more worn than the others."},
            {"id": "surface_grain",   "desc": "The grain runs against the pattern."},
            {"id": "handle_offset",   "desc": "The handle sits slightly higher."},
        ],
    },
    2: {  # SPATIAL -- you have to think
        "type": "spatial",
        "details": [
            {"id": "symmetry_break",  "desc": "The spacing breaks the pattern."},
            {"id": "reflection_miss", "desc": "This door doesn't reflect your torch."},
            {"id": "numbering_gap",   "desc": "The sequence skips."},
            {"id": "alignment_off",   "desc": "Offset from the grid by a hair."},
            {"id": "depth_illusion",  "desc": "It appears closer than the others."},
            {"id": "echo_hollow",     "desc": "The wall behind it sounds different."},
            {"id": "draft_direction", "desc": "Air moves here. Nowhere else."},
        ],
    },
    3: {  # TEMPORAL -- you have to wait
        "type": "temporal",
        "details": [
            {"id": "flicker_rhythm",  "desc": "The nearby light flickers off-beat."},
            {"id": "dust_settling",   "desc": "The dust settles slower here."},
            {"id": "shadow_creep",    "desc": "This shadow moves. The others don't."},
            {"id": "condensation",    "desc": "Your breath fogs this one."},
            {"id": "warmth_gradient", "desc": "Warmer as you stand close."},
            {"id": "sound_decay",     "desc": "Sound lingers here a beat longer."},
            {"id": "pulse_interval",  "desc": "Something behind it breathes."},
        ],
    },
    4: {  # BEHAVIORAL -- the door reads you
        "type": "behavioral",
        "details": [
            {"id": "matches_dim",     "desc": "A rune you recognize. From your own practice."},
            {"id": "responds_verb",   "desc": "It shifted when you looked."},
            {"id": "fingerprint_glow","desc": "It knows your name."},
            {"id": "depth_resonance", "desc": "The deeper you are, the brighter it gets."},
            {"id": "silence_test",    "desc": "It only reveals itself when you stop moving."},
            {"id": "patience_gate",   "desc": "Stand still. Wait. It opens itself."},
            {"id": "mirror_self",     "desc": "You see your own shadow on this one. Only this one."},
        ],
    },
}


class CorridorScene:
    """
    One corridor: 8 doors, 1 correct, detail as clue.

    Parameters
    ----------
    seed          : base seed for the dungeon
    corridor_num  : which corridor (0-indexed)
    tier          : difficulty tier (1-4+)
    """

    def __init__(self, seed: int, corridor_num: int, tier: int):
        self.corridor_num = corridor_num
        self.tier = min(tier, 4)  # cap at tier 4
        self.rng = random.Random(f"{seed}_{corridor_num}_{tier}")

        # Pick which door is correct
        self._correct = self.rng.randint(0, 7)

        # Pick detail for this corridor
        tier_data = _TIER_DETAILS[self.tier]
        detail_entry = self.rng.choice(tier_data["details"])

        # Build doors
        self.doors = []
        for i in range(8):
            if i == self._correct:
                self.doors.append({
                    "index": i,
                    "correct": True,
                    "detail": detail_entry["id"],
                    "detail_type": tier_data["type"],
                    "description": detail_entry["desc"],
                })
            else:
                self.doors.append({
                    "index": i,
                    "correct": False,
                    "detail": None,
                    "detail_type": None,
                    "description": None,
                })

    def examine(self, door_index: int) -> dict:
        """
        Observe a door closely. OBSERVE verb encounter.
        Returns detail if correct door, nothing if wrong.
        """
        if door_index < 0 or door_index >= 8:
            return {"has_detail": False, "description": "No door here."}

        door = self.doors[door_index]
        if door["correct"]:
            return {
                "has_detail": True,
                "description": door["description"],
                "detail_type": door["detail_type"],
                "detail_id": door["detail"],
            }
        else:
            return {
                "has_detail": False,
                "description": "A door. Like the others.",
            }

    def try_door(self, door_index: int) -> dict:
        """
        Attempt to open a door. ACT verb encounter.
        Returns success/failure.
        """
        if door_index < 0 or door_index >= 8:
            return {"success": False, "reason": "invalid"}

        door = self.doors[door_index]
        return {
            "success": door["correct"],
            "door_index": door_index,
            "detail_type": door.get("detail_type"),
        }
