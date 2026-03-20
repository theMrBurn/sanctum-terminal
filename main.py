# main.py
import sys
from core.session import GameSession
from interfaces.terminal_2d import Terminal2D


def main():
    session = GameSession()

    if "--3d" in sys.argv:
        session.calibrate("New York Coast")
        session.active_container = None

        from interfaces.atlas_3d import Atlas3D

        # Create instance and run
        bridge = Atlas3D(session)
        bridge.run_bridge()
    else:
        app = Terminal2D(session)
        app.run()


if __name__ == "__main__":
    main()
