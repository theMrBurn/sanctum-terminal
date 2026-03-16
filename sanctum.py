import argparse
import time
from datetime import datetime, timedelta

from rich.console import Console
from rich.live import Live

from src.engine import SanctumTerminal
from src.scout import ScoutEngine
from src.sensors import EnvironmentalSensor
from src.status import render_dashboard

console = Console()

# Configuration: How many hours between scouts
COOLDOWN_HOURS = 1


def main():
    parser = argparse.ArgumentParser(description="Sanctum Terminal")
    subparsers = parser.add_subparsers(dest="command")

    # Status Command
    status_p = subparsers.add_parser("status")
    status_p.add_argument("city", nargs="?", default="portland")
    status_p.add_argument(
        "--watch", action="store_true", help="Live refresh every 5 seconds"
    )

    # Scout Command
    scout_p = subparsers.add_parser("scout")
    scout_p.add_argument("city", nargs="?", default="portland")

    args = parser.parse_args()

    if args.command == "status":
        if args.watch:
            # The Watcher Loop: Self-contained persistence
            try:
                with Live(refresh_per_second=1):
                    while True:
                        console.clear()
                        render_dashboard(args.city)
                        time.sleep(5)
            except KeyboardInterrupt:
                console.print("\n[bold cyan]Monitoring suspended.[/bold cyan]")
        else:
            render_dashboard(args.city)

    elif args.command == "scout":
        terminal = SanctumTerminal()

        # 1. Check Cooldown (The Temporal Gate)
        last_scout = terminal.get_last_scout_time()
        time_since = datetime.now() - last_scout
        cooldown_delta = timedelta(hours=COOLDOWN_HOURS)

        if time_since < cooldown_delta:
            remaining = cooldown_delta - time_since
            minutes = int(remaining.total_seconds() // 60)
            console.print(
                f"\n[bold red]ERR:[/bold red] Scout Engine Cooling. "
                f"Recalibration complete in [bold white]{minutes} minutes.[/bold white]\n"
            )
            return

        # 2. Fetch Context
        sensor = EnvironmentalSensor()
        env = sensor.fetch_passive_data(args.city)
        player = terminal.get_financial_snapshot()

        # 3. Resolve Mission
        engine = ScoutEngine(env, player)
        result = engine.resolve()

        # 4. Update the Vault (Persistence)
        terminal.update_vault(
            liquid_delta=result.aegis_delta, note=result.description, is_mission=True
        )

        # 5. Feedback
        console.print(f"\n[bold white]MISSION LOG:[/bold white] {result.description}")
        color = "green" if result.success else "red"
        console.print(f"RESULT: [{color}]{result.aegis_delta:+.2f} Aegis[/{color}]")
        print(f"XP GAINED: {result.xp_gain}\n")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
