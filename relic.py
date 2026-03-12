import sys

from engine import SanctumTerminal


def add_relic(name, vibe, cost):
    terminal = SanctumTerminal()
    # Log the purchase in the Ledger
    terminal.log_event(float(cost), "RELIC_PURCHASE", f"Acquired: {name}")

    # Add to the Archive
    import sqlite3

    with sqlite3.connect(terminal.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO archive (archetypal_name, vibe, cost) VALUES (?, ?, ?)",
            (name, vibe, float(cost)),
        )
    print(f"✔️ {name} archived and ledger updated.")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python3 relic.py 'Movie Name' 'Vibe' 'Cost'")
    else:
        add_relic(sys.argv[1], sys.argv[2], sys.argv[3])
