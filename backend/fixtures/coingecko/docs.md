# CoinGecko REST API documentary snapshot
Source: https://docs.coingecko.com/demo/reference/coins-id-market-chart-range
API base URL: https://api.coingecko.com/api/v3
GET /coins/{id}/market_chart/range
Authentication requires the x-cg-demo-api-key header. Obtain a Demo key from https://www.coingecko.com/en/api.
Path id is a string; documented example bitcoin. Required query vs_currency uses usd in the example. Required from and to accept UNIX second timestamps. Returns prices, market_caps and total_volumes as arrays of timestamp/value pairs. Dates outside the Demo plan's supported history can fail; subscription limits apply.
The recorded example uses id bitcoin, vs_currency usd, from 1776787200, to 1777564800. These are examples, not promised service defaults.
