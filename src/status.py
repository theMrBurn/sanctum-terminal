import random
from rich.console import Console
from rich.panel import Panel
from rich.columns import Columns
from rich.text import Text
from rich.progress import ProgressBar
from src.engine import SanctumTerminal

console = Console()

# Standardized Color Map (Standard Rich Colors)
SYSTEM_COLORS = {
    "uplink": "dark_orange",
    "fidelity": "medium_purple",
    "core": "chartreuse1",
}


def glitch_text(text: str, heat: int) -> Text:
    """Randomly corrupts text based on heat levels."""
    if heat < 40:
        return Text(text)

    chars = list(text)
    chance = (heat - 40) / 150

    for i in range(len(chars)):
        if chars[i].isalnum() and random.random() < chance:
            chars[i] = random.choice(["&", "$", "?", "!", "#", "×"])

    style = "bold red" if heat > 85 else ""
    return Text("".join(chars), style=style)


def render_dashboard(city_name: str):
    terminal = SanctumTerminal()
    specs = terminal.get_system_specs()
    fidelity = specs.get("fidelity", {}).get("level", 0)
    snapshot = terminal.get_financial_snapshot()

    heat_data = terminal._execute("SELECT value FROM system_state WHERE key='heat'")
    heat = int(heat_data[0][0]) if heat_data else 0

    # NEW: Fetch Hardware Status
    sensor_damaged = terminal.get_hardware_status("sensor_array")

    if fidelity == 0:
        # TIER 0: BIOS MODE
        console.print("-" * 45)
        console.print(f"TERMINAL_CORE_v0.1 // {city_name.upper()}")
        console.print(f"STABILITY_POOL: {snapshot['liquid']:.2f}")
        # Add raw hardware flag for BIOS feel
        hw_flag = "![DAMAGED]" if sensor_damaged else "[NOMINAL]"
        console.print(f"HW_STATUS_ARRAY: {hw_flag}")
        console.print("-" * 45)
        render_system_telemetry(specs, bios=True, heat=heat)
    else:
        # TIER 1+: THE SANCTUM UI
        render_high_fidelity_dashboard(city_name, snapshot, specs, heat, sensor_damaged)


def render_system_telemetry(specs, bios=False, heat=0):
    """Renders the XP bars with distinct, stable colors."""
    if not bios:
        console.print("\n[bold cyan]── SYSTEM TELEMETRY ──[/bold cyan]")
    else:
        console.print("\n[bold]SYSTEM_CALIBRATION_TELEMETRY[/bold]")

    for name, data in specs.items():
        lvl = data["level"]
        xp = data["xp"]
        next_xp = data["next"]

        color = SYSTEM_COLORS.get(name.lower(), "white")
        if bios:
            color = "white"

        # Thermal Overload Logic
        bar_style = "bold red" if heat > 90 else color

        bar = ProgressBar(
            total=next_xp, completed=xp, width=30, pulse=False, style=bar_style
        )

        label = glitch_text(f"{name.upper():<10}", heat)
        console.print(label, end=" ")
        console.print(f"[Lvl {lvl}] ", end="")
        console.print(bar, end="")
        console.print(f" [bold {color}]{xp}/{next_xp} XP[/]")


def render_high_fidelity_dashboard(city, snapshot, specs, heat, sensor_damaged):
    """Refined layout with distinct colors and hardware integrity status."""
    env_text = Text()
    env_text.append(glitch_text(f"{city.title()}\n", heat))

    # Weather display changes based on hardware health
    if sensor_damaged:
        env_text.append("Weather Data: [bold red]OFFLINE[/bold red]\n", style="dim")
    else:
        env_text.append("Weather Data: [bold green]Active[/bold green]\n", style="dim")

    h_style = "green"
    if heat > 50:
        h_style = "dark_orange"
    if heat > 80:
        h_style = "bold red"
    env_text.append(f"Heat: {heat}%", style=h_style)

    env_panel = Panel(env_text, title="PASSIVE ENV", border_style="cyan", expand=False)

    # Financial Panel
    liquid_panel = Panel(
        Text(f"${snapshot['liquid']:,.2f}", style="bold green"),
        title="LIQUID CAPITAL",
        border_style="bright_blue",
        expand=False,
    )

    # Hardware Panel
    hw_style = "bold red" if sensor_damaged else "green"
    hw_status = "DETACHED" if sensor_damaged else "NOMINAL"
    hw_panel = Panel(
        Text(hw_status, style=hw_style),
        title="HARDWARE",
        border_style=hw_style,
        expand=False,
    )

    console.print("\n[bold]SANCTUM-TERMINAL // SYSTEM STATUS[/bold]")
    console.print(Columns([env_panel, liquid_panel, hw_panel]))

    # If damaged, show a critical alert banner
    if sensor_damaged:
        console.print(
            Panel(
                "[blink bold red]CRITICAL HARDWARE FAILURE DETECTED[/blink bold red]\n"
                "[white]Sensor Array reported desoldered. Environmental telemetry is unreliable.\n"
                "Action required: System Repair.[/white]",
                border_style="red",
                title="[red]SYSTEM LOG[/red]",
            )
        )

    render_system_telemetry(specs, bios=False, heat=heat)
