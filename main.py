class SanctumTerminal(ShowBase):
    def __init__(self):
        super().__init__()
        
        # Window Setup
        props = WindowProperties()
        props.setTitle("Sanctum Terminal v7.0")
        self.win.requestProperties(props)
        
        # --- [INGESTION TEST] ---
        # Load a basic cube from the Panda3D internal library
        self.test_cube = self.loader.loadModel("models/box")
        self.test_cube.reparentTo(self.render)
        self.test_cube.setScale(1, 1, 1)
        self.test_cube.setPos(0, 5, 0) # Move it forward so we can see it
        
        # Add a light so the cube isn't just a black silhouette
        from panda3d.core import PointLight
        plight = PointLight('plight')
        plight_node = self.render.attachNewNode(plight)
        plight_node.setPos(0, 0, 10)
        self.render.setLight(plight_node)
        # --- [END TEST] ---

        console.log("[bold green]Sanctum Terminal initialized.[/bold green] Neural Link active.")
        console.log("[yellow]Baseline:[/yellow] Spatial Design Auditor mode engaged.")
        
        self.accept("escape", self.exit_app)