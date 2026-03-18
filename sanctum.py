import sys
import traceback
import pygame
from viewport import SanctumViewport


def ignite():
    print(">>> [DEBUG] Start of Script Reached")
    print("--- [IGNITING SANCTUM VIEWPORT] ---")

    try:
        # Initialize the hardware-validated viewport from viewport.py
        viewport = SanctumViewport()
        print("--- Ignition Green ---")

        # Start the main loop
        viewport.run()

    except Exception:
        print("\n>>> [DEBUG] CRITICAL FAILURE DURING RUNTIME")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    print(">>> [DEBUG] Entering Main Block")
    ignite()
