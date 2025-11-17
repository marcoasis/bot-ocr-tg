import os, sqlite3

os.makedirs("data", exist_ok=True)
conn = sqlite3.connect("data/tickets.db")
c = conn.cursor()

c.execute("PRAGMA journal_mode=WAL;")
c.execute("PRAGMA synchronous=NORMAL;")

c.execute("""
CREATE TABLE IF NOT EXISTS tickets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  store TEXT,
  date TEXT,
  total REAL,
  currency TEXT,
  category TEXT,
  payment_method TEXT,
  raw_text TEXT,
  created_at TEXT DEFAULT (datetime('now','localtime'))
)
""")

conn.commit()
conn.close()
print("✅ Base de datos lista en data/tickets.db")
