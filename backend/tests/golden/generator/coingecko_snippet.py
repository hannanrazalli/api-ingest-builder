# Source: https://docs.coingecko.com/demo/reference/coins-id-market-chart-range
import os

import requests

url = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart/range"
headers = {}
params = {"from": 1767225600, "to": 1767398399, "vs_currency": "usd"}

api_key = os.getenv("COINGECKO_API_KEY")
if not api_key:
    raise RuntimeError("Set COINGECKO_API_KEY in your environment")

headers["x-cg-demo-api-key"] = api_key


response = requests.get(url, headers=headers, params=params, timeout=30, allow_redirects=False)
if 300 <= response.status_code < 400:
    raise RuntimeError("Redirect refused to protect API credentials")
response.raise_for_status()
data = response.json()
