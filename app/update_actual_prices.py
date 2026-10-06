from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo
from datetime import datetime
import re
import csv
import json
import math
import hashlib

import pandas as pd
import exchange_calendars as xcals
from dataclasses import dataclass
from urllib.request import Request, urlopen


DATA_DIR = Path(__file__).resolve().parents[1] / "data"
ACTUALS_FILE = DATA_DIR / "oslo_actual_prices.csv"
EURONEXT_URL = "https://live.euronext.com/pd_es/data/stocks/download?mics=XOSL"
OSLO_TZ = ZoneInfo("Europe/Oslo")


def normalize_column(name: str) -> str:
    return str(name).strip().lower().replace("/", "_").replace(" ", "_")


def parse_price(value) -> float | None:
    if value is None:
        return None

    raw = str(value).strip().replace("\xa0", "").replace(" ", "")
    if not raw or raw == "-":
        return None

    raw = re.sub(r"[^0-9,.\-]", "", raw)
    if raw.count(",") > 0 and raw.count(".") > 0:
        raw = (raw.replace(".", "").replace(",", ".") if raw.rfind(",") > raw.rfind(".")
               else raw.replace(",", ""))
    elif raw.count(",") > 0:
        raw = raw.replace(",", ".")

    try:
        value = float(raw)
        return value if math.isfinite(value) and value > 0 else None
    except ValueError:
        return None


def fetch_csv_text() -> str:
    request = Request(
        EURONEXT_URL,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/csv,text/plain,*/*",
        },
    )
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8-sig", errors="replace")


@dataclass(frozen=True)
class ActualRow:
    date: str
    ticker: str
    price: float


def parse_closing_date(value: str) -> str | None:
    """Only explicit calendar dates; a time-of-day or download date is insufficient."""
    raw = str(value or "").strip()
    if not re.search(r"\d{4}", raw):
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            pass
    try:
        stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if stamp.tzinfo:
            stamp = stamp.astimezone(OSLO_TZ)
        return stamp.date().isoformat()
    except ValueError:
        return None


def parse_actual_rows(text: str, oslo_date: str, now=None) -> tuple[list[ActualRow], list[dict]]:
    lines = [line for line in text.splitlines() if line.strip()]
    header_index = next((i for i,line in enumerate(lines) if "Symbol" in line and "Closing Price" in line), None)
    if header_index is None:
        raise RuntimeError("Missing closing-price headers in the Euronext download")
    reader = csv.DictReader(lines[header_index:], delimiter=";")
    columns = {normalize_column(name):name for name in (reader.fieldnames or [])}
    required = {"symbol", "closing_price", "closing_price_datetime", "currency"}
    if not required.issubset(columns):
        raise RuntimeError("Closing price, explicit closing timestamp and currency are required")
    now = pd.Timestamp(now or datetime.now(OSLO_TZ))
    if now.tzinfo is None: raise ValueError("now must include timezone")
    results, rejected, seen = [], [], set()
    for row in reader:
        ticker = (row.get(columns['symbol']) or '').strip().upper()
        if not ticker: continue
        date = parse_closing_date(row.get(columns['closing_price_datetime']))
        price = parse_price(row.get(columns['closing_price']))
        reason = None
        if date is None: reason = 'missing_explicit_closing_date'
        elif date > oslo_date: reason = 'future_closing_date'
        elif (row.get(columns['currency']) or '').strip().upper() != 'NOK': reason = 'unexpected_currency'
        elif price is None: reason = 'invalid_closing_price'
        else:
            cal = xcals.get_calendar('XOSL',start=pd.Timestamp(date)-pd.Timedelta(days=7),end=pd.Timestamp(date)+pd.Timedelta(days=7))
            if not cal.is_session(date): reason = 'not_exchange_session'
            elif cal.session_close(date) + pd.Timedelta(minutes=30) > now: reason = 'session_not_final'
        if reason:
            rejected.append({'ticker':ticker,'reason':reason})
            continue
        key = (date,ticker)
        if key in seen: continue
        seen.add(key)
        results.append(ActualRow(date=date,ticker=ticker,price=price))
    return results, rejected


def fetch_actual_rows(oslo_date: str) -> list[ActualRow]:
    text = fetch_csv_text()
    rows, rejected = parse_actual_rows(text, oslo_date)
    DATA_DIR.mkdir(parents=True,exist_ok=True)
    (DATA_DIR/'quote_refresh_audit.json').write_text(json.dumps({
        'fetched_at':datetime.now(OSLO_TZ).isoformat(), 'source_url':EURONEXT_URL,
        'source_sha256':hashlib.sha256(text.encode()).hexdigest(),
        'accepted':len(rows),'rejected':rejected},indent=2))
    if not rows:
        raise RuntimeError("No verified, completed-session closing prices. Refusing to stamp last quotes with today's date. Use forecasting/repair_history.py for session-dated history.")
    return rows


def read_existing_actuals() -> dict[tuple[str, str], float]:
    if not ACTUALS_FILE.exists():
        return {}

    existing: dict[tuple[str, str], float] = {}
    with ACTUALS_FILE.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            date = (row.get("date") or "").strip()
            ticker = (row.get("ticker") or "").strip().upper()
            if not date or not ticker:
                continue
            price = parse_price(row.get("price"))
            if price is None:
                continue
            existing[(date, ticker)] = float(price)
    return existing


def write_actuals(rows: dict[tuple[str, str], float]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temporary = ACTUALS_FILE.with_suffix(".csv.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "ticker", "price"])
        writer.writeheader()
        for (date, ticker), price in sorted(rows.items(), key=lambda item: (item[0][0], item[0][1])):
            writer.writerow({"date": date, "ticker": ticker, "price": price})

    temporary.replace(ACTUALS_FILE)


def upsert_actuals() -> list[ActualRow]:
    oslo_date = datetime.now(OSLO_TZ).date().isoformat()
    new_rows = fetch_actual_rows(oslo_date=oslo_date)

    existing = read_existing_actuals()
    for row in new_rows:
        existing[(row.date, row.ticker)] = row.price

    write_actuals(existing)
    return new_rows


def main() -> None:
    try:
        rows = upsert_actuals()
    except Exception as exc:
        raise SystemExit(f"Oslo actual-price refresh failed: {exc}") from exc

    print(f"Saved {len(rows)} Oslo actual price rows to {ACTUALS_FILE}")


if __name__ == "__main__":
    main()
