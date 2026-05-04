"""Magnet pool composition — what the player has on the fridge each entry.

Per `design_reflective_loop`: three pool layers compose into the
per-respawn magnet tray:

  - Connectives — articles, prepositions, copulas, pronouns. Always
    present. Curated for voice (echoes the player's wife's writing
    register per `feedback_her_voice`). ~15 words.
  - Thematic — drawn from a curated pool. V1 uses authored constants;
    post-V1 will source from lexicon (`vault.lexicon_terms()`) so the
    player composes from words SHE used in journal entries.
  - Wildcards — rare, expressive words. Sparse, lottery-feel.

Pool composition is RNG-driven and deterministic given the seed —
same seed → same pool, useful for replay testing.

V1 keeps lexicon sourcing as a stub (returns []) so this module
runs without a vault. The lexicon sourcing path lights up when
`vault.lexicon_terms()` accessor lands in a later content arc.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field


@dataclass(frozen=True)
class PoolConfig:
    """Authored magnet sources loaded from `config/reflective/magnets.json`."""
    connectives: tuple[str, ...] = ()
    thematic: tuple[str, ...] = ()
    wildcards: tuple[str, ...] = ()


# Module-global, populated by definitions.load_magnets_from_json().
_POOL_CONFIG: PoolConfig = PoolConfig()


def set_pool_config(config: PoolConfig) -> None:
    """Set the authored pool — called by definitions.py on JSON load.
    Tests with custom pools call this directly."""
    global _POOL_CONFIG
    _POOL_CONFIG = config


def get_pool_config() -> PoolConfig:
    return _POOL_CONFIG


def compose_pool(
    rng: random.Random,
    *,
    thematic_count: int = 12,
    wildcard_count: int = 3,
) -> list[str]:
    """Build a per-entry magnet tray.

    Returns: connectives + N sampled thematic words + K sampled
    wildcards. Order matters — the vector terminal tray UI uses list
    position for stable indexing across player input events.

    Sampling without replacement; if the source pool is smaller than
    the requested count, return what's available.
    """
    cfg = _POOL_CONFIG
    pool: list[str] = list(cfg.connectives)

    n_thematic = min(thematic_count, len(cfg.thematic))
    if n_thematic > 0:
        pool.extend(rng.sample(cfg.thematic, n_thematic))

    n_wild = min(wildcard_count, len(cfg.wildcards))
    if n_wild > 0:
        pool.extend(rng.sample(cfg.wildcards, n_wild))

    return pool
