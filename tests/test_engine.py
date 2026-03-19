import pytest
import numpy as np
import time
from core.vault import Vault
from systems.avatar import Avatar


@pytest.fixture
def world():
    v = Vault()
    # Avatar starts at local origin in the new architecture
    a = Avatar([0.0, 0.0, 0.0])
    return v, a


def test_genesis_platform_persistence(world):
    vault, _ = world
    # Query at world origin
    res = vault.get_visible_frame(
        np.array([0.0, 0.0, 0.0], dtype="f4"), [0, 0, 1], radius=5.0
    )
    assert len(res) > 0
    grey_mask = np.all(np.isclose(res["c"], [0.3, 0.3, 0.3], atol=0.1), axis=1)
    assert len(res[grey_mask]) > 0


def test_avatar_gravity_tether(world):
    vault, avatar = world
    # Start higher to ensure we don't hit the ground in one frame
    avatar.pos[1] = 10.0

    avatar.update(0.1, [0, 0], vault, np.zeros(3, dtype="f4"))

    # After one update, velocity should definitely be negative
    assert avatar.vel[1] < 0


def test_avatar_relativistic_collision(world):
    """
    Ensures that if the world slides a voxel into the player's
    local space, the player detects it.
    """
    vault, avatar = world
    # 1. Place a block at world coordinate [10, 0, 10]
    vault.manifest_voxel(np.array([10.0, 0.0, 10.0]), [1.0, 1.0, 1.0])

    # 2. Slide the world so the player is 'standing' on that block
    # If the world_offset is [10, 0, 10], the block is now at local [0, 0, 0]
    world_offset = np.array([10.0, 0.0, 10.0], dtype="f4")

    # 3. Update avatar - it should report being on_ground because of the offset block
    avatar.update(0.1, [0, 0], vault, world_offset)

    assert avatar.on_ground is True
    assert avatar.pos[1] == 0.0


def test_vault_vectorized_bloom(world):
    vault, _ = world
    # Test blooming a chunk far away
    now = int(time.time())
    vault._bloom_entropy(400, 400, 0, now)

    frame = vault.get_visible_frame(
        np.array([400, 0, 400], dtype="f4"), [0, 0, 1], radius=10.0
    )
    assert len(frame) > 0
    assert frame.dtype == [("p", "f4", (3,)), ("c", "f4", (3,)), ("t", "f4")]
