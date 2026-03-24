import sqlite3
from pathlib import Path
from rich.console import Console

console = Console()

class RelicVault:
    def __init__(self, db_name="data/vault.db"):
        self.db_path = Path(db_name)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def init_db(self):
        """Creates the tables for our Voxel Max relics."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS relics (
                    hash TEXT PRIMARY KEY,
                    filename TEXT,
                    biome_tag TEXT,
                    strain_score FLOAT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
        console.log(f"[bold green]Vault Initialized:[/bold green] {self.db_path}")

    def register_relic(self, file_hash, filename, biome="default"):
        """Saves a tested object to the permanent seed database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT OR IGNORE INTO relics (hash, filename, biome_tag) VALUES (?, ?, ?)",
                    (file_hash, filename, biome)
                )
                conn.commit()
            return True
        except Exception as e:
            console.log(f"[red]Vault Error:[/red] {e}")
            return False