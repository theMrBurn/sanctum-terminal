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


# --- subparts (composition) -------------------------------------------------

_BASE_KIND = {
    "_class_defaults": {"geo": {}},
    "kinds": {"widget": {"class": "geo"}},
}


def _kind_with(extras: dict) -> dict:
    """Build a minimal kind config with the given fields added to widget."""
    data = {
        "_class_defaults": {"geo": {}},
        "kinds": {"widget": {"class": "geo", **extras}},
    }
    return data


def test_subparts_valid_composition() -> None:
    """A torch-shaped composite (handle + flame) validates clean."""
    data = _kind_with({
        "render": {
            "subparts": [
                {"family": "tapered_vertical", "scale": [0.04, 0.04, 0.5],
                 "color": [0.4, 0.25, 0.15], "offset": [0, 0, 0]},
                {"family": "orb", "scale": 0.08,
                 "color": [1.0, 0.6, 0.2], "emission": 1.0, "offset": [0, 0, 0.5]},
            ]
        }
    })
    errors = kind_config_schema.validate(data)
    assert not errors, errors


def test_subparts_unknown_family_rejected() -> None:
    data = _kind_with({
        "render": {"subparts": [{"family": "definitely_not_a_primitive"}]}
    })
    errors = kind_config_schema.validate(data)
    assert any("primitive registry" in e for e in errors)


def test_subparts_missing_family_rejected() -> None:
    data = _kind_with({
        "render": {"subparts": [{"scale": 0.1}]}  # no family
    })
    errors = kind_config_schema.validate(data)
    assert any("missing required key 'family'" in e for e in errors)


def test_subparts_wrong_offset_rejected() -> None:
    data = _kind_with({
        "render": {"subparts": [{"family": "orb", "offset": [1, 2]}]}  # 2-tuple
    })
    errors = kind_config_schema.validate(data)
    assert any("offset" in e for e in errors)


def test_subparts_negative_emission_rejected() -> None:
    data = _kind_with({
        "render": {"subparts": [{"family": "orb", "emission": -1}]}
    })
    errors = kind_config_schema.validate(data)
    assert any("emission" in e for e in errors)


def test_subparts_not_list_rejected() -> None:
    data = _kind_with({"render": {"subparts": "not_a_list"}})
    errors = kind_config_schema.validate(data)
    assert any("expected list" in e for e in errors)


# --- wielded_effects + tool_reactions ---------------------------------------


def test_wielded_effects_valid() -> None:
    data = _kind_with({
        "wielded_effects": [
            {"type": "ignite", "duration": 3.0},
            {"type": "damage_hp", "amount": 5},
        ]
    })
    errors = kind_config_schema.validate(data)
    assert not errors, errors


def test_wielded_effects_missing_type_rejected() -> None:
    data = _kind_with({"wielded_effects": [{"amount": 5}]})  # no type
    errors = kind_config_schema.validate(data)
    assert any("missing required key 'type'" in e for e in errors)


def test_wielded_effects_not_list_rejected() -> None:
    data = _kind_with({"wielded_effects": {"type": "ignite"}})  # dict, not list
    errors = kind_config_schema.validate(data)
    assert any("expected list" in e for e in errors)


def test_tool_reactions_valid() -> None:
    data = _kind_with({
        "tool_reactions": {
            "fire": {"type": "ignite", "duration": 5.0},
            "ice": [
                {"type": "damage_hp", "amount": 3},
                {"type": "apply_status", "status": "frozen", "duration": 2.0},
            ],
        }
    })
    errors = kind_config_schema.validate(data)
    assert not errors, errors


def test_tool_reactions_malformed_spec_rejected() -> None:
    data = _kind_with({
        "tool_reactions": {"fire": {"no_type_key": True}}
    })
    errors = kind_config_schema.validate(data)
    assert any("missing required key 'type'" in e for e in errors)


# --- erosion fields ---------------------------------------------------------


def test_erosion_fields_valid() -> None:
    data = _kind_with({
        "erosion_rate": 0.05,
        "charge_max": 100,
        "erosion_mode": "time",
    })
    errors = kind_config_schema.validate(data)
    assert not errors, errors


