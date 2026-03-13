from src.engine import SanctumTerminal
from rich.console import Console
from rich.panel import Panel
from rich.columns import Columns
from rich import box

console = Console()

def render_dashboard():
    # Initialize engine (debug=False for the clean UI look)
    terminal = SanctumTerminal()
    
    # Grab the verified data package
    snapshot = terminal.get_financial_snapshot()
    
    # Create the high-contrast info panels
    liquid_panel = Panel(
        f"[bold green]${snapshot['liquid']:,.2f}[/bold green]",
        title="LIQUID CAPITAL",
        border_style="green",
        box=box.DOUBLE
    )
    
    asset_panel = Panel(
        f"[bold cyan]${snapshot['assets']:,.2f}[/bold cyan]",
        title="PHYSICAL ASSETS",
        border_style="cyan",
        box=box.DOUBLE
    )
    
    aegis_panel = Panel(
        f"[bold magenta]${snapshot['aegis']:,.2f}[/bold magenta]",
        title="TOTAL AEGIS",
        border_style="magenta",
        box=box.HEAVY
    )

    # Render the layout
    console.print("\n[bold white]SANCUM-TERMINAL // SYSTEM STATUS[/bold white]")
    console.print(Columns([liquid_panel, asset_panel, aegis_panel]))
    console.print(f"[dim]Vault Path: {terminal.db_path}[/dim]\n")

if __name__ == "__main__":
    render_dashboard()