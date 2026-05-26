from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo
from datetime import datetime
import re
import csv
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
        raw = raw.replace(".", "").replace(",", ".")
    elif raw.count(",") > 0:
        raw = raw.replace(",", ".")

    try:
        return float(raw)
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


def fetch_actual_rows(oslo_date: str) -> list[ActualRow]:
    text = fetch_csv_text()
    lines = [line for line in text.splitlines() if line.strip()]
    header_index = next(
        (idx for idx, line in enumerate(lines) if "Symbol;" in line and "last Price" in line),
        None,
    )
    if header_index is None:
        raise RuntimeError("Could not find Symbol/last Price headers in the Euronext download.")

    csv_text = "\n".join(lines[header_index:])
    reader = csv.DictReader(csv_text.splitlines(), delimiter=";")
    if reader.fieldnames is None:
        raise RuntimeError("Euronext download did not contain a CSV header row.")

    normalized_to_original: dict[str, str] = {normalize_column(name): name for name in reader.fieldnames}
    if not {"symbol", "last_price"}.issubset(normalized_to_original.keys()):
        raise RuntimeError("The Euronext download is missing symbol/last price columns.")

    symbol_key = normalized_to_original["symbol"]
    last_price_key = normalized_to_original["last_price"]

    results: list[ActualRow] = []
    seen: set[tuple[str, str]] = set()
    for row in reader:
        ticker = (row.get(symbol_key) or "").strip().upper()
        if not ticker:
            continue
        price = parse_price(row.get(last_price_key))
        if price is None:
            continue

        key = (oslo_date, ticker)
        if key in seen:
            continue
        seen.add(key)
        results.append(ActualRow(date=oslo_date, ticker=ticker, price=price))

    return results


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
    with ACTUALS_FILE.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "ticker", "price"])
        writer.writeheader()
        for (date, ticker), price in sorted(rows.items(), key=lambda item: (item[0][0], item[0][1])):
            writer.writerow({"date": date, "ticker": ticker, "price": price})


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
