import sqlite3


def add_relic(title, vibe, rating):
    # In a future step, we can have Gemini generate the
    # 'Archetypal Name' automatically via the CLI.
    try:
        conn = sqlite3.connect("vault.db")
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO archive (archetypal_name, vibe, impact_rating) VALUES (?, ?, ?)",
            (title, vibe, rating),
        )
        conn.commit()
        print(f"[✓] Relic Inked: {title}")
    except Exception as e:
        print(f"[!] Database Error: {e}")


if __name__ == "__main__":
    # Test Entry
    add_relic(
        "The Nuclear Mutant’s Vengeance (4K Radioactive Edition)", "Grit Resilience", 7
    )
