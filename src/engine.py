import sqlite3
import os
from rich.console import Console
from rich.panel import Panel

console = Console()

class SanctumTerminal:
    def __init__(self, db_path: str = None, debug: bool = False):
        self.debug = debug
        # ... (Path resolution logic remains the same)
        self.db_path = self._resolve_path(db_path)
        self._boot_sequence()

    def _execute(self, query, params=(), commit=False):
        """The Telemetry Wrapper for SQL traffic."""
        if self.debug:
            console.print(Panel(
                f"[bold magenta]SQL REQUEST[/bold magenta]\n[white]{query}[/white]\n"
                f"[cyan]PARAMS:[/cyan] {params}",
                title="[bold]DATA WIRE[/bold]", border_style="magenta"
            ))
            
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            result = cursor.fetchall()
            if commit:
                conn.commit()
            
            if self.debug:
                console.print(f"[bold green]SQL RESPONSE:[/bold green] {len(result)} rows returned/affected\n")
            return result

    # Update your log_event to use the wrapper:
    def log_event(self, amount, event_type, note):
        query = "INSERT INTO ledger (timestamp, amount, event_type, note) VALUES (?, ?, ?, ?)"
        params = (datetime.now().isoformat(), float(amount), event_type, note)
        self._execute(query, params, commit=True)