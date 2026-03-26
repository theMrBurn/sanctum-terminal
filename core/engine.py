import sys

import pygame

from core.vault import vault
from core.viewport import Viewport
from infra.loader import SystemLoader


class SanctumTerminal:
    """
    The central coordinator for the Sanctum Terminal.
    Manages the lifecycle of the Vault (Data), Viewport (Render),
    and Loader (Infrastructure/Daemon).
    """

    def __init__(self):
        # 1. Initialize the Data Layer
        self.vault = vault()

        # 2. Initialize the Render Layer
        self.viewport = Viewport()

        # 3. Initialize the Infrastructure Layer (The evolved Daemon)
        # Passing the vault to the loader allows for direct data handoffs
        self.loader = SystemLoader(self.vault)

        # Engine State
        self.is_running = True
        self.clock = pygame.time.Clock()
        self.fps = 60

        print("--- Sanctum Engine: Voxel Manufacturing Mode ---")
        print(
            f"Systems Check: Vault[{'OK' if self.vault.initialized else '??'}] "
            f"Viewport[{'OK' if self.viewport else '??'}]"
        )

    def boot(self):
        """
        Initializes the hardware context and prepares for the main loop.
        """
        pygame.init()
        self.viewport.initialize_display()

        # Initial scan for manufacturing assets
        self.loader.scan_assets()
        print("Kernel: Graphics context and Asset Loader initialized.")

    def run(self):
        """
        The main execution loop for voxel processing and rendering.
        """
        while self.is_running:
            self.handle_events()
            self.update()
            self.render()
            self.clock.tick(self.fps)

    def handle_events(self):
        """Handles OS-level events and input requests."""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.shutdown()

            # Placeholder for manufacturing-specific keybinds
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self.shutdown()

    def update(self):
        """Logic pass for the loader and spatial transformations."""
        # The loader checks the queue and updates the vault automatically
        active_asset = self.loader.dispatch()
        if active_asset:
            print(f"Engine: Now manufacturing {active_asset}")

        self.viewport.update()

    def render(self):
        """Draws the current voxel state to the display."""
        if self.viewport.display:
            # Basic clear screen - Replace with Voxel Render Pipeline
            self.viewport.display.fill((10, 10, 15))
            pygame.display.flip()

    def shutdown(self):
        """Cleanly terminates all subsystems."""
        print("\nKernel: Initiating shutdown sequence...")
        self.is_running = False
        pygame.quit()
        print("Kernel: All systems offline.")
        sys.exit()


if __name__ == "__main__":
    # Self-test entry point
    engine = SanctumTerminal()
    engine.boot()
    # engine.run() # Uncomment to start the actual loop
