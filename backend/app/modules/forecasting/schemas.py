from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class ForecastPoint(BaseModel):
    date: date
    value: str


class BacktestScoreResponse(BaseModel):
    model: str
    mae: str
    rmse: str
    mase: str | None


class ForecastResponse(BaseModel):
    product_id: UUID
    periods_ahead: int
    historical_actuals: list[ForecastPoint]
    point_forecast: list[ForecastPoint]
    prediction_interval_low: list[ForecastPoint]
    prediction_interval_high: list[ForecastPoint]
    model_used: str
    backtest_scores: list[BacktestScoreResponse]
    limitation_note: str


class InsufficientHistoryResponse(BaseModel):
    status: Literal["INSUFFICIENT_HISTORY"] = "INSUFFICIENT_HISTORY"
    periods_available: int
    periods_required: int
    message: str
