import sys
import argparse
import traceback
import subprocess
import os
import sqlite3
from pathlib import Path

# Internal Imports
try:
    from viewport import SanctumViewport
    from vault_engine import DataNode
except ImportError:
    # This handles cases where PYTHONPATH isn't set yet during refactor
    pass


class SanctumCLI:
    def __init__(self):
        self.parser = argparse.ArgumentParser(
            description="SANCTUM TERMINAL: Unified OS"
        )
        self.setup_args()

    def setup_args(self):
        self.parser.add_argument(
            "command",
            nargs="?",
            default="run",
            choices=["run", "test", "status", "reseed"],
            help="The operation mode for the Terminal.",
        )
        self.parser.add_argument(
            "--artifact",
            type=str,
            default="wall",
            help="The specific artifact to inject in 'test' mode.",
        )
        self.parser.add_argument(
            "--burn",
            type=int,
            default=3500,
            help="Monthly burn rate for survival runway calc.",
        )

    def calculate_runway(self, monthly_burn):
        """Integrated from runaway.py"""
        db_path = "sanctum.db"  # Standardizing to the root for status checks
        try:
            with sqlite3.connect(db_path) as conn:
                total = (
                    conn.execute("SELECT SUM(amount) FROM ledger").fetchone()[0] or 0.0
                )
                months = total / monthly_burn
                bar = "█" * min(int((months / 6) * 10), 10) + "░" * (
                    10 - min(int((months / 6) * 10), 10)
                )
                print(
                    f"\n--- SURVIVAL RUNWAY ---\nSTATUS: [{bar}] {months:.1f} Months\n"
                )
        except Exception as e:
            print(f">>> [SYSTEM] Ledger inaccessible: {e}")

    def run_diagnostic(self, artifact):
        """Integrated from launch_viz_test.py"""
        print(f"\n--- [SANCTUM VISUAL DIAGNOSTIC: {artifact.upper()}] ---")
        db_path = Path("data/vault.db")
        if db_path.exists():
            db_path.unlink()
            print(">>> Vault DB purged for clean state.")

        print(f">>> Injecting {artifact} artifact...")
        subprocess.run(
            [sys.executable, "tools/seed_test_object.py", artifact],
            env={**os.environ, "PYTHONPATH": "."},
            check=True,
        )
        self.ignite()

    def ignite(self):
        """The main execution loop from sanctum.py"""
        print("--- [IGNITING SANCTUM VIEWPORT] ---")
        try:
            viewport = SanctumViewport()
            viewport.run()
        except Exception:
            print("\n>>> [CRITICAL] ENGINE SHUTDOWN")
            traceback.print_exc()

    def execute(self):
        args = self.parser.parse_args()

        if args.command == "status":
            self.calculate_runway(args.burn)
        elif args.command == "test":
            self.run_diagnostic(args.artifact)
        elif args.command == "reseed":
            # Direct hook for biome-level seeding in the future
            subprocess.run(
                [sys.executable, "tools/seed_vault.py"],
                env={**os.environ, "PYTHONPATH": "."},
            )
        else:
            self.ignite()


if __name__ == "__main__":
    cli = SanctumCLI()
    cli.execute()
