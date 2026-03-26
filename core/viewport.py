import pygame

# Relative import to pull the camera from the same directory
from .spatial_utils import RelativityCamera


class Viewport:
    def __init__(self):
        self.camera = RelativityCamera()
        self.display = None
        self.resolution = (1280, 720)
        print("Viewport: Ready for Voxel Rendering.")

    def initialize_display(self):
        """Sets up the pygame window."""
        self.display = pygame.display.set_mode(self.resolution)
        pygame.display.set_caption("Sanctum Terminal - Voxel Manufacturing")

    def update(self):
        """Main rendering pass (Voxel logic goes here)."""
        pass
