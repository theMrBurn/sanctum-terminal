import time
from datetime import datetime

from rich.console import Console
from rich.live import Live
from rich.table import Table

from src.engine import SanctumTerminal

console = Console()


def cooling_tick(terminal):
    """
    Reduces system heat based on elapsed time.
    Satisfies TDD requirement: Reduces heat by 5, floor at 0.
    """
    # 1. Fetch current heat
    res = terminal._execute("SELECT value FROM system_state WHERE key='heat'")
    current_heat = int(res[0][0]) if res else 0

    if current_heat <= 0:
        return 0

    # 2. Cooling Math (5% dissipation)
    new_heat = max(0, current_heat - 5)

    # 3. Update DB
    terminal.cursor.execute(
        "UPDATE system_state SET value = ? WHERE key = 'heat'", (str(new_heat),)
    )
    terminal.conn.commit()
    return new_heat


def run_daemon():
    terminal = SanctumTerminal()
    # Track the last hour we processed maintenance (Yield + Cooling)
    last_tick_hour = datetime.now().hour

    with Live(refresh_per_second=1) as live:
        while True:
            now = datetime.now()
            snapshot = terminal.get_financial_snapshot()

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

                # --- B. Passive Cooling Logic ---
                cooling_tick(terminal)

                last_tick_hour = now.hour

            # 2. UI Refresh: Terminal Dashboard for the Daemon
            table = Table(title="[bold blue]SANCTUM // BACKGROUND DAEMON[/bold blue]")
            table.add_column("Telemetry", style="cyan")
            table.add_column("Value", style="green")

            table.add_row("Uptime Status", "ACTIVE")
            table.add_row("Current Time", now.strftime("%H:%M:%S"))
            table.add_row(
                "Thermal Load", f"{current_heat}%"
            )  # Real-time heat telemetry
            table.add_row("Ledger Total", f"${snapshot['aegis']:,.2f}")
            table.add_row("Vault Assets", f"${snapshot['assets']:,.2f}")
            table.add_row("Maintenance", f"Next Tick at {(now.hour + 1) % 24}:00")

            live.update(table)

            # Pulse every minute to check for hour transitions
            time.sleep(60)


if __name__ == "__main__":
    console.print("[bold yellow]Initiating Heartbeat Daemon...[/bold yellow]")
    try:
        run_daemon()
    except KeyboardInterrupt:
        console.print("\n[bold red]Daemon Terminated Safely.[/bold red]")
