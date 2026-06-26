import logging
import re
from pathlib import Path
from typing import Dict, List, Any

import pandas as pd

logger = logging.getLogger(__name__)

# Base data paths
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
RATIONALES_FILE = DATA_DIR / "ticker_rationales_osl_parallel.csv"
HISTORY_FILE = DATA_DIR / "oslo_stock_exchange_all_companies.xlsx"
ACTUALS_FILE = DATA_DIR / "oslo_actual_prices.csv"

FORECAST_SOURCES = [
    # Keep only the requested prediction sources.
    # FinGPT2/FinGPT3 are intentionally excluded from the published runs.
    {
        "label": "FinGPT1",
        "path": DATA_DIR / "my_new_predictions_osl_2026-04-07.csv",
        "sep": "\t",
    },
    {
        "label": "Chronos",
        "path": DATA_DIR / "chronos_osl_2026-06-22_single_run.tsv",
        "sep": "\t",
    },
    {
        "label": "NHITS",
        "path": DATA_DIR / "nhits_osl_2026-06-22_single_run.tsv",
        "sep": "\t",
    },
    {
        "label": "Prophet",
        "path": DATA_DIR / "prophet_osl_2026-06-22_single_run.tsv",
        "sep": "\t",
    },
    {
        "label": "StatsForecast",
        "path": DATA_DIR / "statsforecast_llama3_osl_2026-04-07_single_run.tsv",
        "sep": "\t",
    },
    {
        "label": "TimesFM",
        "path": DATA_DIR / "timesfm_osl_2026-06-22_single_run.tsv",
        "sep": "\t",
    },
    {
        "label": "XGBoost",
        "path": DATA_DIR / "xgboost_osl_2026-06-21_single_run.tsv",
        "sep": "\t",
    },
    {
        "label": "AutoETS",
        "path": DATA_DIR / "autoets_rag_llama3_osl_2026-04-24_single_run.tsv",
        "sep": "\t",
    },
]


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
        if stripped.lower() in {"text", "plain"}:
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

    # Remove prompt tails and review instructions that appear in some rows.
    text = re.split(
        r"\n\s*(?:Note:|Please |Is my commentary|Are there any suggestions|"
        r"Thank you|Also,|If there are any errors|\[End of commentary\])",
        text,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]

    # Collapse excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"^(?:text|plain)\s+", "", text, flags=re.IGNORECASE)

    return text.strip()


def load_rationales() -> Dict[str, str]:
    """
    Load ticker_rationales_osl_parallel.csv and return
      { TICKER: clean_comment }
    where TICKER matches the 'ticker' strings used in
    your forecast CSVs and history sheet names.
    """
    if not RATIONALES_FILE.exists():
        logger.warning("Rationales file not found: %s", RATIONALES_FILE)
        return {}

    try:
        df_raw = pd.read_csv(
            RATIONALES_FILE,
            engine="python",
            quotechar='"',
            sep=",",
            on_bad_lines="warn",
            encoding="latin-1",
            dtype={"ticker": "string"},
        )
    except Exception as exc:
        logger.error("Failed to read rationales file %s: %s", RATIONALES_FILE, exc)
        return {}

    required_cols = {"ticker", "comment", "run_start"}
    if not required_cols.issubset(df_raw.columns):
        logger.error(
            "Rationales file missing required columns. Expected %s, got %s",
            required_cols, set(df_raw.columns),
        )
        return {}

    df_raw["clean_comment"] = df_raw["comment"].apply(clean_comment)

    # Normalize ticker: trim + uppercase only.
    # DO NOT strip ".OL" etc., because you said tickers in all CSVs match
    # sheet names in the history file.
    df_raw["ticker_norm"] = (
        df_raw["ticker"].astype(str).str.strip().str.upper()
    )

    df_unique = (
        df_raw.dropna(subset=["clean_comment"])
        .drop_duplicates(subset=["ticker_norm", "clean_comment"])
        .sort_values("run_start")
        .groupby("ticker_norm", as_index=False)
        .agg({"clean_comment": "first"})
    )

    return dict(zip(df_unique["ticker_norm"], df_unique["clean_comment"]))


