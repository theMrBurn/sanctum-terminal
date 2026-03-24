import sys
from pathlib import Path
from direct.showbase.ShowBase import ShowBase
from panda3d.core import WindowProperties
from rich.console import Console

# Unified Core Imports - Mapped to your specific Tree
from core.vault import RelicVault
from core.spatial_utils import * # Pulls in math utilities
from tools.importer import VoxelTransformer as Transformer # Where the class actually lives
from tools.daemon import VoxelWatcher
from systems.observer import ObserverTask

console = Console()

class SanctumTerminal(ShowBase):
    def __init__(self):
        super().__init__()
        
        # 1. Laboratory Environment
        props = WindowProperties()
        props.setTitle("Sanctum Simulation Lab v7.1")
        self.win.requestProperties(props)
        
        # 2. Data Persistence (The Vault)
        self.vault = RelicVault()
        
        # 3. The Watcher (Daemon)
        # Ensure this path exists or change it to your Voxel Max export folder
        self.export_path = Path("exports")
        self.export_path.mkdir(exist_ok=True)
        
        self.watcher = VoxelWatcher(
            watch_path=str(self.export_path), 
            callback=self.on_relic_detected
        )
        self.watcher.start()
        
        # 4. The Auditor (Observer)
        # We pass self.render so the observer can see the 3D scene
        self.observer = ObserverTask(self.render)
        self.taskMgr.add(self.observer.update, "ObserverUpdateTask")

        console.log("[bold green]Simulation Lab Online.[/bold green] Watching 'exports/' for Voxel Max data...")
        self.accept("escape", self.exit_app)

    def on_relic_detected(self, file_path):
        """The Hook: Triggered by Voxel Max Export"""
        console.log(f"[bold magenta]INGESTION:[/bold magenta] Processing {file_path}")
        
        # Logic to Hash and Vault the new object
        # We will create a small helper in importer.py for this next
        from tools.importer import VoxelTransformer as Transformer
        t = Transformer()
        v_hash = t.generate_relic_hash(file_path)
        
        if self.vault.register_relic(v_hash, Path(file_path).name):
            console.log(f"[cyan]VAULT:[/cyan] Relic {v_hash[:8]} locked in database.")
        
    def exit_app(self):
        if hasattr(self, 'watcher'):
            self.watcher.stop()
        console.log("[bold red]Shutting down Lab...[/bold red]")
        sys.exit(0)

if __name__ == "__main__":
    app = SanctumTerminal()
    app.run()