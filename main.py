# main.py
import sys
from core.session import GameSession
from interfaces.terminal_2d import Terminal2D


def main():
    session = GameSession()

    if "--lab" in sys.argv:
        # Launch dedicated Cleanroom mode in 2D to avoid Shader GLSL mismatch
        session.is_lab_mode = True
        session.active_container = None

        app = Terminal2D(session)
        app.run()
    elif "--3d" in sys.argv:
        session.is_lab_mode = False
        session.calibrate("New York Coast")
        session.active_container = None

        from interfaces.atlas_3d import Atlas3D

        # Create instance and run
        bridge = Atlas3D(session)
        bridge.run_bridge()
    else:
        session.is_lab_mode = False
        app = Terminal2D(session)
        app.run()


if __name__ == "__main__":
    main()
