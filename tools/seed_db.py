#!/usr/bin/env python3
"""
tools/seed_db.py
Initializes vault.db schema. Safe to run multiple times.
"""
import sqlite3
from pathlib import Path

db = Path("data/vault.db")
db.parent.mkdir(exist_ok=True)

conn = sqlite3.connect(db)
conn.execute("""
    CREATE TABLE IF NOT EXISTS archive (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        archetypal_name TEXT NOT NULL,
        vibe            TEXT,
        impact_rating   INTEGER DEFAULT 1
    )
""")
conn.execute("""
    CREATE TABLE IF NOT EXISTS seeds (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        label           TEXT,
        seed_hash       TEXT UNIQUE NOT NULL,
        status          TEXT DEFAULT 'exploring',
        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        snapshot        TEXT,
        consent_version TEXT DEFAULT '1.0'
    )
""")
conn.execute("""
    CREATE TABLE IF NOT EXISTS grace_log (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        event_type TEXT NOT NULL,
        payload    TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")
conn.commit()
conn.close()
print("vault.db schema initialized — archive, seeds, grace_log.")
