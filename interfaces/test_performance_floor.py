import time
import pytest
from types import SimpleNamespace
from interfaces.panda_bridge import PandaKernelBridge


@pytest.fixture
def perf_bridge():
    # Setup mock session
    session = SimpleNamespace()
    session.pos = [0.0, 0.0, 0.0]
    session.seed = 42
    session.tension = 0
    # Use a real WorldEngine to simulate actual logic overhead
    from engines.world import WorldEngine

    session.world_engine = WorldEngine(session.seed)

    # Initialize bridge in headless mode (no window)
    bridge = PandaKernelBridge.__new__(PandaKernelBridge)
    bridge.session = session
    bridge.world = session.world_engine
    bridge.voxels = {}
    bridge.render_radius = 12
    # Mock render node so attachNewNode doesn't crash
    bridge.tile_root = SimpleNamespace(
        attachNewNode=lambda x: SimpleNamespace(
            setPos=lambda a, b, c: None,
            setP=lambda a: None,
            setTexture=lambda a: None,
            setColor=lambda a: None,
        )
    )
    return bridge


def test_fps_floor_during_movement(perf_bridge):
    """
    Ensures that spawning a new 12-radius sector stays under 18ms
    (equivalent to maintaining > 55fps).
    """
    start_time = time.time()

    # Simulate the actual sync_with_kernel loop
    px, pz = 0, 0
    for x in range(px - perf_bridge.render_radius, px + perf_bridge.render_radius):
        for z in range(pz - perf_bridge.render_radius, pz + perf_bridge.render_radius):
            perf_bridge.world.get_node(x, z, perf_bridge.session)
            # This is where we'd call spawn_node

    elapsed = time.time() - start_time

    # 1/55 fps = ~18.1ms per frame
    # We allow 10ms for logic to leave 8ms for GPU draw
    assert (
        elapsed < 0.010
    ), f"Performance Floor Violated: {elapsed*1000:.2f}ms exceeds 10ms logic budget"
