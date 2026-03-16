from src.engine import SanctumTerminal
from src.sensors import EnvironmentalSensor  # <-- ADD THIS
from rich.console import Console
from rich.panel import Panel
from rich.columns import Columns
from rich import box

console = Console()


def render_dashboard(city="portland"):
    terminal = SanctumTerminal()
    sensor = EnvironmentalSensor()  # <-- INITIALIZE SENSOR

    # Grab both layers of reality
    snapshot = terminal.get_financial_snapshot()
    env = sensor.fetch_passive_data(city)  # <-- USE THE CITY ARGUMENT

    # NEW: Passive Environment Panel (Blue Layer)
    env_text = (
        f"[bold white]{env['city']}[/bold white]\n"
        f"[cyan]{env['temp']}°F[/cyan] | [blue]{env['condition']}[/blue]\n"
        f"[dim]Wind: {env['wind_speed']}mph[/dim]"
    )
    env_panel = Panel(
        env_text, title="PASSIVE ENV", border_style="blue", box=box.ROUNDED
    )

    # Economy Panels (Active Layer)
    liquid_panel = Panel(
        f"[bold green]${snapshot['liquid']:,.2f}[/bold green]",
        title="LIQUID CAPITAL",
        border_style="green",
        box=box.DOUBLE,
    )

    aegis_panel = Panel(
        f"[bold magenta]${snapshot['aegis']:,.2f}[/bold magenta]",
        title="TOTAL AEGIS",
        border_style="magenta",
        box=box.HEAVY,
    )

    # Render the Merged State
    console.print("\n[bold white]SANCTUM-TERMINAL // SYSTEM STATUS[/bold white]")
    # Added env_panel to the columns list
    console.print(Columns([env_panel, liquid_panel, aegis_panel]))

    if not env["is_live"]:
        console.print("[yellow]![/yellow] [dim]Running on Offline Defaults[/dim]")


if __name__ == "__main__":
    render_dashboard()
