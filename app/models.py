from typing import List
from pydantic import BaseModel


class RunSeries(BaseModel):
    run_index: int
    horizons: List[str]
    values: List[float]


class ForecastMultiRun(BaseModel):
    ticker: str
    runs: List[RunSeries]


class TickerList(BaseModel):
    tickers: List[str]


class ActualSeries(BaseModel):
    ticker: str
    dates: List[str]
    prices: List[float]


class TickerMetric(BaseModel):
    ticker: str
    prediction_ratio: float


class TickerMetricList(BaseModel):
    tickers: List[TickerMetric]