def test_erosion_mode_unknown_rejected() -> None:
    data = _kind_with({"erosion_mode": "perpetual"})  # not in {"time", "use"}
    errors = kind_config_schema.validate(data)
    assert any("erosion_mode" in e for e in errors)


def test_erosion_rate_must_be_number() -> None:
    data = _kind_with({"erosion_rate": "fast"})
    errors = kind_config_schema.validate(data)
    assert any("erosion_rate" in e for e in errors)


def test_pickupable_must_be_bool() -> None:
    data = _kind_with({"pickupable": "yes"})
    errors = kind_config_schema.validate(data)
    assert any("pickupable" in e for e in errors)


def test_subparts_sprite_field_valid() -> None:
    """Optional sprite path on a flame subpart routes to billboard texture."""
    data = _kind_with({
        "render": {"subparts": [
            {"family": "flame", "scale": 0.4,
             "sprite": "lib/sprites/flame/flame_user_01.png"}
        ]}
    })
    errors = kind_config_schema.validate(data)
    assert not errors, errors


def test_subparts_sprite_must_be_string() -> None:
    data = _kind_with({
        "render": {"subparts": [{"family": "flame", "sprite": 42}]}
    })
    errors = kind_config_schema.validate(data)
    assert any("sprite" in e for e in errors)


# --- mission_loot (L7) ------------------------------------------------------

def test_mission_loot_string_form_valid() -> None:
    """Bare strings = guaranteed drops. Terse for simple cases."""
    data = _kind_with({"mission_loot": ["pot_shard", "ember"]})
    errors = kind_config_schema.validate(data)
    assert not errors, errors


def test_mission_loot_dict_form_valid() -> None:
    """{name, weight} for weighted drops. Brain rolls per entry."""
    data = _kind_with({
        "mission_loot": [
            {"name": "pot_shard", "weight": 1.0},
            {"name": "ember", "weight": 0.4},
        ]
    })
    errors = kind_config_schema.validate(data)
    assert not errors, errors


def test_mission_loot_mixed_forms_valid() -> None:
    data = _kind_with({
        "mission_loot": [
            "pot_shard",  # guaranteed
            {"name": "ember", "weight": 0.3},
        ]
    })
    errors = kind_config_schema.validate(data)
    assert not errors, errors


def test_mission_loot_must_be_list() -> None:
    data = _kind_with({"mission_loot": "pot_shard"})  # bare string
    errors = kind_config_schema.validate(data)
    assert any("mission_loot" in e for e in errors)


def test_mission_loot_dict_missing_name_rejected() -> None:
    data = _kind_with({"mission_loot": [{"weight": 0.5}]})
    errors = kind_config_schema.validate(data)
    assert any("missing required key 'name'" in e for e in errors)


def test_mission_loot_weight_out_of_range_rejected() -> None:
    data = _kind_with({"mission_loot": [{"name": "x", "weight": 1.5}]})
    errors = kind_config_schema.validate(data)
    assert any("weight" in e for e in errors)


def test_mission_loot_empty_name_rejected() -> None:
    data = _kind_with({"mission_loot": [""]})
    errors = kind_config_schema.validate(data)
    assert any("empty item name" in e for e in errors)


# --- consumable + use_effects (L8) -----------------------------------------

def test_consumable_with_use_effects_valid() -> None:
    data = _kind_with({
        "consumable": True,
        "use_effects": [{"type": "heal_player", "amount": 3}],
    })
    errors = kind_config_schema.validate(data)
    assert not errors, errors


def test_consumable_must_be_bool() -> None:
    data = _kind_with({"consumable": "yes"})
    errors = kind_config_schema.validate(data)
    assert any("consumable" in e for e in errors)


def test_use_effects_must_be_list() -> None:
    data = _kind_with({"use_effects": {"type": "heal_player"}})  # dict, not list
    errors = kind_config_schema.validate(data)
    assert any("expected list" in e for e in errors)


def test_use_effects_missing_type_rejected() -> None:
    data = _kind_with({"use_effects": [{"amount": 5}]})
    errors = kind_config_schema.validate(data)
    assert any("missing required key 'type'" in e for e in errors)
