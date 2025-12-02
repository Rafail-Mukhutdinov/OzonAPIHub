import sys, os, sqlite3
try:
    import requests
except ImportError:
    print("[error] Модуль 'requests' не установлен. Установите: pip install requests")
    raise

ROOT = os.path.dirname(os.path.dirname(__file__))
DB = os.path.join(ROOT, 'orders.db')
BASE = 'http://127.0.0.1:8000'
API = BASE + '/sync/history'

if len(sys.argv) < 2:
    print('Usage: python scripts/reconcile_month.py YYYY-MM')
    sys.exit(1)

month = sys.argv[1]
year, mon = month.split('-')
year = int(year); mon = int(mon)

from datetime import datetime
start = datetime(year, mon, 1).isoformat() + 'Z'
# end: last day of month
if mon == 12:
    end_dt = datetime(year+1, 1, 1)
else:
    end_dt = datetime(year, mon+1, 1)
end = (end_dt.replace(microsecond=0).isoformat() + 'Z')

print(f'Reconcile month {month}: {start} -> {end}')

# check server availability
def ping_server(base_url: str) -> bool:
    try:
        r = requests.get(base_url + '/ping', timeout=3)
        return r.status_code == 200
    except Exception:
        return False

if not ping_server(BASE):
    print("[error] Сервер не запущен на http://127.0.0.1:8000. Запустите:\n  python -m uvicorn main:app --reload")
    sys.exit(1)

# before counts
conn = sqlite3.connect(DB)
c = conn.cursor()
c.execute("SELECT COUNT(*) FROM orders WHERE substr(created_at,1,7)=?", (month,))
before = c.fetchone()[0]
print('Local before count:', before)
conn.close()

# call API
payload = {'start': start, 'end': end}
resp = requests.post(API, params=payload, timeout=300)
print('API status:', resp.status_code)
try:
    print('API result summary windows:', resp.json().get('windows')[:1], '...')
except Exception:
    print('API response text:', resp.text[:300])

# after counts
conn = sqlite3.connect(DB)
c = conn.cursor()
c.execute("SELECT COUNT(*) FROM orders WHERE substr(created_at,1,7)=?", (month,))
after = c.fetchone()[0]
print('Local after count:', after)
print('Delta:', after - before)
conn.close()
