"""Schema validator tests — config-lock #1.

Guards the validation rules in core/systems/kind_config_schema.py. The real
config/kind_config.json must pass (no regressions), and known breakage
patterns must produce clear errors pointing at the exact field.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.systems import kind_config, kind_config_schema

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CONFIG_PATH = _REPO_ROOT / "config" / "kind_config.json"


@pytest.fixture
def live_config() -> dict:
    with _CONFIG_PATH.open() as f:
        return json.load(f)


# --- Real-config guard -------------------------------------------------------


def test_live_config_validates(live_config: dict) -> None:
    """The shipped kind_config.json must pass validation."""
    errors = kind_config_schema.validate(live_config)
    assert not errors, "\n".join(errors)


def test_load_surfaces_validation_on_broken_config(
    tmp_path, monkeypatch
) -> None:
    """kind_config.load() must raise ConfigError when the file is broken."""
    # Build a broken config (missing kinds root).
    broken = tmp_path / "kind_config.json"
    broken.write_text('{"_class_defaults": {}}')
    monkeypatch.setattr(kind_config, "_CONFIG_PATH", broken)
    monkeypatch.setattr(kind_config, "_cache", None)
    with pytest.raises(kind_config_schema.ConfigError):
        kind_config.load()


def test_skip_validation_env_bypasses_lock(
    tmp_path, monkeypatch, live_config
) -> None:
    """SANCTUM_SKIP_CONFIG_VALIDATION=1 disables the gate for dev work."""
    bad = tmp_path / "kind_config.json"
    bad.write_text('{"kinds": {"bogus": {"class": "not_a_class"}}}')
    monkeypatch.setattr(kind_config, "_CONFIG_PATH", bad)
    monkeypatch.setattr(kind_config, "_cache", None)
    monkeypatch.setenv("SANCTUM_SKIP_CONFIG_VALIDATION", "1")
    # Should not raise; cache populates.
    assert kind_config.load() is not None


# --- Error-path coverage ----------------------------------------------------


def test_missing_kinds_root_reported() -> None:
    errors = kind_config_schema.validate({})
    assert any("missing required key 'kinds'" in e for e in errors)


def test_non_dict_root_reported() -> None:
    errors = kind_config_schema.validate(["not", "a", "dict"])
    assert any("<root>" in e for e in errors)


def test_unknown_class_on_kind_reported() -> None:
    data = {
        "_class_defaults": {"geological": {}},
        "kinds": {"widget": {"class": "nonexistent_class"}},
    }
    errors = kind_config_schema.validate(data)
    assert any(
        "kinds.widget.class" in e and "nonexistent_class" in e
        for e in errors
    )


def test_kind_missing_class_reported() -> None:
    data = {
        "_class_defaults": {"geological": {}},
        "kinds": {"widget": {"color_base": [0.1, 0.2, 0.3]}},
    }
    errors = kind_config_schema.validate(data)
    assert any("kinds.widget: missing required key 'class'" in e for e in errors)


def test_wrong_color_shape_reported() -> None:
    data = {
        "_class_defaults": {"geo": {}},
        "kinds": {"widget": {"class": "geo", "color_base": [0.5, 0.5]}},
    }
    errors = kind_config_schema.validate(data)
    assert any("kinds.widget.color_base" in e for e in errors)


def test_negative_collision_radius_reported() -> None:
    data = {
        "_class_defaults": {"geo": {}},
        "kinds": {
            "widget": {"class": "geo", "physics": {"collision_radius": -1.0}}
        },
    }
    errors = kind_config_schema.validate(data)
    assert any("collision_radius" in e for e in errors)


def test_bad_render_scale_reported() -> None:
    data = {
        "_class_defaults": {"geo": {}},
        "kinds": {
            "widget": {"class": "geo", "render": {"scale": "huge"}}
        },
    }
    errors = kind_config_schema.validate(data)
    assert any("render.scale" in e for e in errors)


def test_bad_scale_override_reported() -> None:
    data = {
        "_class_defaults": {"geo": {}},
        "kinds": {
            "widget": {
                "class": "geo",
                "scale_override": {"x": 1.0, "y": 2.0},  # missing z
            }
        },
    }
    errors = kind_config_schema.validate(data)
    assert any("scale_override" in e for e in errors)


def test_vertex_colors_true_forbids_non_white_render_color() -> None:
    """Passthrough convention: use_vertex_colors=True → render.color=[1,1,1]."""
    data = {
        "_class_defaults": {"geo": {}},
        "kinds": {
            "widget": {
                "class": "geo",
                "use_vertex_colors": True,
                "render": {"color": [0.5, 0.3, 0.2]},
            },
        },
    }
    errors = kind_config_schema.validate(data)
    assert any(
        "widget.render.color" in e and "use_vertex_colors=True" in e
        for e in errors
    ), errors


def test_vertex_colors_true_with_white_render_color_passes() -> None:
    data = {
        "_class_defaults": {"geo": {}},
        "kinds": {
            "widget": {
                "class": "geo",
                "use_vertex_colors": True,
                "render": {"color": [1.0, 1.0, 1.0]},
            },
        },
    }
    errors = kind_config_schema.validate(data)
    assert not any("use_vertex_colors" in e for e in errors)


def test_vertex_colors_false_allows_colored_render_color() -> None:
    """Facet kinds rely on render.color for MultiMesh instance coloring."""
    data = {
        "_class_defaults": {"geo": {}},
        "kinds": {
            "widget": {
                "class": "geo",
                "use_vertex_colors": False,
                "render": {"color": [0.5, 0.3, 0.2]},
            },
        },
    }
    errors = kind_config_schema.validate(data)
    assert not any("use_vertex_colors" in e for e in errors)


def test_assert_valid_lists_all_errors() -> None:
    data = {
        "kinds": {
            "bad_a": {"color_base": "not_a_color"},
            "bad_b": {"class": "missing", "physics": {"collision_radius": -5}},
        }
    }
    with pytest.raises(kind_config_schema.ConfigError) as exc_info:
        kind_config_schema.assert_valid(data)
    msg = str(exc_info.value)
    assert "bad_a" in msg
    assert "bad_b" in msg
