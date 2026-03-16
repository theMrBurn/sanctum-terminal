import argparse
import time
from datetime import datetime, timedelta

from rich.console import Console
from rich.live import Live

from src.engine import SanctumTerminal
from src.scout import ScoutEngine, ThermalError
from src.sensors import EnvironmentalSensor
from src.status import render_dashboard

console = Console()

# Configuration
COOLDOWN_HOURS = 1
REPAIR_COST = 250.0


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

    # Maintenance Commands
    subparsers.add_parser("flush", help="Vent thermal load (Costs 100 Aegis)")
    subparsers.add_parser("repair", help=f"Repair desoldered hardware (Costs {REPAIR_COST} Aegis)")

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

        # 1. Check Cooldown
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
        heat_data = terminal._execute("SELECT value FROM system_state WHERE key='heat'")
        current_heat = int(heat_data[0][0]) if heat_data else 0

        sensor = EnvironmentalSensor()
        env = sensor.fetch_passive_data(args.city)
        player = terminal.get_financial_snapshot()

        # 3. Resolve Mission with Thermal Guard
        try:
            engine = ScoutEngine(env, player, heat=current_heat)
            result = engine.resolve()
        except ThermalError as e:
            console.print("\n[bold red]─── THERMAL CRITICAL LOCKOUT ───[/bold red]")
            console.print(f"[red]{str(e)}[/red]")
            console.print(
                "[yellow]Recommendation: Run 'python3 sanctum.py flush' or wait for background cooling.[/yellow]\n"
            )
            return

        # 4. Update the Vault, Progression, and HEAT
        terminal.update_vault(
            liquid_delta=result.aegis_delta, note=result.description, is_mission=True
        )

        terminal.add_system_xp("uplink", result.xp_gain)
        terminal.add_system_xp("fidelity", int(result.xp_gain / 2))

        # --- PERSIST HARDWARE DAMAGE ---
        if result.system_damage:
            terminal.apply_hardware_damage("sensor_array", damaged=True)

        # Save new heat state
        new_heat = min(100, current_heat + result.heat_gain)
        terminal.cursor.execute(
            "UPDATE system_state SET value = ? WHERE key = 'heat'", (str(new_heat),)
        )
        terminal.conn.commit()

        # 5. Feedback
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
        console.print(
            f"[dim]XP GAINED: +{result.xp_gain} Uplink | +{int(result.xp_gain/2)} Fidelity[/dim]\n"
        )

    elif args.command == "flush":
        terminal = SanctumTerminal()
        if terminal.get_total_balance() < 100:
            console.print(
                "\n[bold red]ERR:[/bold red] Insufficient Aegis for thermal vent.\n"
            )
            return
        new_heat = terminal.flush_heat()
        console.print(
            f"\n[bold cyan]STABILITY RESTORED:[/bold cyan] Heat sinks stabilized at {new_heat}%.\n"
        )

    elif args.command == "repair":
        terminal = SanctumTerminal()
        
        # Check if repair is needed
        if not terminal.get_hardware_status("sensor_array"):
            console.print("\n[bold green]SENSORS NOMINAL:[/bold green] No hardware degradation detected.\n")
            return

        # Check funds
        if terminal.get_total_balance() < REPAIR_COST:
            console.print(f"\n[bold red]ERR:[/bold red] Insufficient Aegis. Repair requires [white]{REPAIR_COST}[/white] Aegis.\n")
            return

        # Execute
        try:
            terminal.repair_hardware("sensor_array", cost=REPAIR_COST)
            console.print(f"\n[bold green]REPAIR COMPLETE:[/bold green] Sensor Array realigned and secured.")
            console.print(f"[dim]Maintenance cost: {REPAIR_COST} Aegis deducted from stability pool.[/dim]\n")
        except Exception as e:
            console.print(f"\n[bold red]FATAL:[/bold red] {str(e)}\n")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()