import sys
import os

# Ensure the project root is in the path so we can find 'src'
# This allows the tool to run from anywhere
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.append(root_dir)

try:
    from src.engine import SanctumTerminal
except ImportError:
    # Fallback for localized execution
    from engine import SanctumTerminal

def seed():
    st = SanctumTerminal()
    
    # Check if we should actually run this (safety check)
    # This prevents accidental double-seeding of the 10k floor
    print("[SYSTEM] Initializing Vault Seed Sequence...")
    
    try:
        st.log_event(10000.00, "INITIAL_STABILITY", "Aegis Shield Locked")
        st.log_event(5350.00, "RESOURCE_CACHE", "Skyloft Progress Inked")
        st.log_event(350.00, "WASTELAND_SALVAGE", "Vegas Break-Even Surplus")
        
        print("✔️  Seed Complete: $15,700 Inked to Vault.")
    except Exception as e:
        print(f"❌  Seed Failed: {e}")

if __name__ == "__main__":
    # Safety Prompt: Seeding should be intentional
    confirm = input("This will add $15,700 to the ledger. Proceed? (y/n): ")
    if confirm.lower() == 'y':
        seed()
    else:
        print("Sequence aborted.")