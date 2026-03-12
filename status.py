import sqlite3

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def get_status():
    db_path = "vault.db"
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        # 1. Calculate Liquid Cache (Ledger Total)
        cursor.execute("SELECT SUM(amount) FROM ledger")
        liquid = cursor.fetchone()[0] or 0.0

        # 2. Calculate Asset Value (Archive Total)
        # Note: We use the 'cost' column we just verified exists
        cursor.execute("SELECT COUNT(*), SUM(cost) FROM archive")
        relic_count, asset_value = cursor.fetchone()
        asset_value = asset_value or 0.0

        # 3. Recent History
        cursor.execute(
            "SELECT timestamp, event_type, amount FROM ledger ORDER BY id DESC LIMIT 3"
        )
        recent = cursor.fetchall()

    # --- THE ARCHITECT'S VIEW ---
    console.print(
        Panel.fit(
            "[bold cyan]SANCTUM-TERMINAL STATUS REPORT[/bold cyan]\n"
            "[yellow]Sector:[/yellow] Portland [Rain-Veil] | [yellow]Engine:[/yellow] Python 3.12.13",
            border_style="cyan",
        )
    )

    table = Table(show_header=False, box=None)
    table.add_row("LIQUID CACHE:", f"[green]${liquid:,.2f}[/green]")
    table.add_row("ASSET VALUE:", f"[blue]${asset_value:,.2f}[/blue]")
    table.add_row("RELIC COUNT:", f"{relic_count} Physical Units")
    table.add_row("-" * 20, "-" * 10)
    table.add_row(
        "NET POSITION:", f"[bold white]${(liquid + asset_value):,.2f}[/bold white]"
    )

    console.print(table)

    if recent:
        console.print("\n[bold]RECENT LEDGER ACTIVITY:[/bold]")
        for ts, event, amt in recent:
            # Shorten timestamp for readability
            date = ts.split("T")[0]
            console.print(f" • {date} | {event:<15} | [green]${amt:>8.2f}[/green]")


if __name__ == "__main__":
    get_status()
