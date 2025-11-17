import sqlite3

def save_ticket(store, date, total, currency, raw_text, category=None, payment_method=None):
    conn = sqlite3.connect("data/tickets.db")
    c = conn.cursor()
    c.execute("""
        INSERT INTO tickets (store, date, total, currency, category, payment_method, raw_text)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (store, date, float(total) if total else None, currency or "MXN",
          category, payment_method, raw_text))
    conn.commit()
    conn.close()
    print(f"💾 Ticket guardado: {store or '—'} | {date or '—'} | {total or '—'} {currency or 'MXN'}")
