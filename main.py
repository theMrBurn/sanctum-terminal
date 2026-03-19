# main.py
import os
import sys

# 1. Path Injection: Standardize the environment before anything else
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# 2. Imports: Moved after path injection to ensure they are found
# The 'noqa' tag tells Ruff to ignore E402 here if it still complains,
# because our project structure requires this specific order.
from core.session import GameSession  # noqa: E402
from interfaces.terminal_2d import Terminal2D  # noqa: E402


def main():
    print("--- SANCTUM_OS KERNEL BOOTING ---")

    # Initialize the Universal Seed
    session = GameSession()

    # Engine toggle: Future-proofing for 3D/VR transition
    if "--3d" in sys.argv:
        print("HITCHING 3D ATLAS_ENGINE...")
        # from interfaces.atlas_3d import Atlas3D
        # app = Atlas3D(session)
    else:
        print("LINKING 2D TERMINAL INTERFACE...")
        app = Terminal2D(session)

    try:
        app.run()
    except Exception as e:
        print(f"KERNEL PANIC: {e}")
    finally:
        print("--- SANCTUM_OS SHUTDOWN ---")


if __name__ == "__main__":
    main()
