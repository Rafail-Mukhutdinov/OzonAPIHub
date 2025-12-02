import sqlite3
import os

DB = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'orders.db')

print('Using DB:', DB)
conn = sqlite3.connect(DB)
c = conn.cursor()

# Count rows
c.execute('SELECT COUNT(*) FROM orders')
count = c.fetchone()[0]
print('Total rows:', count)

# Min/max created_at
try:
    c.execute("SELECT MIN(created_at), MAX(created_at) FROM orders")
    mn, mx = c.fetchone()
    print('Min created_at:', mn)
    print('Max created_at:', mx)
except Exception as e:
    print('Error getting min/max created_at:', e)

# List all created_at values and ids
print('\nAll rows (id | posting_number | created_at):')
for row in c.execute("SELECT id, posting_number, created_at FROM orders ORDER BY created_at ASC, id ASC"):
    print(row)

# Also show count grouped by created_at
print('\nCounts by created_at:')
for row in c.execute("SELECT created_at, COUNT(*) FROM orders GROUP BY created_at ORDER BY created_at ASC"):
    print(row)

conn.close()