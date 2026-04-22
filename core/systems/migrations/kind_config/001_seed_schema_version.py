"""Seed migration: stamp schema_version: 1 on a pre-version config.

Before this migration, config/kind_config.json had no version field.
This migration is the line in the sand: after it runs, every config
carries an explicit version the migration runner can reason about.
"""
from __future__ import annotations

from typing import Any

VERSION = 1
DESCRIPTION = "Seed: establish schema_version field"


def up(config: dict[str, Any]) -> dict[str, Any]:
    config["schema_version"] = 1
    return config


def down(config: dict[str, Any]) -> dict[str, Any]:
    config.pop("schema_version", None)
    return config
