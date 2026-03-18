import pytest
import numpy as np
from pyrr import Vector3
from engine import DataNode


def test_voxel_stream_integrity():
    brain = DataNode()
    mock_pos = Vector3([0.0, 0.0, 0.0])
    stream = brain.get_stream(mock_pos, radius=10.0)

    assert len(stream) > 0
    assert "p" in stream[0]
    assert "c" in stream[0]


def test_organic_bubble_consistency():
    """Verify that moving the player preserves the scaffold density."""
    brain = DataNode()
    pos_a = Vector3([0.0, 0.0, 0.0])
    pos_b = Vector3([500.0, 0.0, 500.0])

    stream_a = brain.get_stream(pos_a, radius=10.0)
    stream_b = brain.get_stream(pos_b, radius=10.0)

    # Grid counts should be stable regardless of location
    assert abs(len(stream_a) - len(stream_b)) < 10


def test_radial_culling():
    """Verify no voxels exist outside the defined sensory radius."""
    brain = DataNode()
    radius = 5.0
    player_pos = Vector3([0.0, 0.0, 0.0])
    stream = brain.get_stream(player_pos, radius=radius)

    for v in stream:
        dist = np.sqrt(v["p"][0] ** 2 + v["p"][2] ** 2)
        assert dist <= radius + 1.5  # Padding for floor-snapping
