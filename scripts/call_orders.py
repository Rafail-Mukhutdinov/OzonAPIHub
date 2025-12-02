import requests
params = {
    'since': '2025-12-01T00:00:00Z',
    'to': '2025-12-02T23:59:59Z',
    'limit': 50,
    'offset': 0
}
resp = requests.post('http://127.0.0.1:8000/orders/fbo', params=params, json={})
print('STATUS', resp.status_code)
try:
    print(resp.json())
except Exception:
    print(resp.text)
