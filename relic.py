import sys
# Use relative import for the new directory structure
try:
    from .engine import SanctumTerminal
except ImportError:
    from engine import SanctumTerminal

def add_relic(name: str, vibe: str, cost: float):
    """Interfaces with the Engine to execute an Atomic Acquisition."""
    terminal = SanctumTerminal()
    
    try:
        # We now use the engine's built-in atomic method instead of 
        # writing manual SQL here. This ensures the ledger and 
        # archive are always in sync.
        terminal.acquire_relic(name, vibe, cost)
        print(f"✔️  [SUCCESS] {name} archived and ledger updated.")
    except Exception as e:
        print(f"❌  [FAILURE] Could not archive relic: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python3 -m src.relic 'Movie Name' 'Vibe' 'Cost'")
    else:
        # Cast cost to float here to catch errors early
        try:
            name_arg = sys.argv[1]
            vibe_arg = sys.argv[2]
            cost_arg = float(sys.argv[3])
            add_relic(name_arg, vibe_arg, cost_arg)
        except ValueError:
            print("❌  [ERROR] Cost must be a number.")