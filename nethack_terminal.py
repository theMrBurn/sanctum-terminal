"""nethack_terminal.py — entry point for the NetHack make-brain.

Standalone curses app (PR 3+).  PR 1 ships only the splash screen and
substrate boot path (vault profile bootstrap, registry registration,
run lifecycle hook), so smoke tests can verify the wiring without a
playable game loop.

Spec: `.claude/feature/feat_make-brain-nethack.md`.

Usage:
    PYTHONPATH=. ./.venv/bin/python nethack_terminal.py
    make brain-nethack
"""
from __future__ import annotations

import sys

from core.systems.make_brains import nethack
from core.vault import vault as Vault


SPLASH = r"""
                Sanctum NetHack — V1 PR 1 (scaffolding)

                  -------       --------          --------
                  |.....|       |......|          |......|
                  |.....+#######+......|          |......|
                  |..@..|       |......+##########+......|
                  |.....|       |......|          |......|
                  |.....|       --------          --------
                  -------

                Make-brain instance : nethack
                Profile             : vanilla
                Vault path          : data/vault.db

                The dungeon is not yet generated.
                The monsters are not yet stirring.
                Game loop lands in PR 2-8.

                Press Enter to leave the dungeon entrance.
"""


def boot() -> dict:
    """Boot the substrate: instantiate vault, register the make-brain,
    open a run row, return a snapshot of identity + run state.

    Pure side-effect-free description of what the splash binds to —
    used by tests to assert the wiring without launching a real REPL.
    """
    vault = Vault()
    spec = nethack.activate(vault)
    handler = spec.handler
    handler.start_run()
    snapshot = handler.manifest_keys()
    return {
        "instance_id":     spec.instance_id,
        "entry_point":     spec.entry_point,
        "default_profile": spec.default_profile,
        "active_profile":  handler.active_profile,
        "run_id":          handler._run_id,
        "manifest":        snapshot,
        "handler":         handler,
    }


def main(argv: list[str] | None = None) -> int:
    state = boot()
    print(SPLASH)
    print(f"  instance_id : {state['instance_id']}")
    print(f"  entry_point : {state['entry_point']}")
    print(f"  active      : {state['active_profile']}")
    print(f"  run_id      : {state['run_id']}")
    print()

    handler = state["handler"]
    try:
        # Wait for any input. EOF (e.g. piped stdin in CI) exits cleanly.
        input("                Press Enter to quit > ")
    except EOFError:
        pass
    finally:
        handler.end_run(terminal_state="quit")
    print("                Farewell, adventurer.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
