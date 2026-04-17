import re
from pathlib import Path
from typing import Dict, List, Any

import pandas as pd

# Base data paths
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
RATIONALES_FILE = DATA_DIR / "ticker_rationales_osl_parallel.csv"
HISTORY_FILE = DATA_DIR / "oslo_stock_exchange_all_companies.xlsx"
ACTUALS_FILE = DATA_DIR / "oslo_actual_prices.csv"


# -----------------------------
# Commentary cleaning
# -----------------------------
def clean_comment(raw: str) -> str:
    """
    Clean a raw comment string like the ones in the file segments
    (e.g. AZT, JIN, BRG, NAS, SOMA, SB1NO, etc.).
    Removes boilerplate, separators, and ``` blocks
    <ref: index={3344531} firstWord={1} lastWord={34}/>
    <ref: index={3344373} firstWord={43} lastWord={54}/>.
    """
    if not isinstance(raw, str):
        return ""

    text = raw

    # Remove leading boilerplate "in plain text, without bullet points."
    text = re.sub(
        r"^in plain text, without bullet points\.\s*[_\-`]*\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )

    # Remove separator lines and fenced code markers like ```text, ```plain
    lines = text.splitlines()
    cleaned_lines: List[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            cleaned_lines.append(stripped)
            continue
        if re.fullmatch(r"_+", stripped):
            continue
        if re.fullmatch(r"-{3,}", stripped):
            continue
        if stripped.startswith("```"):
            continue
        cleaned_lines.append(line)

    text = "\n".join(cleaned_lines)

    # Remove boilerplate "Here is the commentary" etc.
    text = re.sub(
        r"Here is (the|your)?\s*commentary:\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )

    # Collapse excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def load_rationales() -> Dict[str, str]:
    """
    Load ticker_rationales_osl_parallel.csv and return
      { TICKER: clean_comment }
    where TICKER matches the 'ticker' strings used in
    your forecast CSVs and history sheet names.
    """
    df_raw = pd.read_csv(
        RATIONALES_FILE,
        engine="python",
        quotechar='"',
        sep=",",
        on_bad_lines="warn",
        encoding="latin-1",
        dtype={"ticker": "string"},
    )

    df_raw["clean_comment"] = df_raw["comment"].apply(clean_comment)

    # Normalize ticker: trim + uppercase only.
    # DO NOT strip ".OL" etc., because you said tickers in all CSVs match
    # sheet names in the history file.
    df_raw["ticker_norm"] = (
        df_raw["ticker"]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    df_unique = (
        df_raw
        .dropna(subset=["clean_comment"])
        .drop_duplicates(subset=["ticker_norm", "clean_comment"])
        .sort_values("run_start")
        .groupby("ticker_norm", as_index=False)
        .agg({"clean_comment": "first"})
    )

    return dict(zip(df_unique["ticker_norm"], df_unique["clean_comment"]))


# -----------------------------
# Forecast loader
# -----------------------------

def load_multi_run_forecasts() -> Dict[str, List[Dict[str, Any]]]:
    """
    Load all forecast runs from my_new_predictions_osl_*.csv files in data/.

    - Each file is one run (identified by a 'run_index' column or by
      the _runX in the filename).
    - Each row is a ticker with price_* horizon columns.

    Output:
      {
        "2020": [
          {"run_index": 1, "horizons": [...], "values": [...]},
          {"run_index": 2, "horizons": [...], "values": [...]},
          ...
        ],
        "AZT": [...],
        ...
      }
    """
    pattern = "my_new_predictions_osl_*_run*.csv"
    ticker_to_runs: Dict[str, List[Dict[str, Any]]] = {}

    # Map "frontend horizon label" → "CSV column name"
    horizon_map = [
        ("24h", "price_24h"),
        ("48h", "price_48h"),
        ("1w", "price_1w"),
        ("2w", "price_2w"),
        ("3w", "price_3w"),
        ("1m", "price_1m"),
        ("2m", "price_2m"),
        ("3m", "price_3m"),
        ("6m", "price_6m"),
        ("1y", "price_1y"),
        ("2y", "price_2y"),
        ("3y", "price_3y"),
        ("4y", "price_4y"),
        ("5y", "price_5y"),
    ]

    for path in DATA_DIR.glob(pattern):
        df = pd.read_csv(path,sep='\t')

        # Determine which price_* columns are present
        available = [(h_label, col) for (h_label, col) in horizon_map if col in df.columns]
        if not available:
            # This file has no usable forecast horizons
            continue

        # Run index: from column if present, else from filename
        run_index: int
        if "run_index" in df.columns and not df["run_index"].isna().all():
            try:
                run_index = int(df["run_index"].iloc[0])
            except Exception:
                run_index = 0
        else:
            # Try parse from filename e.g. ..._run3.csv
            run_index = 0
            m = re.search(r"_run(\d+)\.csv$", path.name)
            if m:
                try:
                    run_index = int(m.group(1))
                except Exception:
                    run_index = 0

        for _, row in df.iterrows():
            raw_ticker = str(row.get("ticker", "")).strip()
            if not raw_ticker:
                continue
            # Normalize: uppercase only, no stripping of ".OL"
            base_ticker = raw_ticker.upper()

            horizons: List[str] = []
            values: List[float] = []

            for h_label, col in available:
                val = row.get(col, None)
                if pd.isna(val):
                    continue
                try:
                    v = float(val)
                except (TypeError, ValueError):
                    continue
                horizons.append(h_label)
                values.append(v)

            if not horizons:
                continue

            run_dict = {
                "run_index": run_index,
                "horizons": horizons,
                "values": values,
            }

            ticker_to_runs.setdefault(base_ticker, []).append(run_dict)

    return ticker_to_runs


# -----------------------------
# History loader
# -----------------------------
def load_history() -> Dict[str, Dict[str, List[Any]]]:
    """
    Load historical close prices from oslo_stock_exchange_all_companies.xlsx.

    - One sheet per ticker; you said sheet names match your ticker strings.
    - Row 0: ["Price", "Close", "High", "Low", "Open", "Volume"]
    - Row 1: ["Ticker", "<TICKER>", ...]
    - Index: "Date"

    Returns:
      {
        "2020": {
          "dates": [...],
          "closes": [...]
        },
        ...
      }
    """
    all_sheets = pd.read_excel(
        HISTORY_FILE,
        sheet_name=None,
        header=[0, 1],
        index_col=0,
    )

    history: Dict[str, Dict[str, List[Any]]] = {}

    for sheet_name, df in all_sheets.items():
        # Use the sheet name directly as ticker key, normalized.
        base_ticker = str(sheet_name).strip().upper()

        # Find a "Close" column in the top-level of the MultiIndex
        close_col = None
        for col in df.columns:
            lvl0, lvl1 = col
            if str(lvl0).strip().lower() == "close":
                close_col = col
                break

        if close_col is None:
            continue

        df_reset = df.reset_index()
        date_col_name = df_reset.columns[0]
        df_hist = df_reset[[date_col_name, close_col]].copy()
        df_hist.columns = ["Date", "Close"]

        df_hist = df_hist.dropna(subset=["Date", "Close"])
        df_hist["Date"] = pd.to_datetime(df_hist["Date"])

        df_hist["Close"] = (
            df_hist["Close"]
            .astype(str)
            .str.replace(",", ".", regex=False)
            .astype(float)
        )

        df_hist = df_hist.sort_values("Date")

        history[base_ticker] = {
            "dates": df_hist["Date"].dt.strftime("%Y-%m-%d").tolist(),
            "closes": df_hist["Close"].tolist(),
        }

    return history


def load_actual_prices() -> Dict[str, Dict[str, List[Any]]]:
    """
    Load locally stored post-forecast actual prices captured from Euronext.

    Expected CSV columns:
      date,ticker,price
    """
    if not ACTUALS_FILE.exists():
        return {}

    df = pd.read_csv(ACTUALS_FILE, dtype={"ticker": "string"})
    required = {"date", "ticker", "price"}
    if not required.issubset(df.columns):
        return {}

    df = df.dropna(subset=["date", "ticker", "price"]).copy()
    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df = df.dropna(subset=["date", "price"])
    df = df.sort_values(["ticker", "date"])

    actuals: Dict[str, Dict[str, List[Any]]] = {}
    for ticker, group in df.groupby("ticker"):
        actuals[ticker] = {
            "dates": group["date"].dt.strftime("%Y-%m-%d").tolist(),
            "prices": group["price"].astype(float).tolist(),
        }

    return actuals
