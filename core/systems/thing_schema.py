"""Thing schema — wireframe model from a description with reliable math.

A `Thing` is a named composition of N primitive parts with explicit
real-world dimensions. Math is bounded + predictable:

    real_size_m       — bounding box in meters (w, d, h)
    part.rel_size     — fraction of real_size_m, in (0, 1]
    part.rel_position — offset from thing center, in [-0.5, 0.5] of real_size_m

A "longsword" with real_size_m=[0.15, 0.04, 1.10] and a "head" part at
rel_position=[0, 0, 0.45] places that head at world-Z = thing_origin_z
+ 0.45 × 1.10 = +49.5cm above the sword's center. Predictable.

This is the gating piece for `find me 5 swords and render them` —
schema math that's reliable enough for me to draft compositions
without you having to verify the coordinates by hand.

Vocabulary is bounded against `clients/vector_terminal/recipes.py`:
12 primitives, no silent invention. Anything outside the vocab is
caught at validation time.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


# ── Bounded vocabularies ─────────────────────────────────────────

PRIMITIVES: tuple[str, ...] = (
    "orb",
    "tapered_vertical",
    "banner",
    "heptagonal_mote",
    "silhouette_void",
    "lattice_7",
    "scatter_7",
    "chain",
    "ground_hug",
    "vector_sprite",
    "cube",
    "octahedron",
    "water_plane",
)


# Visual reference per primitive — what the recipe in
# `clients/vector_terminal/recipes.py` actually RENDERS as, not what
# the name suggests. Use when authoring: pick by silhouette, not by
# english word.
#
# Hard-won lesson 2026-05-14: "vector_sprite" sounds like "any 2D
# sprite shape" — it's actually a T-pose HUMANOID figure. Putting it
# on a scimitar blade rendered a person standing on a hilt.
PRIMITIVE_VISUAL: dict[str, str] = {
    "orb":              "low-poly sphere (8x12 wireframe)",
    "tapered_vertical": "vertical cylinder (8-segment), oriented along z-axis",
    "banner":           "flat panel facing +z with inner cross — sign / poster",
    "heptagonal_mote":  "horizontal 7-vertex ring at y=0, no faces — mote/spark",
    "silhouette_void":  "STICK FIGURE — head+spine+shoulders+arms+legs skeleton",
    "lattice_7":        "wheel / hub: center vertex + 6 spokes + outer ring",
    "scatter_7":        "irregular 7-point cloud connected by cross-links",
    "chain":            "three stacked link cubes along z, connectors between",
    "ground_hug":       "flat disc at y≈0 — tile / decal / shadow plate",
    "vector_sprite":    "T-POSE HUMANOID — head diamond + body + arms + legs",
    "cube":             "cube — six faces, twelve edges",
    "octahedron":       "diamond bipyramid — sharper crystal silhouette",
    "water_plane":      "6x6 horizontal grid — animated sin-wave Y displacement, reads as flowing water (river/pool/lake/ocean)",
}

TIERS: tuple[str, ...] = ("silhouette", "mid", "hero")

# Sanity bounds
SIZE_MIN_M: float = 0.02
SIZE_MAX_M: float = 50.0
REL_POS_BOUND: float = 0.5      # rel_position must be in [-REL_POS_BOUND, REL_POS_BOUND]
REL_SIZE_MIN: float = 0.001
REL_SIZE_MAX: float = 1.0
PARTS_MIN: int = 1
PARTS_MAX: int = 12


# ── Dataclasses ──────────────────────────────────────────────────


@dataclass
class ThingPart:
    primitive: str
    role: str
    rel_size: tuple[float, float, float]
    rel_position: tuple[float, float, float]
    rotation_deg: float = 0.0
    color_base:   tuple[float, float, float] | None = None
    color_shadow: tuple[float, float, float] | None = None
    color_accent: tuple[float, float, float] | None = None
    tier: str = "silhouette"
    negate: bool = False           # primitive-inversion flag


@dataclass
class Thing:
    name: str
    real_size_m: tuple[float, float, float]
    anchor: str
    parts: list[ThingPart] = field(default_factory=list)
    source: str | None = None      # provenance — image/description/etc.
    tags:   list[str] = field(default_factory=list)   # query keys for the Blender
    # Verb → response text. V1 vocabulary: "examine" (the classic
    # NetHack/Doom move). Future verbs (pickup, kick, break, light)
    # land as code + handler additions, not schema changes.
    interactions: dict[str, str] = field(default_factory=dict)
    # World-attach mode — what world feature the bbox-bottom snaps to.
    # Per the 2026-05-18 attach_mode primitive PR (Unity/Unreal-style
    # "pivot on floor" convention extended for elevation transitions).
    # See ATTACH_MODES for the enum.
    attach_mode: str = "floor"


# Bounded vocabulary for Thing.attach_mode. Authors pick one; placement
# code resolves the world Y reference accordingly.
#
#   floor          — bbox-bottom on the standing tile's floor. Default.
#                    Trees, posts, ferns, props, ladders, stairs, doors.
#   upper_floor    — bbox-bottom on the HIGHER of two adjacent tiles
#                    at a terrain transition. Bridges, gantries, ramps
#                    whose deck must align with the destination tier.
#   water_surface  — bbox-bottom on the water plane. Lily pads, boats,
#                    floating debris. (Reserved — no fixtures yet.)
#
# Per the "one anchor per asset, attach mode picks the world feature"
# convention across Unity / Unreal / Bethesda / modular kit games.
ATTACH_MODES: tuple[str, ...] = (
    "floor",
    "upper_floor",
    "water_surface",
)


# ── Validation ───────────────────────────────────────────────────


@dataclass
class ValidationError:
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


def validate_thing_dict(data: Any) -> list[ValidationError]:
    """Validate raw dict (e.g. loaded from JSON) against the schema."""
    errors: list[ValidationError] = []

    if not isinstance(data, dict):
        return [ValidationError("$", f"expected object, got {type(data).__name__}")]

    # name
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append(ValidationError("$.name", "must be non-empty string"))

    # real_size_m
    rs = data.get("real_size_m")
    if not _is_vec3(rs):
        errors.append(ValidationError(
            "$.real_size_m", "must be [w, d, h] of numbers"))
    else:
        for i, v in enumerate(rs):
            v = float(v)
            if not (SIZE_MIN_M <= v <= SIZE_MAX_M):
                errors.append(ValidationError(
                    f"$.real_size_m[{i}]",
                    f"must be in [{SIZE_MIN_M}, {SIZE_MAX_M}], got {v}"))

    # anchor (must match one part role)
    anchor = data.get("anchor")
    if not isinstance(anchor, str):
        errors.append(ValidationError("$.anchor", "must be string"))

    # interactions (optional dict[verb_str → text_str])
    if "interactions" in data:
        actions = data["interactions"]
        if not isinstance(actions, dict):
            errors.append(ValidationError(
                "$.interactions",
                f"must be object, got {type(actions).__name__}"))
        else:
            for verb, response in actions.items():
                if not isinstance(verb, str) or not verb.strip():
                    errors.append(ValidationError(
                        f"$.interactions.{verb!r}",
                        "verb must be non-empty string"))
                if not isinstance(response, str):
                    errors.append(ValidationError(
                        f"$.interactions.{verb}",
                        f"response must be string, got {type(response).__name__}"))

    # attach_mode (optional, defaults to "floor"). Bounded vocab per
    # ATTACH_MODES — author can pick how the bbox relates to world
    # features (floor, upper tile floor at terrain transitions, water
    # surface). Per the 2026-05-18 attach_mode primitive PR.
    if "attach_mode" in data:
        am = data["attach_mode"]
        if not isinstance(am, str):
            errors.append(ValidationError(
                "$.attach_mode",
                f"must be string, got {type(am).__name__}"))
        elif am not in ATTACH_MODES:
            errors.append(ValidationError(
                "$.attach_mode",
                f"unknown mode {am!r}; allowed: {ATTACH_MODES}"))

    # tags (optional list of non-empty strings)
    if "tags" in data:
        tags = data["tags"]
        if not isinstance(tags, list):
            errors.append(ValidationError(
                "$.tags", f"must be list, got {type(tags).__name__}"))
        else:
            for i, t in enumerate(tags):
                if not isinstance(t, str) or not t.strip():
                    errors.append(ValidationError(
                        f"$.tags[{i}]", "must be non-empty string"))

    # parts
    parts = data.get("parts")
    if not isinstance(parts, list):
        errors.append(ValidationError(
            "$.parts", f"must be list, got {type(parts).__name__}"))
        return errors      # can't continue without parts list
    if not (PARTS_MIN <= len(parts) <= PARTS_MAX):
        errors.append(ValidationError(
            "$.parts",
            f"must have {PARTS_MIN}-{PARTS_MAX} entries, got {len(parts)}"))

    anchor_seen = False
    for i, part in enumerate(parts):
        errors.extend(_validate_part(part, f"$.parts[{i}]"))
        if isinstance(part, dict) and part.get("role") == anchor:
            anchor_seen = True
    if isinstance(anchor, str) and parts and not anchor_seen:
        errors.append(ValidationError(
            "$.anchor",
            f"anchor role {anchor!r} not found in any part"))

    return errors


def _validate_part(part: Any, prefix: str) -> list[ValidationError]:
    errors: list[ValidationError] = []
    if not isinstance(part, dict):
        return [ValidationError(prefix, f"expected object, got {type(part).__name__}")]

    # primitive
    prim = part.get("primitive")
    if not isinstance(prim, str):
        errors.append(ValidationError(f"{prefix}.primitive", "must be string"))
    elif prim not in PRIMITIVES:
        errors.append(ValidationError(
            f"{prefix}.primitive",
            f"unknown primitive {prim!r}. Allowed: {sorted(PRIMITIVES)}"))

    # role
    role = part.get("role")
    if not isinstance(role, str) or not role.strip():
        errors.append(ValidationError(f"{prefix}.role", "must be non-empty string"))

    # rel_size — must be vec3 of floats in (REL_SIZE_MIN, REL_SIZE_MAX]
    rs = part.get("rel_size")
    if not _is_vec3(rs):
        errors.append(ValidationError(
            f"{prefix}.rel_size", "must be [w, d, h] of numbers"))
    else:
        for i, v in enumerate(rs):
            v = float(v)
            if not (REL_SIZE_MIN <= v <= REL_SIZE_MAX):
                errors.append(ValidationError(
                    f"{prefix}.rel_size[{i}]",
                    f"must be in ({REL_SIZE_MIN}, {REL_SIZE_MAX}], got {v}"))

    # rel_position — must be vec3 of floats in [-REL_POS_BOUND, REL_POS_BOUND]
    rp = part.get("rel_position")
    if not _is_vec3(rp):
        errors.append(ValidationError(
            f"{prefix}.rel_position", "must be [x, y, z] of numbers"))
    else:
        for i, v in enumerate(rp):
            v = float(v)
            if not (-REL_POS_BOUND <= v <= REL_POS_BOUND):
                errors.append(ValidationError(
                    f"{prefix}.rel_position[{i}]",
                    f"must be in [{-REL_POS_BOUND}, {REL_POS_BOUND}], got {v}"))

    # rotation_deg (optional)
    if "rotation_deg" in part:
        rd = part["rotation_deg"]
        if not isinstance(rd, (int, float)) or isinstance(rd, bool):
            errors.append(ValidationError(f"{prefix}.rotation_deg", "must be number"))

    # tier (optional, default silhouette)
    if "tier" in part:
        tier = part["tier"]
        if not isinstance(tier, str) or tier not in TIERS:
            errors.append(ValidationError(
                f"{prefix}.tier",
                f"unknown tier {tier!r}. Allowed: {sorted(TIERS)}"))

    # negate (optional, bool)
    if "negate" in part and not isinstance(part["negate"], bool):
        errors.append(ValidationError(f"{prefix}.negate", "must be bool"))

    # color fields (optional, each [r, g, b] in [0, 1])
    for color_key in ("color_base", "color_shadow", "color_accent"):
        if color_key in part:
            c = part[color_key]
            if c is None:
                continue
            if not _is_vec3(c):
                errors.append(ValidationError(
                    f"{prefix}.{color_key}", "must be [r, g, b] of numbers"))
                continue
            for i, v in enumerate(c):
                v = float(v)
                if not (0.0 <= v <= 1.0):
                    errors.append(ValidationError(
                        f"{prefix}.{color_key}[{i}]",
                        f"must be in [0, 1], got {v}"))

    return errors


def _is_vec3(v: Any) -> bool:
    return (
        isinstance(v, (list, tuple))
        and len(v) == 3
        and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v)
    )


# ── Loading + parsing ────────────────────────────────────────────


def parse_thing(data: dict[str, Any]) -> Thing:
    """Build a Thing dataclass from a validated dict.

    Caller should run `validate_thing_dict()` first; this assumes the
    data is shape-valid.
    """
    parts = [_parse_part(p) for p in data["parts"]]
    raw_tags = data.get("tags") or []
    raw_interactions = data.get("interactions") or {}
    return Thing(
        name=str(data["name"]),
        real_size_m=tuple(float(v) for v in data["real_size_m"]),
        anchor=str(data["anchor"]),
        parts=parts,
        source=data.get("source"),
        tags=[str(t) for t in raw_tags if isinstance(t, str) and t.strip()],
        interactions={
            str(k): str(v) for k, v in raw_interactions.items()
            if isinstance(k, str) and k.strip() and isinstance(v, str)
        },
        attach_mode=str(data.get("attach_mode", "floor")),
    )


def _parse_part(d: dict[str, Any]) -> ThingPart:
    return ThingPart(
        primitive=str(d["primitive"]),
        role=str(d["role"]),
        rel_size=tuple(float(v) for v in d["rel_size"]),
        rel_position=tuple(float(v) for v in d["rel_position"]),
        rotation_deg=float(d.get("rotation_deg", 0.0)),
        color_base=_maybe_color(d.get("color_base")),
        color_shadow=_maybe_color(d.get("color_shadow")),
        color_accent=_maybe_color(d.get("color_accent")),
        tier=str(d.get("tier", "silhouette")),
        negate=bool(d.get("negate", False)),
    )


def _maybe_color(c: Any) -> tuple[float, float, float] | None:
    if c is None:
        return None
    return (float(c[0]), float(c[1]), float(c[2]))


def load_thing(path: Path | str) -> Thing:
    """Read + validate + parse one thing JSON file. Raises ValueError
    on schema violation with the full error list."""
    p = Path(path).expanduser()
    data = json.loads(p.read_text())
    errs = validate_thing_dict(data)
    if errs:
        raise ValueError(
            f"thing at {p} failed validation ({len(errs)} errors):\n  "
            + "\n  ".join(str(e) for e in errs)
        )
    return parse_thing(data)


def load_things_from_dir(dir_path: Path | str) -> dict[str, Thing]:
    """Walk a directory of *.json files, return name → Thing.
    Skips invalid files with a stderr warning rather than crashing."""
    import sys
    d = Path(dir_path).expanduser()
    if not d.exists():
        return {}
    out: dict[str, Thing] = {}
    for p in sorted(d.iterdir()):
        if p.suffix != ".json":
            continue
        try:
            thing = load_thing(p)
            out[thing.name] = thing
        except (ValueError, json.JSONDecodeError) as exc:
            sys.stderr.write(f"thing_schema: skipping {p}: {exc}\n")
    return out
