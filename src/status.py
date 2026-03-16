from rich.console import Console
from src.engine import SanctumTerminal

console = Console()


def render_status(city_data: dict):
    terminal = SanctumTerminal()
    specs = terminal.get_system_specs()
    fidelity = specs.get("fidelity", {}).get("level", 0)

    if fidelity == 0:
        # TIER 0: BIOS MODE
        # Subtle immersion: No colors, no boxes, raw telemetry.
        console.print("-" * 40)
        console.print(f"TERMINAL_CORE_v0.1 // {city_data['city'].upper()}")
        console.print(f"ENV_DATA: {city_data['temp']}F | {city_data['condition']}")
        console.print(f"STABILITY_POOL: {terminal.get_total_balance():.2f}")
        console.print("-" * 40)
        console.print("[dim]LOG: GFX_DRIVER_NOT_FOUND. SYSTEM_UPGRADE_REQUIRED.[/dim]")

    else:
        # TIER 1+: THE SANCTUM UI
        # This is the beautiful Rich layout we already built.
        render_high_fidelity_dashboard(city_data, terminal, specs)


def render_high_fidelity_dashboard(city_data, terminal, specs):
    # (Your existing code with Panels and Colors goes here)
    # Plus, we can now add a progress bar for the next level!
    pass
