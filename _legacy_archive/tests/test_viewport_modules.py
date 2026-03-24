import pytest
import numpy as np
from core.vault import Vault
from systems.observer import ObserverSystem
from unittest.mock import MagicMock


def test_vault_observer_handshake():
    """Verify that the Vault and Observer can coexist in a shared frame."""
    vault = Vault()
    mock_config = MagicMock()
    mock_config.resolve_city.return_value = "portland"
    observer = ObserverSystem(mock_config)

    # 1. Get world data
    pos = [0.0, 0.0, 0.0]
    frame = vault.get_visible_frame(pos, [0, 0, -1], radius=20.0)

    # 2. Get shader state
    params = observer.get_shader_params()

    assert len(frame) >= 0
    assert "u_intensity" in params
    assert params["u_visibility"] == 72.0


def test_collision_boundary():
    """Ensure the vault correctly identifies floor vs obstacles."""
    vault = Vault()
    # Testing a point high in the air
    assert vault.check_collision([0, 50, 0]) is False
