"""World Blender V0 — synthesis layer that composes lexicon + character
substrate into personalized in-game artifacts.

Per `design_world_blender`: the Blender is a *consumer* layer. It pulls
from existing substrates (lexicon, character_sheet, biome registry,
chronometer, tension) and produces CharacterSheets / encounter-shaped
dicts. It does NOT invent new primitive types.

V0 scope: rules-based composition with a stubbed LexiconClient. When the
lexicon J3+ endpoint ships, swap LexiconStub for a vault-backed client
without touching the Blender's compose logic. Same input contract.

Hard rules from `design_wont_tolerate`:
  - Voice phrases are returned VERBATIM. No paraphrasing, no smoothing.
  - Empty lexicon falls back to neutral primitives, not invented filler.
  - No LLM, no network, no scraping.
  - No degrading framings of real people from the journal.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Protocol

from core.systems.character_classes import CLASSES
from core.systems.character_sheet import (
    CharacterSheet,
    ClassEntry,
    generate_character_sheet,
)


@dataclass(frozen=True)
class LexiconTerm:
    """Minimal shape the Blender consumes. Real lexicon rows have more
    fields (lemma, ngram_size, last_seen_at, co_occurring) but the
    Blender only needs term + category + snippet + occurrences for V0
    composition. Future versions can pull more without breaking callers."""
    term: str
    category: str | None = None
    occurrences: int = 1
    snippet: str | None = None  # verbatim surface form for voice echo


class LexiconClient(Protocol):
    """The API surface the Blender consumes. Swap implementations:
       - LexiconStub for tests + pre-J3 development
       - VaultLexiconClient (future) for live brain integration after J3+ lands
    """

    def query(self, category: str | None = None) -> list[LexiconTerm]: ...

    def similar(self, word: str, k: int = 8) -> list[str]: ...

    def voice_phrases(self, min_occurrences: int = 2) -> list[str]: ...


class LexiconStub:
    """Empty by default; tests inject fixtures.

    No hardcoded cultural / personal terms — per `design_wont_tolerate` #5
    cultural neutrality and `design_lexicon_architecture`. The stub is
    a transport for fixture data only, never a source of synthetic content.
    """

    def __init__(
        self,
        terms: list[LexiconTerm] | None = None,
        voice: list[str] | None = None,
        similar_map: dict[str, list[str]] | None = None,
    ) -> None:
        self._terms: list[LexiconTerm] = list(terms or [])
        self._voice: list[str] = list(voice or [])
        self._similar: dict[str, list[str]] = dict(similar_map or {})

    def query(self, category: str | None = None) -> list[LexiconTerm]:
        if category is None:
            return list(self._terms)
        return [t for t in self._terms if t.category == category]

    def similar(self, word: str, k: int = 8) -> list[str]:
        return self._similar.get(word, [])[:k]

    def voice_phrases(self, min_occurrences: int = 2) -> list[str]:
        return list(self._voice)


# ── Biome → things config ──────────────────────────────────────────────
#
# Per `design_cohesive_illusion` + `design_config_as_code`: every biome
# uses the same code path; this config table differentiates. Add a new
# biome by adding a row. Workroom keeps the curated gallery via per_tile=0.

BIOME_THING_CONFIG: dict[str, dict[str, Any]] = {
    "cavern":   {"tags": ["carcosa", "tolkien"],
                 "exclude_tags": ["outdoor"],
                 "per_tile": 2},
    # Outdoor = PNW forest as of 2026-05-17. Doug fir / sword fern /
    # moss as the library anchor; greenhouse layer logs any unfilled
    # demand. Excludes carcosa (cavern's mythos register) so a stray
    # tag overlap can't leak fungal/bone things into the forest.
    "outdoor":  {"tags": ["pnw"],
                 "exclude_tags": ["carcosa"],
                 "per_tile": 3},
    "hub":      {"tags": ["moebius"],
                 "exclude_tags": [],
                 "per_tile": 1},
    "workroom": {"tags": [],
                 "exclude_tags": [],
                 "per_tile": 0},
}

# Unknown biomes fall back to this — empty filter, no things. Forces an
# explicit config row when new biomes are added rather than silent default
# behavior.
BIOME_THING_CONFIG_DEFAULT: dict[str, Any] = {
    "tags": [], "exclude_tags": [], "per_tile": 0,
}


# Stamp placement policy per biome — same shape as BIOME_THING_CONFIG,
# but `tile_chance` (float 0..1) replaces `per_tile` because
# architecture is rare/intentional, not density scatter. A stamp is a
# multi-meter assembly (bridge, ladder, staircase, doorway).
#
# Per the 2026-05-17 "stamps as data" PR. Greenhouse path is shared
# with things — unfilled stamp demand records the same way.
BIOME_STAMP_CONFIG: dict[str, dict[str, Any]] = {
    "outdoor":  {"tags": ["pnw", "architecture"],
                 "exclude_tags": ["carcosa"],
                 "tile_chance": 0.10},
    "cavern":   {"tags": ["architecture"],
                 "exclude_tags": ["pnw"],
                 "tile_chance": 0.0},     # no stamps for cavern yet
    "hub":      {"tags": [], "exclude_tags": [], "tile_chance": 0.0},
    "workroom": {"tags": [], "exclude_tags": [], "tile_chance": 0.0},
}

BIOME_STAMP_CONFIG_DEFAULT: dict[str, Any] = {
    "tags": [], "exclude_tags": [], "tile_chance": 0.0,
}


# ── Role → class mapping ──────────────────────────────────────────────


# Maps Blender role names to character classes from `core.systems.character_classes`.
# Roles are gameplay-meaningful labels ("vendor", "companion") that map to
# class definitions ("rogue", "monk") which carry the actual stats + abilities.
# Unknown roles fall back to "rogue" — the most generic class.
ROLE_TO_CLASS: dict[str, str] = {
    "watcher": "watcher",
    "scout": "scout",
    "scholar": "scholar",
    "vendor": "rogue",
    "companion": "monk",
    "cipher": "philosopher",
}


def _class_for_role(role: str) -> str:
    return ROLE_TO_CLASS.get(role.lower(), "rogue")


# ── Blender ───────────────────────────────────────────────────────────


@dataclass
class WorldBlender:
    """Composes substrates into per-session artifacts.

    Pure data + lexicon queries. Deterministic when seeded.
    """

    lexicon: LexiconClient = field(default_factory=LexiconStub)

    def npc_for_role(
        self,
        role: str,
        *,
        biome: str | None = None,
        seed: int | None = None,
    ) -> CharacterSheet:
        """Synthesize an NPC CharacterSheet for `role`.

        Composition:
          - Name from lexicon.query(category="PERSON") if any; otherwise
            a role-based neutral default ("Watcher", "Scout", ...). Snippet
            wins over normalized term so her capitalization survives.
          - Class history from ROLE_TO_CLASS mapping.
          - Age sampled deterministically from `seed`.
          - Stats + abilities derive from the class preset (no override).

        Per `design_wont_tolerate`: never invents synthetic personal names
        when the lexicon is empty — falls back to neutral role labels.
        """
        rng = random.Random(seed)

        person_terms = self.lexicon.query(category="PERSON")
        if person_terms:
            chosen = rng.choice(person_terms)
            # Snippet preserves her exact surface form per the voice contract.
            name = chosen.snippet if chosen.snippet else chosen.term
        else:
            name = role.title()  # neutral fallback

        class_name = _class_for_role(role)
        # NPC age: rough archetype-appropriate band. Not fed back to the
        # player as a literal stat; just shapes class progression depth.
        age = rng.randint(30, 80)
        history = [ClassEntry(class_name, levels=age, started_at_age=0)]

        return generate_character_sheet(
            name=name,
            birthday=(1, 1),  # NPC placeholder; not surfaced in HUD
            age=age,
            class_history=history,
        )

    def voice_lines_for_npc(
        self,
        role: str,
        n: int = 3,
        min_occurrences: int = 1,
    ) -> list[str]:
        """Return up to `n` verbatim voice phrases for an NPC's dialog options.

        Per `design_wont_tolerate` #1 + #9: phrases are returned VERBATIM
        from the lexicon. Never paraphrase, smooth, or "improve" them. If
        no voice data is available, returns []; the encounter system uses
        neutral fallbacks rather than synthesizing voice.
        """
        phrases = self.lexicon.voice_phrases(min_occurrences=min_occurrences)
        return phrases[:n]

    def encounter_template(
        self,
        *,
        biome: str,
        tension: str = "open",
        role: str = "watcher",
        seed: int | None = None,
    ) -> dict[str, Any]:
        """Compose an encounter shape: NPC + voice options + biome flavor.

        Returns a dict matching the brain's encounter manifest shape.
        Action options come from the existing `design_orb_encounters`
        substrate when available; voice phrases are layered on as
        verbatim dialog lines.
        """
        npc = self.npc_for_role(role, biome=biome, seed=seed)
        voice = self.voice_lines_for_npc(role, n=3)

        return {
            "name": npc.name,
            "kind": role,
            "biome": biome,
            "tension": tension,
            # action_options shape mirrors the existing encounter system
            # (string list of action names). Voice phrases ride alongside
            # so the renderer can echo them as the labels OR fall back to
            # action names directly.
            "action_options": ["parley", "observe", "leave"],
            "voice_phrases": voice,
            "npc_sheet": {
                "name": npc.name,
                "age": npc.age,
                "class_history": [
                    {"name": e.name, "levels": e.levels} for e in npc.class_history
                ],
            },
        }

    def compose_library_kind(
        self,
        name: str,
        *,
        texture_name: str | None = None,
    ) -> dict[str, Any] | None:
        """Compose a renderable artifact from an image_scan library entry.

        Reads `library/geometry/<name>.json` for the composition,
        optionally pulls a named texture's bundle (texture path + noise +
        ramp), and produces a flat dict the brain manifest can carry.

        Returns None if no geometry by that name. The texture arg is
        independent of the geometry — a scarecrow geometry can be
        rendered with a flannel texture, or a hay_fibers texture, or
        none at all. Caller picks.
        """
        from core.systems import scan_library                  # local — avoids cycle

        geo = scan_library.get_geometry(name)
        if geo is None:
            return None

        out: dict[str, Any] = {
            "kind_name":      geo.get("name", name),
            "anchor":         geo.get("anchor"),
            "subparts":       geo.get("subparts", []),
            "source_image":   geo.get("source_image"),
        }

        if texture_name is not None:
            bundle = scan_library.get_texture_bundle(texture_name)
            if bundle is not None:
                out["texture"] = bundle

        return out

    def library_kinds(self) -> list[str]:
        """All geometry names available in the library."""
        from core.systems import scan_library
        return scan_library.list_geometries()

    # ── Thing library arm (spec 18 successor) ───────────────────

    def pick_thing(
        self,
        include_tags: list[str] | None = None,
        exclude_tags: list[str] | None = None,
        *,
        match_all: bool = False,
        seed: int | None = None,
    ) -> Any | None:
        """Pick ONE thing matching the tag query. Returns a Thing
        dataclass or None if nothing matches. Deterministic when
        seeded.

        Voice-of-restraint per `design_wont_tolerate`: returns the
        thing AS-IS, no synthetic filler. Caller decides what to do
        with None.
        """
        from core.systems import thing_library

        candidates = thing_library.find_by_tags(
            include=include_tags,
            exclude=exclude_tags,
            match_all=match_all,
        )
        if not candidates:
            return None
        rng = random.Random(seed)
        return rng.choice(candidates)

    def things_for_biome(
        self,
        biome: str,
        *,
        tension: str = "open",
        count: int = 3,
        seed: int | None = None,
    ) -> list[Any]:
        """Pick `count` things compatible with this biome's mood.

        Maps biome → tag filter. Currently a small lookup; can grow
        into a registry in `core/systems/biome_data.py` later.
        """
        cfg = BIOME_THING_CONFIG.get(biome, BIOME_THING_CONFIG_DEFAULT)
        tags = cfg.get("tags", []) or []
        exclude_tags = cfg.get("exclude_tags", []) or []

        from core.systems import thing_library
        candidates = thing_library.find_by_tags(
            include=tags or None,
            exclude=exclude_tags or None,
        )
        if not candidates:
            # Fallback — return any decorative things if biome-tag filter empty
            candidates = thing_library.find_by_tags(
                include=["decorative", "prop"],
            )
        if not candidates:
            return []
        rng = random.Random(seed)
        n = min(count, len(candidates))
        return rng.sample(candidates, n)

    def things_for_tile(
        self,
        biome: str,
        tile_x: int,
        tile_y: int,
        base_seed: int = 0,
    ) -> tuple[list[Any], list[list[str]]]:
        """Per-tile pick driven by BIOME_THING_CONFIG.

        Returns (filled_things, unfilled_tag_profiles). The caller
        spawns each filled thing as a normal entity; each unfilled
        slot becomes a greenhouse demand row + a placeholder seed.

        Deterministic per (tile_x, tile_y, base_seed): re-visiting
        the same tile produces the same picks (per
        `design_path_memory`).
        """
        cfg = BIOME_THING_CONFIG.get(biome, BIOME_THING_CONFIG_DEFAULT)
        tags = cfg.get("tags", []) or []
        exclude_tags = cfg.get("exclude_tags", []) or []
        per_tile = int(cfg.get("per_tile", 0))

        if per_tile <= 0:
            return [], []

        from core.systems import thing_library
        candidates = thing_library.find_by_tags(
            include=tags or None,
            exclude=exclude_tags or None,
        )
        if not candidates:
            # Whole tile is unfilled — every slot demands the biome's tags.
            return [], [list(tags) for _ in range(per_tile)]

        # Deterministic per-tile RNG
        tile_seed = hash((biome, int(tile_x), int(tile_y), int(base_seed)))
        rng = random.Random(tile_seed)

        if len(candidates) >= per_tile:
            picks = rng.sample(candidates, per_tile)
            return picks, []
        # Partial fill — return what we have, log the rest as demand
        picks = list(candidates)
        rng.shuffle(picks)
        unfilled = per_tile - len(picks)
        unfilled_profiles = [list(tags) for _ in range(unfilled)]
        return picks, unfilled_profiles


    def stamps_for_tile(
        self,
        biome: str,
        tile_x: int,
        tile_y: int,
        base_seed: int = 0,
    ) -> tuple[list[Any], list[list[str]]]:
        """Per-tile stamp pick — analogous to things_for_tile but
        uses BIOME_STAMP_CONFIG and the stamps library.

        Returns (filled_stamps, unfilled_tag_profiles). Most tiles
        return ([], []) — `tile_chance` gates whether this tile gets
        a stamp at all. When it does, a single stamp is picked.

        Deterministic per (tile_x, tile_y, base_seed) — the gate, the
        pick, and the placement all share the seed lineage.
        """
        cfg = BIOME_STAMP_CONFIG.get(biome, BIOME_STAMP_CONFIG_DEFAULT)
        tags = cfg.get("tags", []) or []
        exclude_tags = cfg.get("exclude_tags", []) or []
        tile_chance = float(cfg.get("tile_chance", 0.0))

        if tile_chance <= 0.0:
            return [], []

        # Deterministic per-tile gate
        tile_seed = hash((biome, "stamp", int(tile_x), int(tile_y),
                          int(base_seed)))
        rng = random.Random(tile_seed)
        if rng.random() >= tile_chance:
            return [], []

        from core.systems import thing_library
        candidates = thing_library.find_stamps_by_tags(
            include=tags or None,
            exclude=exclude_tags or None,
        )
        if not candidates:
            # Tile won the gate but library has nothing — record one
            # greenhouse demand row so authoring sees the gap.
            return [], [list(tags)]

        return [rng.choice(candidates)], []


# Convenience factory — single Blender instance with empty stub. Tests and
# brain code can either import this default or build their own with a
# specific LexiconClient injected.
def default_blender() -> WorldBlender:
    return WorldBlender(lexicon=LexiconStub())
