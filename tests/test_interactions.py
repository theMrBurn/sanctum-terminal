from SimulationRunner import Simulation


def test_proximity_logic():
    sim = Simulation(headless=True)

    ent = sim.app.spawn("ACT_Human_Stock_V1", (10, 10, 0))
    ent.setPythonTag("interactable", True)

    sim.app.camera.setPos(9, 9, 6)
    sim.process_interactions()

    ent_pos = ent.getPos()
    cam_pos = sim.app.camera.getPos()
    dist_2d = ((ent_pos.x - cam_pos.x) ** 2 + (ent_pos.y - cam_pos.y) ** 2) ** 0.5
    assert dist_2d < sim.interact_dist
