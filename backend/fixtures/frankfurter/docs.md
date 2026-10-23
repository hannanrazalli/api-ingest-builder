# Frankfurter REST API documentary snapshot
Source: https://frankfurter.dev/
API base URL: https://api.frankfurter.dev/v2
GET /rates
No authentication is required. Query base chooses a currency. Query quotes filters quote currencies. Query date selects an ISO date in YYYY-MM-DD form. Query from and to select a date range in ISO form. The response is an array of objects with date, base, quote and rate fields. Narrow the currency filter to keep responses small.
OpenAPI: https://api.frankfurter.dev/v2/openapi.json
