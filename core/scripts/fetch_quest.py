"""
core/scripts/fetch_quest.py

First scripted quest -- fetch end-to-end.

Pipeline:
    spawn target → create scenario → activate → encounter begins →
    move to target → pick up → stow → scenario completes →
    encounter resolves → provenance recorded.

Usage:
    from core.scripts.fetch_quest import fetch_quest
    result = fetch_quest(runner, pipeline)

    # Or via ScenarioRunner.run():
    from core.scripts.fetch_quest import make_fetch_script
    report = runner.run(make_fetch_script(pipeline))
"""

from __future__ import annotations


# -- Default fetch parameters --------------------------------------------------

TARGET_ASSET   = "TOOL_Minor_V1"
TARGET_ID      = "fetch_target_01"
TARGET_POS     = (3, 8, 0.5)
TARGET_OBJ     = {
    "id":       TARGET_ID,
    "weight":   0.5,
    "category": "tool",
    "tags":     ["precision_score", "crafting_time", "objects_inspected"],
}
RETURN_POS     = (0, 2, 0)
OBJECTIVE      = "Retrieve the tool and bring it back."


def fetch_quest(runner, pipeline, target_obj=None, target_pos=None) -> dict:
    """
    Execute a complete fetch quest through the runner.

    1. Prime fingerprint so encounters resonate
    2. Spawn the target object
    3. Create + activate fetch scenario
    4. Begin encounter with the target entity
    5. Move to target, pick up, stow
    6. Tick until scenario completes
    7. Resolve encounter
    8. Return result dict

    Parameters
    ----------
    runner   : ScenarioRunner instance
    pipeline : AvatarPipeline instance
    target_obj : dict -- override target object (optional)
    target_pos : tuple -- override target position (optional)

    Returns
    -------
    dict with scenario_id, state, provenance, target_id, encounter_result
    """
    obj = target_obj or dict(TARGET_OBJ)
    pos = target_pos or TARGET_POS
    tid = obj["id"]
    tags = obj.get("tags", [])

    # -- 1. Prime fingerprint so encounters can resonate -----------------------
    # Multiple records to build past resonance threshold (0.45)
    for _ in range(5):
        pipeline.fingerprint.record("precision_score", 0.9)
        pipeline.fingerprint.record("objects_inspected", 0.7)
    pipeline.refresh_blend()

    # -- 2. Spawn target -------------------------------------------------------
    runner.spawn(TARGET_ASSET, pos=pos, obj=obj)

    # -- 3. Create + activate fetch scenario -----------------------------------
    scenario_id = runner.se.create(
        "fetch",
        {
            "target_id":  tid,
            "return_pos": RETURN_POS,
            "objective":  OBJECTIVE,
        },
        win_fn=lambda: runner.inventory.get(tid) is not None,
    )
    runner.se.activate(scenario_id)

    # -- 4. Begin encounter with target entity ---------------------------------
    entity = {"id": tid, "tags": tags, "type": "object"}
    pipeline.encounter.begin(entity)
    verb = pipeline.encounter.dominant_verb()
    pipeline.encounter.choose(verb)

    # -- 5. Move to target, pick up, stow -------------------------------------
    runner.move_to(pos)
    runner.press("e")    # lift
    runner.press("e")    # stow
    runner.tick(seconds=0.5)

    # -- 6. Resolve encounter --------------------------------------------------
    encounter_result = pipeline.encounter.resolve()

    # -- 7. Record behavioral event to fingerprint -----------------------------
    pipeline.fingerprint.record("objects_inspected", 0.3)

    # -- 8. Build result -------------------------------------------------------
    state      = runner.se.get_state(scenario_id)
    provenance = runner.se.get_provenance(scenario_id)

    return {
        "scenario_id":      scenario_id,
        "state":            state.name if state else None,
        "provenance":       provenance,
        "target_id":        tid,
        "encounter_result": encounter_result,
    }


def make_fetch_script(pipeline, target_obj=None, target_pos=None):
    """
    Return a callable for ScenarioRunner.run().

    Usage:
        script = make_fetch_script(pipeline)
        report = runner.run(script)
    """
    def script(runner):
        fetch_quest(runner, pipeline, target_obj, target_pos)
    return script
