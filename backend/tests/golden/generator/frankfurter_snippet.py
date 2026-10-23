# Source: https://frankfurter.dev/

import requests

url = "https://api.frankfurter.dev/v2/rates"
headers = {}
params = {"base": "EUR", "from": "2026-01-01", "quotes": "USD", "to": "2026-01-02"}

response = requests.get(url, headers=headers, params=params, timeout=30, allow_redirects=False)
if 300 <= response.status_code < 400:
    raise RuntimeError("Redirect refused to protect API credentials")
response.raise_for_status()
data = response.json()
