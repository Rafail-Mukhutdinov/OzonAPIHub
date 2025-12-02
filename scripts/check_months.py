import sys, os, sqlite3
ROOT = os.path.dirname(os.path.dirname(__file__))
DB = os.path.join(ROOT, 'orders.db')

conn = sqlite3.connect(DB)
c = conn.cursor()

months = [
    ('2025-09', 'September 2025'),
    ('2025-10', 'October 2025'),
    ('2025-11', 'November 2025'),
    ('2025-12', 'December 2025'),
]

for pref, label in months:
    c.execute("SELECT COUNT(*) FROM orders WHERE substr(created_at,1,7)=?", (pref,))
    cnt = c.fetchone()[0]
    print(f"{label}: {cnt} rows")

# show min/max created_at for quick sanity
c.execute("SELECT MIN(created_at), MAX(created_at) FROM orders")
mn, mx = c.fetchone()
print("Min created_at:", mn)
print("Max created_at:", mx)

conn.close()
