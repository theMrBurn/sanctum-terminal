"""Universal dial input primitive — every prompt is a constrained scale.

Per `design_dial_input`: every interaction in the game (pillars, latches,
chests, dialog choices, vendor purchases, journal moments) ships a
DialPrompt to the client. Player commits one option; brain handles via
the source-routed `dial_response` command.

The primitive is data-only. Logic lives in PillarHandlers and other
source-specific dispatchers — they construct DialPrompts and consume
the chosen value.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# Visual / timing register — vector_terminal reads this to apply
# context-appropriate pulse rate, glow timing, etc. Brain just tags;
# clients interpret. See `design_dial_input` atmospheric register table.
RITUAL = "ritual"            # pillars, sacred moments — slow breath pulse
TENSE = "tense"              # encounter actions, parley — tight kinetic
AMBIENT = "ambient"          # chests, latches, passive discovery — light glance
REFLECTIVE = "reflective"    # journal, meditation — peripheral, optional
TRANSACTIONAL = "transactional"  # vendor, trade — moderate, list-like


# Mode determines how the dial presents its range:
# - "select": all options visible at once. Best for finite small ranges (2-7).
# - "narrow": binary CAT cascade — each ask is "older or younger than X?".
#   Best for continuous ranges (1-100) or large discrete sets.
SELECT = "select"
NARROW = "narrow"


@dataclass
class DialOption:
    label: str
    value: Any
    bias: str | None = None  # contextual hint shown next to the option


@dataclass
class DialPrompt:
    source: str                    # "pillar:name", "chest:47", "watcher:dialog"
    label: str                     # framing text — short, evocative
    mode: str                      # "select" | "narrow"
    options: list[DialOption]
    default_index: int             # which option is highlighted on engage
    register: str = RITUAL         # visual/timing context for client renderer
    multi_select_max: int = 1
    # narrow-mode only
    pivot_value: Any = None
    range_remaining: tuple = ()


def to_manifest(prompt: DialPrompt) -> dict:
    """Serialize for transmission in the manifest. Clients reconstruct
    behavior from this shape."""
    return {
        "source": prompt.source,
        "label": prompt.label,
        "mode": prompt.mode,
        "options": [
            {"label": o.label, "value": o.value, "bias": o.bias}
            for o in prompt.options
        ],
        "default_index": prompt.default_index,
        "register": prompt.register,
        "multi_select_max": prompt.multi_select_max,
        "pivot_value": prompt.pivot_value,
        "range_remaining": list(prompt.range_remaining) if prompt.range_remaining else [],
    }
