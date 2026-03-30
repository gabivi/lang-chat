"""One-time migration: add gender column to users table if missing."""
import sqlite3, os

DB = os.getenv("DATABASE_URL", "companion.db").replace("sqlite:///", "")

conn = sqlite3.connect(DB)
cur  = conn.cursor()

cols = [row[1] for row in cur.execute("PRAGMA table_info(users)")]
if "gender" not in cols:
    cur.execute("ALTER TABLE users ADD COLUMN gender TEXT DEFAULT 'unknown'")
    conn.commit()
    print("Added 'gender' column to users table.")
else:
    print("'gender' column already exists — nothing to do.")

conn.close()
