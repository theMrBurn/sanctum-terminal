"""Quest state container — in-memory ledger of available / active / completed.

Per `project_async_quest_refactor` PR 1.2: lives on BrainWorld for now.
PR 2 (V3 save schema) promotes the relevant lists onto PlayerState so
they persist across restart. Until then, quest state is reset each
brain boot — fine for UAT; loses no real player progress because the
substrate isn't player-facing yet.

The four pieces:

  available  — quest ids the player has been offered (seeded from biome
               binding at world init). Toggling moves an id to active.
  active     — quest ids the player is currently pursuing. Skyrim-style:
               all broadcast on HUD, no tracked/untracked split (per
               `project_async_quest_refactor`).
  completed  — quest ids the player has finished. Append-only history.
  progress   — id → mutable per-quest progress dict. The predicate
               accumulates state here across ticks (e.g., kill counts,
               element sets). Cleared when quest completes.

Toggle semantics: `journal_toggle_quest` moves between available ↔
active. Completed quests cannot be re-activated via the toggle (the
journal flags them as historical).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class QuestState:
    available: list[str] = field(default_factory=list)
    active: list[str] = field(default_factory=list)
    completed: list[str] = field(default_factory=list)
    progress: dict[str, dict] = field(default_factory=dict)

    def toggle_active(self, quest_id: str) -> str:
        """Move a quest between available ↔ active. Returns the new state
        ("active" | "available" | "completed" | "unknown"). Completed
        quests are read-only — the toggle is a no-op."""
        if quest_id in self.completed:
            return "completed"
        if quest_id in self.active:
            self.active.remove(quest_id)
            if quest_id not in self.available:
                self.available.append(quest_id)
            self.progress.pop(quest_id, None)
            return "available"
        if quest_id in self.available:
            self.available.remove(quest_id)
            self.active.append(quest_id)
            self.progress.setdefault(quest_id, {})
            return "active"
        return "unknown"

    def complete(self, quest_id: str) -> None:
        """Move a quest from active → completed. Clears progress."""
        if quest_id in self.active:
            self.active.remove(quest_id)
        if quest_id not in self.completed:
            self.completed.append(quest_id)
        self.progress.pop(quest_id, None)
