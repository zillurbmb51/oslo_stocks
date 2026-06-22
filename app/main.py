from pathlib import Path
from typing import Dict, List, Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .data_loader import (
    load_model_commentaries,
    load_multi_run_forecasts,
    load_history,
    load_actual_prices,
)
from .models import (
    TickerList,
    ForecastMultiRun,
    RunSeries,
    ActualSeries,
    TickerMetric,
    TickerMetricList,
    CommentaryResponse,
    CommentaryBlock,
)


app = FastAPI(title="MyStocks OSL")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TICKER_TO_COMMENTARIES: Dict[str, Dict[str, str]] = {}
TICKER_TO_FORECAST: Dict[str, List[Dict[str, Any]]] = {}
TICKER_TO_HISTORY: Dict[str, Dict[str, List[Any]]] = {}
TICKER_TO_ACTUAL: Dict[str, Dict[str, List[Any]]] = {}
TICKER_TO_RATIO: Dict[str, float] = {}

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def compute_prediction_ratio(runs: List[Dict[str, Any]]) -> float:
    values: List[float] = []
    for run in runs:
        run_values = run.get("values", [])
        if isinstance(run_values, list):
            values.extend(v for v in run_values if isinstance(v, (int, float)))

    if not values:
        return 0.0

    min_value = min(values)
    max_value = max(values)
    if max_value == 0:
        return 0.0

    return float(min_value / max_value)


@app.on_event("startup")
def startup_event():
    global TICKER_TO_COMMENTARIES, TICKER_TO_FORECAST, TICKER_TO_HISTORY, TICKER_TO_ACTUAL, TICKER_TO_RATIO
    TICKER_TO_COMMENTARIES = load_model_commentaries()
    TICKER_TO_FORECAST = load_multi_run_forecasts()
    TICKER_TO_HISTORY = load_history()
    TICKER_TO_ACTUAL = load_actual_prices()
    TICKER_TO_RATIO = {
        ticker: compute_prediction_ratio(runs)
        for ticker, runs in TICKER_TO_FORECAST.items()
    }
    # Optional debug:
    # print("Loaded:",
    #       len(TICKER_TO_COMMENT), "comments;",
    #       len(TICKER_TO_FORECAST), "forecasts;",
    #       len(TICKER_TO_HISTORY), "histories")


@app.get("/api/tickers", response_model=TickerList)
def list_tickers():
    tickers = sorted(set(TICKER_TO_FORECAST.keys()) & set(TICKER_TO_COMMENTARIES.keys()))
    return TickerList(tickers=tickers)


@app.get("/api/ticker-metrics", response_model=TickerMetricList)
def list_ticker_metrics():
    metrics = [
        TickerMetric(ticker=ticker, prediction_ratio=TICKER_TO_RATIO.get(ticker, 0.0))
        for ticker in sorted(set(TICKER_TO_FORECAST.keys()) & set(TICKER_TO_COMMENTARIES.keys()))
    ]
    return TickerMetricList(tickers=metrics)

#@app.get("/api/tickers", response_model=TickerList)
#def list_tickers():
    # Only tickers that have *both* commentary and forecasts
#    tickers = sorted(set(TICKER_TO_COMMENT.keys()) & set(TICKER_TO_FORECAST.keys()))
#    return TickerList(tickers=tickers)


@app.get("/api/forecast/{ticker}", response_model=ForecastMultiRun)
def get_forecast(ticker: str):
    key = ticker.strip().upper()
    runs_raw = TICKER_TO_FORECAST.get(key)
    if not runs_raw:
        raise HTTPException(status_code=404, detail="Ticker not found")
    runs = [RunSeries(**r) for r in runs_raw]
    return ForecastMultiRun(ticker=key, runs=runs)


@app.get("/api/commentary/{ticker}", response_model=CommentaryResponse)
def get_commentary(ticker: str):
    key = ticker.strip().upper()
    comments = TICKER_TO_COMMENTARIES.get(key)
    if not comments:
        raise HTTPException(status_code=404, detail="Ticker not found")

    blocks: List[CommentaryBlock] = []
    fingpt_comment = comments.get("FinGPT1")
    
    if fingpt_comment:
        blocks.append(CommentaryBlock(source="FinGPT", commentary=fingpt_comment))

    for source in ["StatsForecast", "AutoETS"]:
        if comments.get(source):
            blocks.append(CommentaryBlock(source=source, commentary=comments[source]))

    return CommentaryResponse(ticker=key, commentaries=blocks)


@app.get("/api/history/{ticker}")
def get_history(ticker: str):
    key = ticker.strip().upper()
    hist = TICKER_TO_HISTORY.get(key)
    if hist is None:
        raise HTTPException(status_code=404, detail="No history for this ticker")
    return {"ticker": key, "dates": hist["dates"], "closes": hist["closes"]}


@app.get("/api/actual/{ticker}", response_model=ActualSeries)
def get_actual(ticker: str):
    key = ticker.strip().upper()
    actual = load_actual_prices().get(key)
    if actual is None:
        return ActualSeries(ticker=key, dates=[], prices=[])
    return ActualSeries(ticker=key, dates=actual["dates"], prices=actual["prices"])


@app.get("/")
def root():
    return {"message": "Go to /static/index.html for the UI."}
