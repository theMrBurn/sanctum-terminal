from SimulationRunner import Simulation
from core.systems.inventory import Inventory


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


# -- PickupSystem --------------------------------------------------------------
# TDD: these tests define the contract. Run make test -> Red.
# Then wire core/systems/pickup_system.py -> Green.
#
# The Philosopher Monk lifts a book.
# First [E]: object detaches from world, floats held.
# Second [E]: flies into inventory. World notices.
# [G]: returns to world_pos. No punishment.

class TestPickupSystemContract:

    def _make_sim_with_item(self):
        """Headless sim, one pickupable object near camera."""
        sim = Simulation(headless=True)
        node = sim.app.spawn("TOOL_Minor_V1", (1, 0, 0))
        node.setPythonTag("pickupable", True)
        node.setPythonTag("obj", {
            "id":       "tool_minor_01",
            "name":     "Minor Tool",
            "weight":   0.5,
            "category": "tool",
        })
        sim.app.camera.setPos(0, 0, 6)
        return sim, node

    def test_pickup_system_importable(self):
        """PickupSystem exists and can be instantiated."""
        from core.systems.pickup_system import PickupSystem
        assert PickupSystem is not None

    def test_pickup_state_idle_on_init(self):
        from core.systems.pickup_system import PickupSystem, PickupState
        from core.systems.inventory import Inventory
        sim, node = self._make_sim_with_item()
        inv = Inventory()
        ps  = PickupSystem(
            camera         = sim.app.camera,
            inventory      = inv,
            get_nearest_fn = lambda: {"obj": node.getPythonTag("obj"), "node": node},
        )
        assert ps.state is PickupState.IDLE

    def test_first_e_lifts_object(self):
        """E press while near object -> HELD state, node reparented to camera."""
        from core.systems.pickup_system import PickupSystem, PickupState
        sim, node = self._make_sim_with_item()
        inv = Inventory()
        ps  = PickupSystem(
            camera         = sim.app.camera,
            inventory      = inv,
            get_nearest_fn = lambda: {"obj": node.getPythonTag("obj"), "node": node},
        )
        result = ps.on_e_pressed()
        assert result == "lifted"
        assert ps.state is PickupState.HELD
        assert node.getParent() == sim.app.camera

    def test_held_object_has_no_world_position(self):
        """Once held, node is camera-relative -- world pos is HOLD_OFFSET."""
        from core.systems.pickup_system import PickupSystem, HOLD_OFFSET
        sim, node = self._make_sim_with_item()
        inv = Inventory()
        ps  = PickupSystem(
            camera         = sim.app.camera,
            inventory      = inv,
            get_nearest_fn = lambda: {"obj": node.getPythonTag("obj"), "node": node},
        )
        ps.on_e_pressed()
        pos = node.getPos()
        assert abs(pos.x - HOLD_OFFSET[0]) < 0.01
        assert abs(pos.y - HOLD_OFFSET[1]) < 0.01
        assert abs(pos.z - HOLD_OFFSET[2]) < 0.01

    def test_second_e_begins_stow(self):
        """Second E -> STOWING state."""
        from core.systems.pickup_system import PickupSystem, PickupState
        sim, node = self._make_sim_with_item()
        inv = Inventory()
        ps  = PickupSystem(
            camera         = sim.app.camera,
            inventory      = inv,
            get_nearest_fn = lambda: {"obj": node.getPythonTag("obj"), "node": node},
        )
        ps.on_e_pressed()
        result = ps.on_e_pressed()
        assert result == "stowing"
        assert ps.state is PickupState.STOWING

    def test_stow_completes_into_inventory(self):
        """After tween completes, item is in inventory and node is hidden."""
        from core.systems.pickup_system import PickupSystem, STOW_DURATION
        sim, node = self._make_sim_with_item()
        inv = Inventory()
        ps  = PickupSystem(
            camera         = sim.app.camera,
            inventory      = inv,
            get_nearest_fn = lambda: {"obj": node.getPythonTag("obj"), "node": node},
        )
        ps.on_e_pressed()
        ps.on_e_pressed()
        total = 0.0
        while total < STOW_DURATION + 0.05:
            ps.update(0.016)
            total += 0.016
        assert inv.count() == 1
        assert inv.get("tool_minor_01") is not None
        assert node.isHidden()

    def test_drop_returns_object_to_world(self):
        """[G] while held -> IDLE, node back at original world pos."""
        from core.systems.pickup_system import PickupSystem, PickupState
        sim, node = self._make_sim_with_item()
        original_pos = node.getPos(sim.app.render)
        inv = Inventory()
        ps  = PickupSystem(
            camera         = sim.app.camera,
            inventory      = inv,
            get_nearest_fn = lambda: {"obj": node.getPythonTag("obj"), "node": node},
        )
        ps.on_e_pressed()
        result = ps.on_drop_pressed()
        assert result == "dropped"
        assert ps.state is PickupState.IDLE
        restored = node.getPos(sim.app.render)
        assert abs(restored.x - original_pos.x) < 0.01
        assert abs(restored.y - original_pos.y) < 0.01

    def test_nothing_nearby_returns_status(self):
        """E with nothing in range -> nothing_nearby, stays IDLE."""
        from core.systems.pickup_system import PickupSystem, PickupState
        sim, node = self._make_sim_with_item()
        inv = Inventory()
        ps  = PickupSystem(
            camera         = sim.app.camera,
            inventory      = inv,
            get_nearest_fn = lambda: None,
        )
        result = ps.on_e_pressed()
        assert result == "nothing_nearby"
        assert ps.state is PickupState.IDLE

    def test_inventory_full_blocks_lift(self):
        """Cannot lift when inventory is at capacity."""
        from core.systems.pickup_system import PickupSystem, PickupState
        sim, node = self._make_sim_with_item()
        inv = Inventory()
        for i in range(8):
            inv.pickup({"id": f"filler_{i}", "name": f"Filler {i}", "weight": 0.5})
        ps  = PickupSystem(
            camera         = sim.app.camera,
            inventory      = inv,
            get_nearest_fn = lambda: {"obj": node.getPythonTag("obj"), "node": node},
        )
        result = ps.on_e_pressed()
        assert result == "inventory_full"
        assert ps.state is PickupState.IDLE

    def test_e_during_stow_is_ignored(self):
        """Extra E presses during stow tween do nothing."""
        from core.systems.pickup_system import PickupSystem, PickupState
        sim, node = self._make_sim_with_item()
        inv = Inventory()
        ps  = PickupSystem(
            camera         = sim.app.camera,
            inventory      = inv,
            get_nearest_fn = lambda: {"obj": node.getPythonTag("obj"), "node": node},
        )
        ps.on_e_pressed()
        ps.on_e_pressed()
        result = ps.on_e_pressed()
        assert result == "busy"
        assert ps.state is PickupState.STOWING

    def test_weight_blocks_stow_not_lift(self):
        """
        Item lifted fine, then inventory fills externally before second E.
        Stow returns inventory_full. Item stays held -- not lost.
        """
        from core.systems.pickup_system import PickupSystem, PickupState
        sim, node = self._make_sim_with_item()
        inv = Inventory(max_slots=8, max_weight=1.0)
        ps  = PickupSystem(
            camera         = sim.app.camera,
            inventory      = inv,
            get_nearest_fn = lambda: {"obj": node.getPythonTag("obj"), "node": node},
        )
        ps.on_e_pressed()
        inv.pickup({"id": "sneaky", "name": "Sneaky", "weight": 0.9})
        result = ps.on_e_pressed()
        assert result == "inventory_full"
        assert ps.state is PickupState.HELD
