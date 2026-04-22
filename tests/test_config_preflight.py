"""Preflight orchestrator tests — config-lock #6."""
from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout

import pytest

from core.systems import config_preflight as preflight
from core.systems import kind_config_migrations as mig


# --- Individual checks ----------------------------------------------------


def test_check_schema_ok_on_valid_minimal_config() -> None:
    config = {"kinds": {"x": {"class": "geo"}}, "_class_defaults": {"geo": {}}}
    result = preflight.check_schema(config)
    assert result.ok and not result.warnings


def test_check_schema_errors_on_broken() -> None:
    result = preflight.check_schema({"kinds": "not_a_dict"})
    assert result.errors
    assert "schema" in result.errors[0]


def test_check_version_errors_on_stale() -> None:
    result = preflight.check_version({"kinds": {}})  # version 0
    assert result.errors
    assert "version" in result.errors[0]


def test_check_version_ok_at_current() -> None:
    config = {"schema_version": mig.current_version(), "kinds": {}}
    result = preflight.check_version(config)
    assert result.ok


def test_check_snapshot_warns_on_drift(tmp_path, monkeypatch) -> None:
    from core.systems import kind_config_snapshot as snap
    snap_path = tmp_path / "snap.json"
    snap.save_snapshot({"schema_version": 1, "kinds": {"x": {"class": "c"}}}, snap_path)
    monkeypatch.setattr(snap, "SNAPSHOT_PATH", snap_path)
    drifted = {"schema_version": 1, "kinds": {"x": {"class": "c"}, "y": {"class": "c"}}}
    result = preflight.check_snapshot(drifted)
    assert result.ok  # drift is WARN, not ERROR
    assert result.warnings
    assert "drift" in result.warnings[0].lower()


def test_check_snapshot_warns_when_missing(tmp_path, monkeypatch) -> None:
    from core.systems import kind_config_snapshot as snap
    monkeypatch.setattr(snap, "SNAPSHOT_PATH", tmp_path / "absent.json")
    result = preflight.check_snapshot({"kinds": {}})
    assert result.ok
    assert any("no snapshot" in w for w in result.warnings)


# --- Orchestration --------------------------------------------------------


def test_run_short_circuits_on_schema_error() -> None:
    """Don't run version/snapshot checks when schema is broken."""
    result = preflight.run({"kinds": "broken"})
    assert result.errors
    # Version check would have fired too; ensure only schema error is present.
    assert all("schema" in e for e in result.errors)


def test_run_reads_disk_when_no_config_passed() -> None:
    result = preflight.run()
    assert result.ok, result.errors + result.warnings


def test_assert_valid_config_state_raises_on_error() -> None:
    with pytest.raises(preflight.PreflightError):
        preflight.assert_valid_config_state({"kinds": "broken"}, print_warnings=False)


def test_assert_valid_config_state_passes_on_live_config() -> None:
    # include_snapshot=True because shipped snapshot tracks shipped config.
    preflight.assert_valid_config_state(print_warnings=False)


def test_skip_env_downgrades_errors_to_warnings(monkeypatch) -> None:
    monkeypatch.setenv("SANCTUM_SKIP_CONFIG_VALIDATION", "1")
    # A config that would normally error (wrong version, broken schema):
    bad = {"kinds": "broken"}
    result = preflight.assert_valid_config_state(bad, print_warnings=False)
    assert not result.errors
    assert any("(downgraded)" in w for w in result.warnings)


def test_cli_prints_ok_on_clean() -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = preflight.main([])
    assert code == 0
    assert "OK" in buf.getvalue()


def test_cli_returns_1_on_error(tmp_path, monkeypatch) -> None:
    from core.systems import kind_config_snapshot as snap
    broken = tmp_path / "bad.json"
    broken.write_text('{"kinds": "not_a_dict"}')
    monkeypatch.setattr(snap, "CONFIG_PATH", broken)
    err_buf = io.StringIO()
    with redirect_stderr(err_buf):
        code = preflight.main([])
    assert code == 1
    assert "ERROR" in err_buf.getvalue()
