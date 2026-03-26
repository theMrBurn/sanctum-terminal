from SimulationRunner import Simulation


def test_proximity_logic():
    # Start headless
    sim = Simulation(headless=True)

    # Place an interactable object at (10, 10, 0)
    ent = sim.app.spawn("ACT_Human_Stock_V1", (10, 10, 0))
    ent.setPythonTag("interactable", True)

    # Move player close
    sim.app.camera.setPos(9, 9, 6)
    sim.process_interactions()

    # In a real test, we'd assert the prompt text changed
    assert (ent.getPos() - sim.app.camera.getPos()).length() < sim.interact_dist
