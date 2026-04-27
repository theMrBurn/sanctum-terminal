"""Schema validator for config/kind_config.json.

Config-lock #1 (design_thoughts.txt:864-888, highest leverage of the 6-point
protocol). Brain refuses to start when the config is structurally broken and
reports the exact field path that failed. This is drift insurance against the
daily "I edited the wrong key" derailments.

Design choice: hand-rolled validator over pydantic/jsonschema. Zero new deps,
error messages carry file path + key path + expected-vs-actual in one line,
and the schema lives next to the loader rather than in a separate .json file.

Call `validate(data)` to get a list of error strings; empty list = valid.
Call `assert_valid(data)` to raise ConfigError with all errors joined.
"""
from __future__ import annotations

from typing import Any, Iterable


class ConfigError(ValueError):
    """Raised when kind_config.json fails schema validation."""


# --- Low-level type helpers -------------------------------------------------


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_color(v: Any, length: int = 3) -> bool:
    return (
        isinstance(v, list)
        and len(v) == length
        and all(_is_number(c) for c in v)
    )


def _is_vec3(v: Any) -> bool:
    return _is_color(v, 3)


def _check_required(
    data: dict[str, Any], keys: Iterable[str], path: str
) -> list[str]:
    errors: list[str] = []
    for key in keys:
        if key not in data:
            errors.append(f"{path}: missing required key {key!r}")
    return errors


# --- Section validators -----------------------------------------------------


def _validate_color_fields(
    obj: dict[str, Any], path: str, keys: Iterable[str] = ("color_base", "color_shadow", "color_accent")
) -> list[str]:
    errors: list[str] = []
    for k in keys:
        if k not in obj:
            continue  # optional; only check when present
        if not _is_color(obj[k], 3):
            errors.append(
                f"{path}.{k}: expected [r,g,b] (3 numbers), got {obj[k]!r}"
            )
    return errors


