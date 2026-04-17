"""One-time migration: add gender, language, and level columns to users table if missing."""
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
    print("'gender' column already exists.")

if "language" not in cols:
    cur.execute("ALTER TABLE users ADD COLUMN language TEXT DEFAULT 'he'")
    conn.commit()
    print("Added 'language' column to users table.")
else:
    print("'language' column already exists.")

if "level" not in cols:
    cur.execute("ALTER TABLE users ADD COLUMN level TEXT DEFAULT 'intermediate'")
    conn.commit()
    print("Added 'level' column to users table.")
else:
    print("'level' column already exists.")

conn.close()
