import time
from datetime import datetime
from rich.console import Console
from rich.live import Live
from rich.table import Table
from src.engine import SanctumTerminal

console = Console()


def run_daemon():
    terminal = SanctumTerminal()
    # Track the last hour we paid out interest
    last_payout_hour = datetime.now().hour

    with Live(refresh_per_second=1) as live:
        while True:
            now = datetime.now()
            snapshot = terminal.get_financial_snapshot()

            # 1. Passive Yield Logic: Every new hour, generate interest
            if now.hour != last_payout_hour:
                # 0.1% hourly yield on physical assets
                interest = snapshot["assets"] * 0.001
                if interest > 0:
                    terminal.update_vault(
                        liquid_delta=interest,
                        note="Passive Yield: Physical Asset Appreciation",
                        is_mission=False,
                    )
                last_payout_hour = now.hour

            # 2. UI Refresh: Terminal Dashboard for the Daemon
            table = Table(title="[bold blue]SANCTUM // BACKGROUND DAEMON[/bold blue]")
            table.add_column("Telemetry", style="cyan")
            table.add_column("Value", style="green")

            table.add_row("Uptime Status", "ACTIVE")
            table.add_row("Current Time", now.strftime("%H:%M:%S"))
            table.add_row("Ledger Total", f"${snapshot['aegis']:,.2f}")
            table.add_row("Vault Assets", f"${snapshot['assets']:,.2f}")
            table.add_row("Recalibration", f"Next Payout at { (now.hour + 1) % 24 }:00")

            live.update(table)

            # Pulse every minute to check for hour transitions
            time.sleep(60)


if __name__ == "__main__":
    console.print("[bold yellow]Initiating Heartbeat Daemon...[/bold yellow]")
    try:
        run_daemon()
    except KeyboardInterrupt:
        console.print("\n[bold red]Daemon Terminated Safely.[/bold red]")
