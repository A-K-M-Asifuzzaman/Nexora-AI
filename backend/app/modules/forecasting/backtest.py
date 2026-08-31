"""Walk-forward backtesting and model selection (`AI.md` §4).

Random k-fold on a time series leaks the future into training and scores a
model that would have failed in production — every evaluation here is
expanding-window, one-step-ahead, sliding forward in time order only.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from app.modules.forecasting.algorithms import Model

MIN_TRAIN_PERIODS = 4  # never backtest a fit against fewer than this many points


@dataclass(frozen=True, slots=True)
class BacktestScore:
    model_name: str
    mae: float
    rmse: float
    mase: float | None  # None when the naive-scale denominator is zero (a flat series)


@dataclass(frozen=True, slots=True)
class SelectionResult:
    scores: list[BacktestScore]
    winner: str


def walk_forward_errors(
    model: Model, values: Sequence[float], dates: Sequence[date]
) -> list[float]:
    """One-step-ahead errors from an expanding window, sliding forward."""
    errors: list[float] = []
    for i in range(MIN_TRAIN_PERIODS, len(values)):
        fitted = model.fit(values[:i], dates[:i])
        (prediction,) = fitted.predict([dates[i]])
        errors.append(values[i] - prediction)
    return errors


def _naive_scale(values: Sequence[float]) -> float:
    """MASE's denominator: the mean absolute one-step change, in-sample.
    Zero for a perfectly flat series — callers must treat that as
    "undefined", never divide by it."""
    diffs = [abs(values[i] - values[i - 1]) for i in range(1, len(values))]
    return sum(diffs) / len(diffs) if diffs else 0.0


def score(model: Model, values: Sequence[float], dates: Sequence[date]) -> BacktestScore:
    errors = walk_forward_errors(model, values, dates)
    if not errors:
        return BacktestScore(model.name, mae=0.0, rmse=0.0, mase=None)
    mae = sum(abs(e) for e in errors) / len(errors)
    rmse = math.sqrt(sum(e * e for e in errors) / len(errors))
    scale = _naive_scale(values)
    mase = mae / scale if scale > 1e-9 else None
    return BacktestScore(model.name, mae=mae, rmse=rmse, mase=mase)


def select_best(
    candidates: Sequence[Model], values: Sequence[float], dates: Sequence[date]
) -> SelectionResult:
    """Scores every candidate and picks a winner.

    The first candidate is always treated as the naive floor (`service.py`
    puts `Naive` first): a later candidate only wins if its MASE is strictly
    lower. When MASE is undefined for either side (a flat series has nothing
    for MASE to scale by), MAE is the tiebreaker — still comparable, just
    not scale-free.
    """
    scores = [score(model, values, dates) for model in candidates]
    winner = scores[0].model_name
    best = scores[0]
    for candidate in scores[1:]:
        if best.mase is not None and candidate.mase is not None:
            better = candidate.mase < best.mase
        else:
            better = candidate.mae < best.mae
        if better:
            best = candidate
            winner = candidate.model_name
    return SelectionResult(scores=scores, winner=winner)
