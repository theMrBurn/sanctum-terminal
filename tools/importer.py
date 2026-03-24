import hashlib
from pathlib import Path
from rich.console import Console

console = Console()

class VoxelTransformer:
    def __init__(self, vault_path="data/vault.db"):
        self.vault_path = vault_path

    def generate_relic_hash(self, file_path):
        """Creates a unique identity for your Voxel Max export."""
        with open(file_path, "rb") as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()
        
        # We use a 12-character 'Short-Hash' for the HUD
        short_id = file_hash[:12]
        console.log(f"[bold green]HASH GENERATED:[/bold green] {short_id}")
        return file_hash

    def register_to_vault(self, file_path):
        """Prepares the object for the procedural engine."""
        file_hash = self.generate_relic_hash(file_path)
        # Here we will add the SQLite insertion logic next...
        return file_hash