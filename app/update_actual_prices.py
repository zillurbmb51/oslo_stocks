from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo
from datetime import datetime
import re
from io import StringIO
from urllib.request import Request, urlopen

import pandas as pd


DATA_DIR = Path(__file__).resolve().parents[1] / "data"
ACTUALS_FILE = DATA_DIR / "oslo_actual_prices.csv"
EURONEXT_URL = "https://live.euronext.com/pd_es/data/stocks/download?mics=XOSL"
OSLO_TZ = ZoneInfo("Europe/Oslo")


def normalize_columns(columns) -> list[str]:
    return [str(col).strip().lower().replace("/", "_").replace(" ", "_") for col in columns]


def parse_price(value) -> float | None:
    if pd.isna(value):
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


def fetch_actual_table() -> pd.DataFrame:
    text = fetch_csv_text()
    lines = [line for line in text.splitlines() if line.strip()]
    header_index = next(
        (idx for idx, line in enumerate(lines) if "Symbol;" in line and "last Price" in line),
        None,
    )
    if header_index is None:
        raise RuntimeError("Could not find Symbol/last Price headers in the Euronext download.")

    csv_text = "\n".join(lines[header_index:])
    df = pd.read_csv(StringIO(csv_text), sep=";")
    df.columns = normalize_columns(df.columns)
    if not {"symbol", "last_price"}.issubset(df.columns):
        raise RuntimeError("The Euronext download is missing symbol/last price columns.")
    return df


def build_actual_rows() -> pd.DataFrame:
    df = fetch_actual_table()
    df = df[["symbol", "last_price"]].copy()
    df["ticker"] = df["symbol"].astype(str).str.strip().str.upper()
    df["price"] = df["last_price"].apply(parse_price)
    df = df.dropna(subset=["ticker", "price"])
    df = df[df["ticker"] != ""]
    df["date"] = datetime.now(OSLO_TZ).date().isoformat()
    return df[["date", "ticker", "price"]].drop_duplicates(subset=["date", "ticker"], keep="last")


def upsert_actuals() -> pd.DataFrame:
    new_rows = build_actual_rows()

    if ACTUALS_FILE.exists():
        existing = pd.read_csv(ACTUALS_FILE, dtype={"ticker": "string"})
    else:
        existing = pd.DataFrame(columns=["date", "ticker", "price"])

    combined = pd.concat([existing, new_rows], ignore_index=True)
    combined["ticker"] = combined["ticker"].astype(str).str.strip().str.upper()
    combined = combined.dropna(subset=["date", "ticker", "price"])
    combined["price"] = pd.to_numeric(combined["price"], errors="coerce")
    combined = combined.dropna(subset=["price"])
    combined = combined.sort_values(["date", "ticker"])
    combined = combined.drop_duplicates(subset=["date", "ticker"], keep="last")
    combined.to_csv(ACTUALS_FILE, index=False)
    return new_rows


def main() -> None:
    rows = upsert_actuals()
    print(f"Saved {len(rows)} Oslo actual price rows to {ACTUALS_FILE}")


if __name__ == "__main__":
    main()
