import os
import sys

# --- THE GOD-MODE BOOTSTRAP ---
_ABS_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ABS_ROOT not in sys.path:
    sys.path.insert(0, _ABS_ROOT)
# ------------------------------

import argparse
import time
from datetime import datetime, timedelta
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

# Sibling imports
try:
    from config_manager import ConfigManager
    from engine import SanctumTerminal
    from scout import ScoutEngine, ThermalError
    from sensors import EnvironmentalSensor
    from status import render_dashboard
except ImportError:
    import config_manager
    import engine
    import scout
    import sensors
    import status
    ConfigManager = config_manager.ConfigManager
    SanctumTerminal = engine.SanctumTerminal
    ScoutEngine = scout.ScoutEngine
    ThermalError = scout.ThermalError
    EnvironmentalSensor = sensors.EnvironmentalSensor
    render_dashboard = status.render_dashboard

console = Console()
COOLDOWN_HOURS = 1
REPAIR_COST = 250.0

def main():
    config = ConfigManager()
    parser = argparse.ArgumentParser(description="Sanctum Terminal")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("status").add_argument("city", nargs="?", default="portland")
    subparsers.add_parser("scout").add_argument("city", nargs="?", default="portland")
    subparsers.add_parser("ledger")
    subparsers.add_parser("flush")
    subparsers.add_parser("repair")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    terminal = SanctumTerminal()

    if args.command == "status":
        render_dashboard(config.resolve_city(args.city))

    elif args.command == "scout":
        city = config.resolve_city(args.city)

        if (datetime.now() - terminal.get_last_scout_time()) < timedelta(hours=COOLDOWN_HOURS):
            console.print("\n[bold red]ERR:[/bold red] Scout Engine Cooling.\n")
            return

        heat_data = terminal._execute("SELECT value FROM system_state WHERE key='heat'")
        current_heat = int(heat_data[0][0]) if heat_data else 0
        hw_status = {"sensor_array": not terminal.get_hardware_status("sensor_array")}

        env = EnvironmentalSensor().fetch_passive_data(city)
        player = terminal.get_financial_snapshot()

        console.print(f"\n[bold cyan]─── MISSION BRIEFING: {city.upper()} ───[/bold cyan]")
        choice = Prompt.ask("\nExecute via profile [1] Stealth [2] Std [3] Aggr", choices=["1", "2", "3"], default="2")
        tactic = config.resolve_tactic(choice)

        try:
            engine_inst = ScoutEngine(env, player, heat=current_heat, tactic=tactic, hardware_status=hw_status)
            result = engine_inst.resolve()
        except ThermalError as e:
            console.print(f"\n[bold red]LOCKOUT:[/bold red] {str(e)}\n")
            return

        terminal.update_vault(result.aegis_delta, result.description, is_mission=True)
        terminal.record_mission(result, city, tactic)
        terminal.add_system_xp("uplink", result.xp_gain)

        if result.system_damage:
            terminal.apply_hardware_damage("sensor_array", damaged=True)

        new_heat = min(100, current_heat + result.heat_gain)
        terminal.cursor.execute("UPDATE system_state SET value = ? WHERE key = 'heat'", (str(new_heat),))
        terminal.conn.commit()

        console.print(f"\n[bold white]MISSION LOG:[/bold white] {result.description}")
        color = "green" if result.success else "red"
        console.print(f"STATUS: [{color}]{'SUCCESS' if result.success else 'FAILURE'}[/{color}]")
        console.print(f"STABILITY: [{color}]{result.aegis_delta:+.2f} Aegis[/{color}]")
        console.print(f"THERMAL SURGE: [bold red]+{result.heat_gain}%[/bold red] (Total: {new_heat}%)\n")

    elif args.command == "ledger":
        history = terminal.get_mission_history()
        if not history:
            console.print("\n[dim]No mission logs found.[/dim]\n")
            return

        table = Table(title="Sovereign Mission Ledger", border_style="cyan")
        table.add_column("Timestamp", style="dim")
        table.add_column("City")
        table.add_column("Profile")
        table.add_column("Result")
        table.add_column("Aegis Δ", justify="right")

        for row in history:
            status_text = "[green]SUCCESS[/green]" if row[3] else "[red]FAILURE[/red]"
            delta_color = "green" if row[4] >= 0 else "red"
            ts = datetime.fromisoformat(row[0]).strftime("%m.%d %H:%M")
            table.add_row(ts, row[1].capitalize(), row[2].upper(), status_text, f"[{delta_color}]{row[4]:+.2f}[/{delta_color}]")

        console.print(table)

    elif args.command == "flush":
        with console.status("[bold cyan]VENTING THERMAL LOAD...", spinner="glitch"):
            time.sleep(1)
            new_heat = terminal.flush_heat()
        console.print(f"\n[bold cyan]STABILITY RESTORED:[/bold cyan] Heat sinks at {new_heat}%.\n")

    elif args.command == "repair":
        if not terminal.get_hardware_status("sensor_array"):
            console.print("\n[bold green]SENSORS NOMINAL.[/bold green]\n")
            return
        terminal.repair_hardware("sensor_array", cost=REPAIR_COST)
        console.print("\n[bold green]REPAIR COMPLETE.[/bold green]\n")

if __name__ == "__main__":
    main()