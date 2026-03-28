from rich.console import Console

console = Console()


class ObserverTask:
    def __init__(self, render_node):
        self.render_node = render_node
        self.scan_radius = 50.0
        self.last_audit_time = 0
        console.log("[bold yellow]OBSERVER:[/bold yellow] Intelligence initialized.")

    def update(self, task):
        """
        This is the main loop called by Panda3D's taskMgr.
        We will eventually put the 'Strain' and 'Occlusion' math here.
        """
        # For now, we just keep the heartbeat alive
        return task.cont

    def perform_audit(self, model_node):
        """
        This will be triggered by the Daemon when a new Voxel Max
        object is injected.
        """
        console.log(
            f"[bold blue]AUDIT:[/bold blue] Scanning object {model_node.getName()}..."
        )
        # Placeholder for the math from your Legacy volume.py
        return True
