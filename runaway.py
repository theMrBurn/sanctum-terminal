import sqlite3


def calculate_runway(monthly_burn=3500):
    db_path = "vault.db"
    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT SUM(amount) FROM ledger")
            total = cursor.fetchone()[0] or 0.0

            months = total / monthly_burn

            # Create a simple visual progress bar (10 segments)
            # Assuming a "Safe" runway is 6 months
            segments = min(int((months / 6) * 10), 10)
            bar = "█" * segments + "░" * (10 - segments)

            print("\n" + "--- SURVIVAL RUNWAY ---")
            print(f" MONTHLY BURN:  ${monthly_burn:,.2f}")
            print(f" TOTAL CACHE:   ${total:,.2f}")
            print(f" STATUS:        [{bar}] {months:.1f} Months")

            if months < 3:
                print(" ALERT: Stability low. Prioritize Logic-Contracts.")
            else:
                print(" STATUS: Aegis holds. Stability optimal.")
            print("-" * 23 + "\n")

    except Exception as e:
        print(f"Error calculating runway: {e}")


if __name__ == "__main__":
    # You can change 3500 to your actual estimated Portland monthly cost
    calculate_runway(3500)
