import os
from core.vault import vault


class SystemLoader:
    """
    Evolved from the original daemon. Handles the hot-loading of
    voxel assets and system-level manufacturing instructions.
    """

    def __init__(self, engine_vault):
        self.vault = engine_vault
        self.load_queue = []
        print("Infra: SystemLoader (Daemon) Active.")

    def scan_assets(self, directory="data/live_assets"):
        """Scans for new voxel models to manufacture."""
        if not os.path.exists(directory):
            os.makedirs(directory)

        assets = os.listdir(directory)
        self.load_queue = [a for a in assets if a.endswith(".vox")]
        print(f"Loader: Found {len(self.load_queue)} assets in queue.")

    def dispatch(self):
        """Dispatches the next item in the queue to the Engine Vault."""
        if self.load_queue:
            asset = self.load_queue.pop(0)
            self.vault.store("active_manufacturing_target", asset)
            return asset
        return None
