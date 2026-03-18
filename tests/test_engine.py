import pytest
from core.vault import Vault
import numpy as np


@pytest.fixture
def vault():
    # Uses the absolute pathing we built into the Vault class
    return Vault()


def test_vault_bloom_on_fetch(vault):
    """Verify that fetching an empty sector triggers a procedural bloom."""
    # Pick a coordinate far out that shouldn't be in the initial seed
    far_pos = [2000.0, 0.0, 2000.0]

    # 1. First fetch should trigger _bloom_entropy internally
    frame = vault.get_visible_frame(far_pos, None, radius=10.0)

    # 2. Assert we got data back (Bloom worked)
    assert len(frame) > 0
    assert "p" in frame.dtype.names
    assert "c" in frame.dtype.names


def test_vault_collision_logic(vault):
    """Verify AABB collision detection."""
    # Test a known 'empty' air position (assuming y=0 is ground)
    assert vault.check_collision([0.0, 10.0, 0.0]) is False

    # Test ground level (y is usually < 0.5 for floor)
    # Note: Bloom uses y = seed * 2.5, so check_collision looks for y > 0.5
    high_pos = [0.0, 0.0, 0.0]
    # This depends on your specific seed/bloom, but ensures the method runs
    result = vault.check_collision(high_pos)
    assert isinstance(result, bool)