def _validate_physics(physics: Any, path: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(physics, dict):
        return [f"{path}: expected object, got {type(physics).__name__}"]
    if "collision_radius" in physics:
        cr = physics["collision_radius"]
        if not _is_number(cr) or cr < 0:
            errors.append(
                f"{path}.collision_radius: expected non-negative number, got {cr!r}"
            )
    return errors


def _validate_render(render: Any, path: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(render, dict):
        return [f"{path}: expected object, got {type(render).__name__}"]
    if "scale" in render:
        s = render["scale"]
        if not (_is_number(s) or _is_vec3(s)):
            errors.append(
                f"{path}.scale: expected number or [x,y,z], got {s!r}"
            )
    if "color" in render:
        c = render["color"]
        if not (_is_color(c, 3) or _is_color(c, 4)):
            errors.append(
                f"{path}.color: expected [r,g,b] or [r,g,b,a], got {c!r}"
            )
    if "emissive" in render:
        e = render["emissive"]
        if not _is_number(e) or e < 0:
            errors.append(
                f"{path}.emissive: expected non-negative number, got {e!r}"
            )
    if "z_offset" in render:
        z = render["z_offset"]
        if not (isinstance(z, list) and len(z) == 2
                and all(_is_number(v) for v in z) and z[0] <= z[1]):
            errors.append(
                f"{path}.z_offset: expected [min, max] with min <= max, got {z!r}"
            )
    return errors


def _validate_scale_override(val: Any, path: str) -> list[str]:
    if val is None:
        return []
    if not isinstance(val, dict):
        return [f"{path}: expected null or object with x,y,z, got {type(val).__name__}"]
    errors: list[str] = []
    for axis in ("x", "y", "z"):
        if axis not in val:
            errors.append(f"{path}: missing axis {axis!r}")
        elif not _is_number(val[axis]):
            errors.append(
                f"{path}.{axis}: expected number, got {val[axis]!r}"
            )
    return errors


def _validate_class_block(
    cfg: dict[str, Any], path: str
) -> list[str]:
    """A class default or per-kind block — colors, radii, physics, render."""
    errors: list[str] = []
    errors.extend(_validate_color_fields(cfg, path))
    if "color_cap" in cfg and not _is_color(cfg["color_cap"], 3):
        errors.append(
            f"{path}.color_cap: expected [r,g,b], got {cfg['color_cap']!r}"
        )
    if "physics" in cfg:
        errors.extend(_validate_physics(cfg["physics"], f"{path}.physics"))
    if "render" in cfg:
        errors.extend(_validate_render(cfg["render"], f"{path}.render"))
    if "scale_override" in cfg:
        errors.extend(
            _validate_scale_override(cfg["scale_override"], f"{path}.scale_override")
        )
    for num_key in (
        "visual_radius", "band_strength", "wind_strength", "ghost_chance",
        "fade_in_near", "fade_in_far", "sink", "taper_strength",
        "twist_amount", "world_scale_mult",
    ):
        if num_key in cfg and not _is_number(cfg[num_key]):
            errors.append(
                f"{path}.{num_key}: expected number, got {cfg[num_key]!r}"
            )
    for bool_key in ("light_reactive", "use_vertex_colors"):
        if bool_key in cfg and not isinstance(cfg[bool_key], bool):
            errors.append(
                f"{path}.{bool_key}: expected bool, got {cfg[bool_key]!r}"
            )
    return errors


def _validate_class_defaults(defaults: Any) -> tuple[list[str], set[str]]:
    """Returns (errors, set_of_known_class_names)."""
    if not isinstance(defaults, dict):
        return (
            [f"_class_defaults: expected object, got {type(defaults).__name__}"],
            set(),
        )
    errors: list[str] = []
    for class_name, cfg in defaults.items():
        path = f"_class_defaults.{class_name}"
        if not isinstance(cfg, dict):
            errors.append(f"{path}: expected object, got {type(cfg).__name__}")
            continue
        errors.extend(_validate_class_block(cfg, path))
    return errors, set(defaults.keys())


def _validate_vertex_color_passthrough(cfg: dict[str, Any], path: str) -> list[str]:
    """When use_vertex_colors is True, render.color must be [1,1,1].

    Vertex-color kinds render via individual MeshInstance3D paths where the
    mesh's baked COLOR stream drives pixels. Manifest r/g/b is dead data on
    this path — declaring a non-[1,1,1] render.color creates a "two sources
    of truth" ambiguity that's caused real-user "what color is this kind?"
    confusion. Require [1,1,1] passthrough so there's exactly one answer:
    color_base/shadow/accent own the palette, render.color is unused.
    """
    if not cfg.get("use_vertex_colors", False):
        return []
    render = cfg.get("render", {})
    if "color" not in render:
        return []
    c = render["color"]
    if not _is_color(c, 3) and not _is_color(c, 4):
        return []  # a separate rule will catch the shape error
    if c[:3] != [1.0, 1.0, 1.0]:
        return [
            f"{path}.render.color: must be [1,1,1] when use_vertex_colors=True "
            f"(vertex-color kinds ignore manifest r/g/b; use color_base instead), "
            f"got {c!r}"
        ]
    return []


def _validate_kinds(kinds: Any, known_classes: set[str]) -> list[str]:
    if not isinstance(kinds, dict):
        return [f"kinds: expected object, got {type(kinds).__name__}"]
    errors: list[str] = []
    for kind_name, cfg in kinds.items():
        path = f"kinds.{kind_name}"
        if not isinstance(cfg, dict):
            errors.append(f"{path}: expected object, got {type(cfg).__name__}")
            continue
        # Every kind must declare a class; class must exist in defaults.
        if "class" not in cfg:
            errors.append(f"{path}: missing required key 'class'")
        else:
            cls = cfg["class"]
            if not isinstance(cls, str):
                errors.append(f"{path}.class: expected string, got {cls!r}")
            elif known_classes and cls not in known_classes:
                errors.append(
                    f"{path}.class: {cls!r} not declared in _class_defaults "
                    f"(known: {sorted(known_classes)})"
                )
        errors.extend(_validate_class_block(cfg, path))
        errors.extend(_validate_vertex_color_passthrough(cfg, path))
    return errors


def _validate_global(glob: Any) -> list[str]:
    if glob is None:
        return []  # _global is optional
    if not isinstance(glob, dict):
        return [f"_global: expected object, got {type(glob).__name__}"]
    errors: list[str] = []
    if "reaction_patterns" in glob:
        rp = glob["reaction_patterns"]
        if not isinstance(rp, dict):
            errors.append(
                f"_global.reaction_patterns: expected object, got {type(rp).__name__}"
            )
        else:
            for name, pattern in rp.items():
                p = f"_global.reaction_patterns.{name}"
                if not isinstance(pattern, dict):
                    errors.append(
                        f"{p}: expected object, got {type(pattern).__name__}"
                    )
                    continue
                if "color_tint" in pattern and not _is_color(pattern["color_tint"], 3):
                    errors.append(
                        f"{p}.color_tint: expected [r,g,b], got {pattern['color_tint']!r}"
                    )
                for num_key in ("duration", "peak_energy"):
                    if num_key in pattern and not _is_number(pattern[num_key]):
                        errors.append(
                            f"{p}.{num_key}: expected number, got {pattern[num_key]!r}"
                        )
    return errors


# --- Public API -------------------------------------------------------------


def validate(data: Any) -> list[str]:
    """Return list of error strings. Empty list means the config is valid.

    Each error is a single line of form "path.to.field: reason" so they can
    be printed directly without further formatting.
    """
    if not isinstance(data, dict):
        return [f"<root>: expected object, got {type(data).__name__}"]

    errors: list[str] = []
    errors.extend(_check_required(data, ("kinds",), "<root>"))
    errors.extend(_validate_global(data.get("_global")))
    class_errors, known_classes = _validate_class_defaults(
        data.get("_class_defaults", {})
    )
    errors.extend(class_errors)
    errors.extend(_validate_kinds(data.get("kinds", {}), known_classes))
    return errors


def assert_valid(data: Any) -> None:
    """Raise ConfigError if validation fails, else return None."""
    errors = validate(data)
    if errors:
        joined = "\n  - ".join(errors)
        raise ConfigError(
            f"kind_config.json failed schema validation ({len(errors)} errors):\n  - {joined}"
        )
