import argparse
import time
from datetime import datetime, timedelta
from rich.console import Console
from rich.live import Live

# Global console instance
console = Console()

# Configuration
COOLDOWN_HOURS = 1
REPAIR_COST = 250.0


def main():
    # Defensive imports to prevent linter auto-deletion
    from rich.prompt import Prompt
    from src.engine import SanctumTerminal
    from src.scout import ScoutEngine, ThermalError
    from src.sensors import EnvironmentalSensor
    from src.status import render_dashboard

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

    # Maintenance Commands
    subparsers.add_parser("flush", help="Vent thermal load (Costs 100 Aegis)")
    subparsers.add_parser(
        "repair", help=f"Repair desoldered hardware (Costs {REPAIR_COST} Aegis)"
    )

    args = parser.parse_args()

    if args.command == "status":
        if args.watch:
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
        last_scout = terminal.get_last_scout_time()
        time_since = datetime.now() - last_scout
        cooldown_delta = timedelta(hours=COOLDOWN_HOURS)

        if time_since < cooldown_delta:
            remaining = cooldown_delta - time_since
            minutes = int(remaining.total_seconds() // 60)
            console.print(
                f"\n[bold red]ERR:[/bold red] Scout Engine Cooling. Complete in {minutes}m.\n"
            )
            return

        heat_data = terminal._execute("SELECT value FROM system_state WHERE key='heat'")
        current_heat = int(heat_data[0][0]) if heat_data else 0
        sensor = EnvironmentalSensor()
        env = sensor.fetch_passive_data(args.city)
        player = terminal.get_financial_snapshot()

        console.print(
            f"\n[bold cyan]─── MISSION BRIEFING: {args.city.upper()} ───[/bold cyan]"
        )
        console.print(
            f"Environment: [yellow]{env['condition']}[/yellow] | Current Heat: [orange1]{current_heat}%[/orange1]"
        )
        console.print("\nSelect Scouting Profile:")
        console.print(" [1] [green]STEALTH[/green]    (0.5x Heat, 0.7x Reward)")
        console.print(" [2] [white]STANDARD[/white]   (1.0x Heat, 1.0x Reward)")
        console.print(" [3] [red]AGGRESSIVE[/red] (2.0x Heat, 1.5x Reward)")

        choice = Prompt.ask(
            "\nExecute via profile", choices=["1", "2", "3"], default="2"
        )
        tactic_map = {"1": "stealth", "2": "standard", "3": "aggressive"}
        selected_tactic = tactic_map[choice]

        try:
            engine = ScoutEngine(env, player, heat=current_heat, tactic=selected_tactic)
            result = engine.resolve()
        except ThermalError as e:
            console.print(
                f"\n[bold red]─── THERMAL CRITICAL LOCKOUT ───[/bold red]\n[red]{str(e)}[/red]\n"
            )
            return

        terminal.update_vault(result.aegis_delta, result.description, is_mission=True)
        terminal.add_system_xp("uplink", result.xp_gain)
        terminal.add_system_xp("fidelity", int(result.xp_gain / 2))

        if result.system_damage:
            terminal.apply_hardware_damage("sensor_array", damaged=True)

        new_heat = min(100, current_heat + result.heat_gain)
        terminal.cursor.execute(
            "UPDATE system_state SET value = ? WHERE key = 'heat'", (str(new_heat),)
        )
        terminal.conn.commit()

        console.print(f"\n[bold white]MISSION LOG:[/bold white] {result.description}")
        if result.system_damage:
            console.print(
                "[bold blink red]!!! HARDWARE CRITICAL: SENSOR ARRAY DESOLDERED !!![/bold blink red]"
            )

        color = "green" if result.success else "red"
        console.print(
            f"STATUS: [{color}]{'SUCCESS' if result.success else 'FAILURE'}[/{color}]"
        )
        console.print(f"STABILITY: [{color}]{result.aegis_delta:+.2f} Aegis[/{color}]")
        console.print(
            f"THERMAL SURGE: [bold red]+{result.heat_gain}%[/bold red] (Total: {new_heat}%)"
        )
        console.print(f"[dim]XP GAINED: +{result.xp_gain} Uplink[/dim]\n")

    elif args.command == "flush":
        terminal = SanctumTerminal()
        if terminal.get_total_balance() < 100:
            console.print("\n[bold red]ERR:[/bold red] Insufficient Aegis.\n")
            return
        new_heat = terminal.flush_heat()
        console.print(
            f"\n[bold cyan]STABILITY RESTORED:[/bold cyan] Heat sinks at {new_heat}%.\n"
        )

    elif args.command == "repair":
        terminal = SanctumTerminal()
        if not terminal.get_hardware_status("sensor_array"):
            console.print("\n[bold green]SENSORS NOMINAL.[/bold green]\n")
            return
        if terminal.get_total_balance() < REPAIR_COST:
            console.print(f"\n[bold red]ERR:[/bold red] Need {REPAIR_COST} Aegis.\n")
            return
        terminal.repair_hardware("sensor_array", cost=REPAIR_COST)
        console.print(f"\n[bold green]REPAIR COMPLETE.[/bold green]\n")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
