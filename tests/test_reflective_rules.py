"""Reflective-mode rule registry + JSON loader.

Step 2 of PR 3.5. The rule registry holds Rule rows that bind a
player-facing micro-game (instructions + AC predicate chain) to an
id the brain picks at reflective entry.

Validates:
- Rule dataclass shape + immutability
- Registry pattern (register/get/all/clear/duplicate-rejection)
- JSON loader (correct row → Rule mapping)
- Default config registers `compose_three` on import
- Every shipped rule references a real AC predicate
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.systems.reflective import ac_predicates as ac_module
from core.systems.reflective import definitions
from core.systems.reflective import rules
from core.systems.reflective.rules import Rule


@pytest.fixture
def clean():
    """Each test gets a fresh registry. Teardown reloads the default
    config so subsequent tests still see `compose_three`."""
    rules.clear()
    yield
    rules.clear()
    definitions.load_rules_from_json()


# ── Rule dataclass ────────────────────────────────────────────────


def test_rule_required_fields():
    r = Rule(id="x", name="X", instructions="Do X.")
    assert r.id == "x"
    assert r.name == "X"
    assert r.instructions == "Do X."
    assert r.ac_predicates == []
    assert r.ac_args == {}


def test_rule_with_predicates():
    r = Rule(
        id="x",
        name="X",
        instructions="…",
        ac_predicates=["min_magnet_count"],
        ac_args={"min_magnet_count": {"count": 3}},
    )
    assert r.ac_predicates == ["min_magnet_count"]
    assert r.ac_args == {"min_magnet_count": {"count": 3}}


def test_rule_is_immutable():
    """Rule is a frozen dataclass — no accidental mutation of catalog entries."""
    r = Rule(id="x", name="X", instructions="…")
    with pytest.raises(Exception):  # FrozenInstanceError
        r.id = "different"  # type: ignore[misc]


# ── Registry ──────────────────────────────────────────────────────


def test_register_and_get(clean):
    r = Rule(id="test_rule", name="Test", instructions="…")
    rules.register(r)
    assert rules.get("test_rule") is r


def test_register_rejects_duplicate(clean):
    r = Rule(id="dup", name="Dup", instructions="…")
    rules.register(r)
    with pytest.raises(ValueError, match="already registered"):
        rules.register(r)


def test_unknown_rule_returns_none(clean):
    assert rules.get("does_not_exist") is None


def test_all_rules_returns_snapshot(clean):
    rules.register(Rule(id="a", name="A", instructions="…"))
    rules.register(Rule(id="b", name="B", instructions="…"))
    snap = rules.all_rules()
    snap.clear()
    # Mutating the snapshot doesn't affect the registry.
    assert rules.get("a") is not None
    assert rules.get("b") is not None


# ── JSON loader ───────────────────────────────────────────────────


def test_json_loader_registers_rows(tmp_path, clean):
    config = {
        "schema_version": 1,
        "rules": [
            {
                "id": "from_json",
                "name": "From JSON",
                "instructions": "Just commit.",
                "ac_predicates": ["min_magnet_count"],
                "ac_args": {"min_magnet_count": {"count": 5}},
            }
        ],
    }
    path = tmp_path / "rules.json"
    path.write_text(json.dumps(config))

    definitions.load_rules_from_json(path)

    r = rules.get("from_json")
    assert r is not None
    assert r.name == "From JSON"
    assert r.instructions == "Just commit."
    assert r.ac_predicates == ["min_magnet_count"]
    assert r.ac_args == {"min_magnet_count": {"count": 5}}


def test_json_loader_handles_missing_file(tmp_path, clean):
    """No-op when config file doesn't exist (early-bringup safety)."""
    bogus = tmp_path / "does_not_exist.json"
    definitions.load_rules_from_json(bogus)
    assert rules.all_rules() == {}


def test_json_loader_empty_rules_list(tmp_path, clean):
    path = tmp_path / "rules.json"
    path.write_text(json.dumps({"schema_version": 1, "rules": []}))
    definitions.load_rules_from_json(path)
    assert rules.all_rules() == {}


def test_json_loader_uses_id_as_default_name(tmp_path, clean):
    """Missing 'name' falls back to 'id' — defensive."""
    config = {
        "schema_version": 1,
        "rules": [{"id": "id_only"}],
    }
    path = tmp_path / "rules.json"
    path.write_text(json.dumps(config))
    definitions.load_rules_from_json(path)

    r = rules.get("id_only")
    assert r is not None
    assert r.name == "id_only"


# ── Default config integrity ──────────────────────────────────────


def test_compose_three_registered_on_import():
    """The shipped rules.json registers compose_three on package import."""
    r = rules.get("compose_three")
    assert r is not None
    assert r.name == "Compose"
    assert r.instructions  # non-empty player-facing copy
    assert r.ac_predicates == ["min_magnet_count"]
    assert r.ac_args == {"min_magnet_count": {"count": 3}}


def test_every_rule_references_real_ac_predicate():
    """Every shipped rule's ac_predicates list must reference a
    registered AC predicate. Catches typos at test time."""
    for rule_id, r in rules.all_rules().items():
        for pred_name in r.ac_predicates:
            assert ac_module.get(pred_name) is not None, (
                f"rule {rule_id!r} references unknown AC predicate "
                f"{pred_name!r}"
            )


def test_default_config_path_exists():
    """The shipped rules.json must exist where definitions.py expects it."""
    from core.systems.reflective.definitions import RULES_PATH
    assert RULES_PATH.exists()
    data = json.loads(RULES_PATH.read_text())
    assert "schema_version" in data
    assert isinstance(data.get("rules", []), list)
