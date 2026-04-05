"""
core/systems/roster_pool.py

RosterPool — least-recently-used rotation over a fixed pool of variants.

Like a Tetris piece bag or a baseball lineup: every variant in the pool
must appear once before any variant repeats. Creates the perception of
randomness without actual randomness, with maximum perceptual distance
between repeats.

Deterministic: same seed + same pool → same sequence. Reproducible.

Usage:
    pool = RosterPool(["a", "b", "c", "d"], seed=42)
    pool.next()  # "a" (or shuffled first, depending on seed)
    pool.next()  # "b"
    ...
    pool.next()  # "d"
    pool.next()  # back to start of rotation, a new cycle

Reusable substrate — buttress variants, light hues, creature spawns,
encounter verbs, ghost seeds all consume the same pattern.
"""

import random
from collections import deque


class RosterPool:
    """LRU rotation over a fixed pool. Deterministic per seed."""

    def __init__(self, variants, seed=0, shuffle_initial=True):
        """
        variants: list of any hashable items (strings, tuples, dicts)
        seed: deterministic seed for initial shuffle
        shuffle_initial: if True, randomize starting order; if False, use given order
        """
        if not variants:
            raise ValueError("RosterPool requires at least one variant")
        items = list(variants)
        if shuffle_initial:
            rng = random.Random(seed)
            rng.shuffle(items)
        self._queue = deque(items)
        self._cycle_count = 0
        self._total_picks = 0

    def next(self):
        """Pop the least-recently-seen variant, push it to the back of the queue."""
        variant = self._queue.popleft()
        self._queue.append(variant)
        self._total_picks += 1
        if self._total_picks % len(self._queue) == 0:
            self._cycle_count += 1
        return variant

    def peek(self):
        """Return the next variant without consuming it."""
        return self._queue[0]

    def __len__(self):
        return len(self._queue)

    @property
    def cycle_count(self):
        """How many full rotations through the pool have been completed."""
        return self._cycle_count

    @property
    def total_picks(self):
        """Total number of next() calls across all cycles."""
        return self._total_picks
