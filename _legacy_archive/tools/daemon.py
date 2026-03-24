import time
from datetime import datetime

from rich.console import Console
from rich.live import Live
from rich.table import Table

from engine import SanctumTerminal
from sensors import EnvironmentalSensor

console = Console()

# Cooling Multipliers based on weather conditions
WEATHER_MODIFIERS = {
    "Snow": 2.0,  # Arctic dissipation
    "Rain": 1.5,  # Liquid cooling
    "Clouds": 1.0,  # Nominal
    "Clear": 1.0,  # Nominal
    "Extreme": 0.0,  # Thermal stagnation
}


def cooling_tick(terminal, condition="Clear"):
    """
    Reduces system heat based on environmental modifiers.
    Base dissipation: 5%
    """
    # 1. Fetch current heat
    res = terminal._execute("SELECT value FROM system_state WHERE key='heat'")
    current_heat = int(res[0][0]) if res else 0

    if current_heat <= 0:
        return 0

    # 2. Dynamic Cooling Math
    modifier = WEATHER_MODIFIERS.get(condition, 1.0)
    base_dissipation = 5
    actual_cooling = int(base_dissipation * modifier)

    new_heat = max(0, current_heat - actual_cooling)

    # 3. Update DB
    terminal.cursor.execute(
        "UPDATE system_state SET value = ? WHERE key = 'heat'", (str(new_heat),)
    )
    terminal.conn.commit()

    if terminal.debug:
        print(f"[DAEMON] Cooling tick: -{actual_cooling}% (Condition: {condition})")

    return new_heat


def run_daemon(home_city="portland"):
    terminal = SanctumTerminal()
    sensor = EnvironmentalSensor()

    # Track the last hour we processed maintenance
    last_tick_hour = datetime.now().hour

    with Live(refresh_per_second=1) as live:
        while True:
            now = datetime.now()
            snapshot = terminal.get_financial_snapshot()

            # Fetch current weather context for the Home City
            env = sensor.fetch_passive_data(home_city)
            condition = env.get("condition", "Clear")

            # Fetch current heat for the UI display
            heat_data = terminal._execute(
                "SELECT value FROM system_state WHERE key='heat'"
            )
            current_heat = int(heat_data[0][0]) if heat_data else 0

            # 1. MAINTENANCE TICK: Every new hour
            if now.hour != last_tick_hour:
                # --- A. Passive Yield Logic ---
                interest = snapshot["assets"] * 0.001
                if interest > 0:
                    terminal.update_vault(
                        liquid_delta=interest,
                        note="Passive Yield: Physical Asset Appreciation",
                        is_mission=False,
                    )

                # --- B. Passive Cooling Logic (Weather Dependent) ---
                cooling_tick(terminal, condition=condition)

                last_tick_hour = now.hour

            # 2. UI Refresh
            table = Table(title="[bold blue]SANCTUM // BACKGROUND DAEMON[/bold blue]")
            table.add_column("Telemetry", style="cyan")
            table.add_column("Value", style="green")

            table.add_row("Uptime Status", "ACTIVE")
            table.add_row("Home City", home_city.upper())
            table.add_row(
                "Env Condition",
                f"{condition} (x{WEATHER_MODIFIERS.get(condition, 1.0)})",
            )
            table.add_row("Current Time", now.strftime("%H:%M:%S"))
            table.add_row("Thermal Load", f"{current_heat}%")
            table.add_row("Ledger Total", f"${snapshot['aegis']:,.2f}")
            table.add_row("Vault Assets", f"${snapshot['assets']:,.2f}")
            table.add_row("Maintenance", f"Next Tick at {(now.hour + 1) % 24}:00")

            live.update(table)

            # Check for hour transitions every minute
            time.sleep(60)


if __name__ == "__main__":
    console.print("[bold yellow]Initiating Heartbeat Daemon...[/bold yellow]")
    try:
        # Defaulting to Portland as the 'Home City' for cooling context
        run_daemon(home_city="portland")
    except KeyboardInterrupt:
        console.print("\n[bold red]Daemon Terminated Safely.[/bold red]")
