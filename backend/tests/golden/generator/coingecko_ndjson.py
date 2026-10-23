# Generated deterministically from a source-backed API specification.
# Review the source and API plan limits before running. Credentials are environment-only.
import json
import logging
import os
import time
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
BASE_URL = "https://api.coingecko.com/api/v3"
ENDPOINT = "/coins/{id}/market_chart/range"
NAME = "coingecko"
SOURCE_URL = "https://docs.coingecko.com/demo/reference/coins-id-market-chart-range"
BASE_PARAMS = {"from": 1767225600, "to": 1767398399, "vs_currency": "usd"}
BASE_HEADERS = {}
PATH_PARAMS = {"id": "bitcoin"}
RECORD_PATH = "prices"
PAGINATION = None
CURSOR_NEXT_PATH = None
DATE_PARAMS = {"end": "to", "format": "unix", "start": "from", "strftime": None}
MIN_INTERVAL = 0
SKIP_EXISTING = False
FLATTEN = True
MAX_PAGES = 1000


def _at(value, path):
    if not path or path == "$":
        return value
    for key in path.split("."):
        value = value[key]
    return value


def _records(payload):
    records = _at(payload, RECORD_PATH)
    if isinstance(records, dict):
        return [records]
    if not isinstance(records, list):
        raise ValueError("Record path must select a JSON object or array")
    return records


def _flatten(value, prefix=""):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            result.update(_flatten(item, f"{prefix}.{key}".strip(".")))
        return result
    if isinstance(value, (list, tuple)):
        result = {}
        for index, item in enumerate(value):
            result.update(_flatten(item, f"{prefix}.{index}".strip(".")))
        return result
    return {prefix or "value": value}


def to_ndjson(records):
    return "\n".join(
        json.dumps(_flatten(row) if FLATTEN else row, sort_keys=True) for row in records
    )


def _date(value, end=False):
    dt = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
    if DATE_PARAMS and DATE_PARAMS["format"] in {"unix", "unix_ms"}:
        if end:
            dt += timedelta(days=1) - timedelta(seconds=1)
        return int(dt.timestamp()) * (1000 if DATE_PARAMS["format"] == "unix_ms" else 1)
    return dt.strftime((DATE_PARAMS or {}).get("strftime") or "%Y-%m-%d")


def _headers_params():
    headers, params = dict(BASE_HEADERS), dict(BASE_PARAMS)

    api_key = os.getenv("COINGECKO_API_KEY")
    if not api_key:
        raise RuntimeError("Set COINGECKO_API_KEY in your environment")

    headers["x-cg-demo-api-key"] = api_key

    return headers, params


def _get(url, headers, params):
    if urlsplit(url).hostname != urlsplit(BASE_URL).hostname:
        raise ValueError("Pagination URL cannot leave the documented API host")
    if urlsplit(BASE_URL).scheme == "https" and urlsplit(url).scheme != "https":
        raise ValueError("HTTPS downgrade blocked")
    for attempt in range(5):
        time.sleep(MIN_INTERVAL)
        try:
            response = requests.get(
                url, headers=headers, params=params, timeout=30, allow_redirects=False
            )
        except (requests.Timeout, requests.ConnectionError):
            if attempt == 4:
                raise
            time.sleep(min(60, 2**attempt))
            continue
        if response.status_code in {429, 500, 502, 503, 504} and attempt < 4:
            retry = response.headers.get("Retry-After", "")
            try:
                delay = float(retry)
            except ValueError:
                try:
                    delay = (parsedate_to_datetime(retry) - datetime.now(UTC)).total_seconds()
                except (TypeError, ValueError):
                    delay = 2**attempt
            time.sleep(max(0, delay))
            continue
        if 300 <= response.status_code < 400:
            raise RuntimeError("Redirect refused to protect API credentials")
        response.raise_for_status()
        return response
    raise RuntimeError("Retry limit exceeded")


def fetch_records(start_date=None, end_date=None):
    headers, params = _headers_params()
    path = ENDPOINT
    for key, value in PATH_PARAMS.items():
        from urllib.parse import quote

        path = path.replace("{" + key + "}", quote(str(value), safe=""))
    if DATE_PARAMS and start_date:
        params[DATE_PARAMS["start"]] = _date(start_date)
        if DATE_PARAMS["end"]:
            params[DATE_PARAMS["end"]] = _date(end_date or start_date, end=True)
    url = BASE_URL.rstrip("/") + path
    records, seen = [], set()
    for _ in range(MAX_PAGES):
        marker = json.dumps([url, params], sort_keys=True)
        if marker in seen:
            raise RuntimeError("Pagination repeated a cursor or URL")
        seen.add(marker)
        response = _get(url, headers, params)
        payload = response.json()
        page = _records(payload)
        records.extend(page)
        if not PAGINATION or not page:
            break
        kind, parameter = PAGINATION["type"], PAGINATION["param"]
        if kind == "link_header":
            link = response.links.get("next", {}).get("url")
            if not link:
                break
            url = urljoin(url, link)
            params = {}
        elif kind == "cursor":
            cursor = _at(payload, CURSOR_NEXT_PATH)
            if cursor is None or cursor == "":
                break
            params[parameter] = cursor
        else:
            initial = 1 if kind == "page" else 0
            params[parameter] = int(params.get(parameter, initial)) + (
                1 if kind == "page" else len(page)
            )
    else:
        raise RuntimeError("Maximum pagination pages exceeded")
    return records


def coingecko(ds: str | None = None, end_date: str | None = None):
    ds = ds or datetime.now(tz=UTC).strftime("%Y-%m-%d")
    dt = datetime.strptime(ds, "%Y-%m-%d").replace(tzinfo=UTC)
    key = f"raw/{NAME}/year={dt:%Y}/month={dt:%m}/day={dt:%d}/{NAME}_{dt:%Y%m%d}.ndjson"

    target = Path(key)
    if SKIP_EXISTING and target.exists():
        return []
    records = fetch_records(ds, end_date)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(to_ndjson(records), encoding="utf-8")
    temporary.replace(target)

    logger.info("Successfully ingested partition %s", ds)
    return records


def backfill(start_date, end_date, chunk_days=1):
    start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=UTC)
    finish = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=UTC)
    if finish < start:
        raise ValueError("end_date must be on or after start_date")
    while start <= finish:
        stop = min(finish, start + timedelta(days=chunk_days - 1))
        coingecko(start.strftime("%Y-%m-%d"), stop.strftime("%Y-%m-%d"))
        start = stop + timedelta(days=1)


if __name__ == "__main__":
    print(to_ndjson(fetch_records("2026-01-01", "2026-01-02")))