def load_model_commentaries() -> Dict[str, Dict[str, str]]:
    ticker_to_comments: Dict[str, Dict[str, str]] = {}

    rationales = load_rationales()
    for ticker, comment in rationales.items():
        if comment:
            ticker_to_comments.setdefault(ticker, {})
            ticker_to_comments[ticker]["FinGPT1"] = comment
            ticker_to_comments[ticker]["FinGPT2"] = comment
            ticker_to_comments[ticker]["FinGPT3"] = comment

    for source in FORECAST_SOURCES:
        if source["label"] in {"FinGPT1", "FinGPT2", "FinGPT3"}:
            continue

        # Render containers may not contain all forecast artifacts.
        if not source["path"].exists():
            continue

        try:
            df = pd.read_csv(source["path"], sep=source["sep"])
        except FileNotFoundError:
            logger.warning("Commentary source file missing: %s", source["path"])
            continue
        except Exception as exc:
            logger.error(
                "Failed to parse commentary source %s (%s): %s",
                source["label"], source["path"], exc,
            )
            continue

        if "ticker" not in df.columns or "comment" not in df.columns:
            continue


        df = df.copy()
        df["ticker_norm"] = df["ticker"].astype(str).str.strip().str.upper()
        df["clean_comment"] = df["comment"].apply(clean_comment)

        for _, row in df.iterrows():
            ticker = row["ticker_norm"]
            comment = row["clean_comment"]
            if not ticker or not comment:
                continue
            ticker_to_comments.setdefault(ticker, {})
            ticker_to_comments[ticker][source["label"]] = comment

    return ticker_to_comments


# -----------------------------
# Forecast loader
# -----------------------------

def load_multi_run_forecasts() -> Dict[str, List[Dict[str, Any]]]:
    """
    Load the website's selected forecast runs from data/.

    Output:
      {
        "2020": [
          {"run_index": 1, "run_label": "FinGPT1", "horizons": [...], "values": [...]},
          ...
        ],
        "AZT": [...],
        ...
      }
    """
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

    for source_index, source in enumerate(FORECAST_SOURCES, start=1):
        if not source["path"].exists():
            logger.warning("Forecast source file missing: %s (%s)", source["label"], source["path"])
            continue

        try:
            df = pd.read_csv(source["path"], sep=source["sep"])
        except Exception as exc:
            logger.error(
                "Failed to read forecast source %s (%s): %s",
                source["label"], source["path"], exc,
            )
            continue

        # Determine which price_* columns are present
        available = [(h_label, col) for (h_label, col) in horizon_map if col in df.columns]
        if not available:
            logger.warning("Forecast source %s has no usable price columns", source["label"])
            continue

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
                "run_index": source_index,
                "run_label": source["label"],
                "horizons": horizons,
                "values": values,
            }

            ticker_to_runs.setdefault(base_ticker, []).append(run_dict)

    for runs in ticker_to_runs.values():
        runs.sort(key=lambda run: run["run_index"])

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
        "2020": {"dates": [...], "closes": [...]},
        ...
      }
    """
    if not HISTORY_FILE.exists():
        logger.warning("History file not found: %s", HISTORY_FILE)
        return {}

    try:
        all_sheets = pd.read_excel(
            HISTORY_FILE,
            sheet_name=None,
            header=[0, 1],
            index_col=0,
        )
    except Exception as exc:
        logger.error("Failed to read history file %s: %s", HISTORY_FILE, exc)
        return {}

    history: Dict[str, Dict[str, List[Any]]] = {}

    for sheet_name, df in all_sheets.items():
        base_ticker = str(sheet_name).strip().upper()

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
            df_hist["Close"].astype(str).str.replace(",", ".", regex=False).astype(float)
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
        logger.info("Actual prices file not found: %s (this is normal on first deploy)", ACTUALS_FILE)
        return {}

    try:
        df = pd.read_csv(ACTUALS_FILE, dtype={"ticker": "string"})
    except Exception as exc:
        logger.error("Failed to read actual prices file %s: %s", ACTUALS_FILE, exc)
        return {}

    required = {"date", "ticker", "price"}
    if not required.issubset(df.columns):
        logger.error(
            "Actual prices file missing required columns. Expected %s, got %s",
            required, set(df.columns),
        )
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

