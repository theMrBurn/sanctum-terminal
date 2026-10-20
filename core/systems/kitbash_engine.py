"""
core/systems/kitbash_engine.py

KitbashEngine -- renderer-agnostic assembly CORE for the kitbash / greeble
procedural-asset subsystem (spec_kitbash_greeble.md §1).

Peer to InteractionEngine / EncounterEngine: a plain class, no base class,
no registry. PURE LOGIC -- NO renderer, NO bpy import -- fully unit-testable
headless. The two backends (wireframe LIVE, Blender CAPABILITY) consume the
`AssemblyResult` this produces; they are Personas B / D and live elsewhere.

Model
-----
    Base    declares named attach points  Socket(name, socket_type, scale_class)
    Part    declares socket_types (set) + scale_class + category (kit)
    CSP     per socket, a part fits iff  socket_type ∈ part.socket_types
                                     AND scale classes are compatible
    Select  PURE function of a passed-in signal state dict + a seed:
              high entropy  -> bias cross-category "scavenged / mismatched"
              low / stable  -> bias uniform same-category (same-kit)
            Any tie-break RNG is seeded from (signal, seed) -- NO bare random().

    -> AssemblyResult { base_id, bindings=[(socket_name, part_id)], signal_snapshot }

The assembly ledger (reproducible provenance_hash) lives in core/vault.py
(`assemblies` table) -- one ledger, both backends. This module never touches
the DB; vault.record_assembly() duck-types the AssemblyResult.

Determinism is the acceptance bar: fixed base + fixed signal snapshot + fixed
parts table -> identical AssemblyResult, reproducible from the ledger row alone.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from typing import Optional


# -- Constants (no hardcoded tunables -- AGENTS.md line 18) --------------------

# Ordered scale-class bands. Index in this tuple is the scale magnitude; two
# classes are compatible iff their indices differ by <= SCALE_CLASS_TOLERANCE.
# NOTE (Persona-A deferral): AGENTS.md line 19 + spec §7 gesture at
# config/kind_config.json as the single source for scale/category recipes.
# Building that config loader is out of Persona-A scope; these live as named
# consts here per the task, ready to migrate to config when a backend needs it.
SCALE_CLASSES        = ("tiny", "small", "medium", "large", "huge")
SCALE_CLASS_TOLERANCE = 1        # bands of slack allowed between socket & part

# Selection: at/above this entropy the assembly biases toward cross-category
# "scavenged / mismatched" parts; below it, toward a uniform same-kit look.
# Read from signal_state["entropy"] (0.0-1.0). See §3.
ENTROPY_THRESHOLD = 0.5
DEFAULT_ENTROPY   = 0.0          # stable when the signal omits entropy

# The signal key selection actually consumes. Everything else in the snapshot
# (e.g. "atmosphere") is RECORDED for provenance but not read here -- Persona C
# wires additional consumers by hand.
ENTROPY_KEY = "entropy"

DEFAULT_SEED = 0


# -- Value types (backend-neutral tuples) -------------------------------------

@dataclass(frozen=True)
class Socket:
    """A named attach point on a base. Backend-neutral: a wireframe base names
    these in data; a Blender base carries them as empties / vertex groups that
    the Blender backend normalizes to this same tuple."""
    name:        str
    socket_type: str
    scale_class: str


@dataclass(frozen=True)
class Base:
    """A base is an id plus its ordered named attach points."""
    base_id: str
    sockets: tuple = ()          # tuple[Socket, ...]


@dataclass(frozen=True)
class Part:
    """A greeble part. `socket_types` is the set of socket types it can attach
    to; `scale_class` is its own band; `category` names its kit (drives the
    same-kit vs scavenged selection bias)."""
    part_id:      str
    socket_types: frozenset      # frozenset[str]
    scale_class:  str
    category:     str = ""


@dataclass
class AssemblyResult:
    """Renderer-agnostic result of one assembly. `bindings` is sorted
    deterministically by socket name. `signal_snapshot` must be
    JSON-serializable (it is both hashed and stored as json in the ledger)."""
    base_id:         str
    bindings:        list = field(default_factory=list)   # list[(socket_name, part_id)]
    signal_snapshot: dict = field(default_factory=dict)


# -- Engine -------------------------------------------------------------------

class KitbashEngine:
    """
    Renderer-agnostic assembly core. Pure logic; no renderer, no bpy.

    Usage
    -----
        engine = KitbashEngine()
        result = engine.assemble(base, parts, signal_state, seed=0)

    `parts` is the candidate parts table passed in by the caller (a fixture in
    tests, the wireframe registry in Persona B). `signal_state` is the consumed
    Entropy/Atmosphere snapshot passed in by Persona C -- the engine RECEIVES
    it, it does not fetch it.
    """

    # -- CSP -------------------------------------------------------------------

    def _scale_index(self, scale_class: str) -> int:
        """Position of a scale class in the ordered bands. Unknown classes sort
        past the end so they only ever match themselves within tolerance."""
        try:
            return SCALE_CLASSES.index(scale_class)
        except ValueError:
            return len(SCALE_CLASSES)

    def _scale_compatible(self, part: Part, socket: Socket) -> bool:
        return abs(
            self._scale_index(part.scale_class) - self._scale_index(socket.scale_class)
        ) <= SCALE_CLASS_TOLERANCE

    def _compatible(self, part: Part, socket: Socket) -> bool:
        """A part fits a socket iff the socket's type is one the part accepts
        AND their scale classes are within tolerance. Rejects otherwise."""
        return (
            socket.socket_type in part.socket_types
            and self._scale_compatible(part, socket)
        )

    def _candidates(self, socket: Socket, parts) -> list:
        """Compatible parts for a socket, sorted by part_id for determinism."""
        return sorted(
            (p for p in parts if self._compatible(p, socket)),
            key=lambda p: p.part_id,
        )

    # -- Selection -------------------------------------------------------------

    @staticmethod
    def _rng(signal_state: dict, seed: int) -> random.Random:
        """Deterministic RNG seeded from (signal, seed). NO bare random()."""
        material = f"{seed}:{json.dumps(signal_state, sort_keys=True, default=str)}"
        digest   = hashlib.sha256(material.encode("utf-8")).hexdigest()
        return random.Random(int(digest, 16))

    def _anchor_category(self, base: Base, parts, rng: random.Random) -> Optional[str]:
        """Stable-mode kit anchor: the category with the most compatible
        candidates across all sockets (the dominant kit), tie-broken by the
        seeded RNG so it stays deterministic."""
        counts: dict = {}
        for socket in base.sockets:
            for p in self._candidates(socket, parts):
                counts[p.category] = counts.get(p.category, 0) + 1
        if not counts:
            return None
        top = max(counts.values())
        winners = sorted(c for c, n in counts.items() if n == top)
        return rng.choice(winners)

    def assemble(
        self,
        base: Base,
        parts,
        signal_state: Optional[dict] = None,
        seed: int = DEFAULT_SEED,
    ) -> AssemblyResult:
        """
        Assemble greebles onto `base`, one part per socket that has at least
        one compatible candidate.

        Behavior when a socket has NO compatible part: it is SKIPPED (omitted
        from bindings -- partial assembly). This keeps the result deterministic
        and is an interface fact backends rely on.

        Selection is a pure function of `signal_state` + `seed`:
          entropy >= ENTROPY_THRESHOLD -> prefer a not-yet-used category per
                                          socket (scavenged / mismatched);
          entropy <  ENTROPY_THRESHOLD -> prefer the anchor kit's category
                                          (uniform same-kit).
        The seeded RNG only breaks ties within the chosen candidate pool.

        Returns an AssemblyResult with bindings sorted by socket name.
        """
        signal_state = dict(signal_state or {})
        rng      = self._rng(signal_state, seed)
        entropy  = signal_state.get(ENTROPY_KEY, DEFAULT_ENTROPY)
        high     = entropy >= ENTROPY_THRESHOLD

        anchor   = None if high else self._anchor_category(base, parts, rng)
        used_categories: set = set()
        bindings: list = []

        # Deterministic socket order: by name.
        for socket in sorted(base.sockets, key=lambda s: s.name):
            candidates = self._candidates(socket, parts)
            if not candidates:
                continue

            if high:
                # Scavenged: restrict to not-yet-used categories when possible,
                # so the assembly spreads across kits.
                pool = [c for c in candidates if c.category not in used_categories]
                if not pool:
                    pool = candidates
            else:
                # Same-kit: restrict to the anchor category when possible.
                pool = [c for c in candidates if c.category == anchor]
                if not pool:
                    pool = candidates

            choice = rng.choice(pool)
            used_categories.add(choice.category)
            bindings.append((socket.name, choice.part_id))

        bindings.sort(key=lambda b: b[0])
        return AssemblyResult(
            base_id=base.base_id,
            bindings=bindings,
            signal_snapshot=signal_state,
        )
