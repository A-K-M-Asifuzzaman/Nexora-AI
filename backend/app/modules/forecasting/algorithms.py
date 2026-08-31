"""Forecasting candidates, cheapest first (`AI.md` §4).

Every model exposes the same shape — `fit(values, dates) -> FittedModel`,
`FittedModel.predict(dates) -> list[float]` — so the backtest harness in
`backtest.py` can walk-forward any of them identically, and so a multi-period
forecast is one `predict()` call against the real future dates rather than a
recursive chain of the model feeding its own guesses back into itself (which
compounds error for no reason a direct formula does not already avoid).

No numpy: every model here is small enough that plain arithmetic is both
correct and, unlike a fitted black box, auditable at the line level — which
matters for a system that has to describe *which* model produced a number,
not just produce one.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Protocol


@dataclass(frozen=True, slots=True)
class FittedModel:
    name: str
    _predict_fn: object  # Callable[[Sequence[date]], list[float]], see below

    def predict(self, dates: Sequence[date]) -> list[float]:
        fn: PredictFn = self._predict_fn  # type: ignore[assignment]
        return fn(dates)


class PredictFn(Protocol):
    def __call__(self, dates: Sequence[date]) -> list[float]: ...


class Model(Protocol):
    name: str

    def fit(self, values: Sequence[float], dates: Sequence[date]) -> FittedModel: ...


class Naive:
    """Last observed value, repeated. The floor every other model must beat."""

    name = "naive"

    def fit(self, values: Sequence[float], dates: Sequence[date]) -> FittedModel:
        last = values[-1] if values else 0.0

        def predict(dates: Sequence[date]) -> list[float]:
            return [last for _ in dates]

        return FittedModel(self.name, predict)


class MovingAverage:
    def __init__(self, window: int = 4) -> None:
        self.window = window
        self.name = f"moving_average_{window}"

    def fit(self, values: Sequence[float], dates: Sequence[date]) -> FittedModel:
        tail = values[-self.window :] if values else [0.0]
        level = sum(tail) / len(tail)

        def predict(dates: Sequence[date]) -> list[float]:
            return [level for _ in dates]

        return FittedModel(self.name, predict)


class ExponentialSmoothing:
    """Simple (single) exponential smoothing — flat forecast at the last
    smoothed level. No trend; `Holt` below is what adds one."""

    def __init__(self, alpha: float = 0.3) -> None:
        self.alpha = alpha
        self.name = "exponential_smoothing"

    def fit(self, values: Sequence[float], dates: Sequence[date]) -> FittedModel:
        level = values[0] if values else 0.0
        for value in values[1:]:
            level = self.alpha * value + (1 - self.alpha) * level

        def predict(dates: Sequence[date]) -> list[float]:
            return [level for _ in dates]

        return FittedModel(self.name, predict)


class Holt:
    """Double exponential smoothing: level and trend. Forecast h steps ahead
    is `level + h * trend` — the direct formula, not a recursive chain."""

    def __init__(self, alpha: float = 0.3, beta: float = 0.1) -> None:
        self.alpha = alpha
        self.beta = beta
        self.name = "holt_linear_trend"

    def fit(self, values: Sequence[float], dates: Sequence[date]) -> FittedModel:
        if len(values) < 2:
            level = values[0] if values else 0.0
            trend = 0.0
        else:
            level = values[0]
            trend = values[1] - values[0]
            for value in values[1:]:
                previous_level = level
                level = self.alpha * value + (1 - self.alpha) * (level + trend)
                trend = self.beta * (level - previous_level) + (1 - self.beta) * trend

        def predict(dates: Sequence[date]) -> list[float]:
            return [level + (h + 1) * trend for h in range(len(dates))]

        return FittedModel(self.name, predict)


class HoltWinters:
    """Triple exponential smoothing (additive seasonality). Only meaningful
    with at least two full seasonal cycles of history — the caller is
    responsible for not fitting this on too short a series (`service.py`
    only includes it as a candidate once that holds)."""

    def __init__(
        self, season_length: int, alpha: float = 0.3, beta: float = 0.1, gamma: float = 0.3
    ) -> None:
        self.season_length = season_length
        self.alpha = alpha
        self.beta = beta
        self.gamma = gamma
        self.name = f"holt_winters_{season_length}"

    def fit(self, values: Sequence[float], dates: Sequence[date]) -> FittedModel:
        m = self.season_length
        n = len(values)
        if n < 2 * m:
            # Falls back to Holt's trend-only formula rather than raising —
            # the caller decides whether this candidate is even offered;
            # if it is called anyway, degrading gracefully beats crashing.
            return Holt(self.alpha, self.beta).fit(values, dates)

        # Initial level/trend from the first two full cycles; initial
        # seasonal indices as each point's deviation from its cycle's mean.
        first_cycle = values[:m]
        second_cycle = values[m : 2 * m]
        level = sum(first_cycle) / m
        trend = (sum(second_cycle) / m - sum(first_cycle) / m) / m
        season = [values[i] - (sum(values[i : i + m]) / m) for i in range(m)]

        for i, value in enumerate(values):
            s = season[i % m]
            previous_level = level
            level = self.alpha * (value - s) + (1 - self.alpha) * (level + trend)
            trend = self.beta * (level - previous_level) + (1 - self.beta) * trend
            season[i % m] = self.gamma * (value - level) + (1 - self.gamma) * s

        def predict(dates: Sequence[date]) -> list[float]:
            return [level + (h + 1) * trend + season[(n + h) % m] for h in range(len(dates))]

        return FittedModel(self.name, predict)


class CalendarRegression:
    """Linear trend plus a smooth (sin/cos) month-of-year term — two
    features rather than eleven month dummies, so a small history does not
    overfit a nearly-as-large parameter count. This is the "complex" model
    `AI.md` §4 requires to beat the naive baseline before it is ever shown.
    """

    name = "linear_regression_calendar"

    def fit(self, values: Sequence[float], dates: Sequence[date]) -> FittedModel:
        n = len(values)
        if n == 0:
            return FittedModel(self.name, lambda ds: [0.0 for _ in ds])

        def features(index: int, d: date) -> list[float]:
            angle = 2 * math.pi * (d.month - 1) / 12
            return [1.0, float(index), math.sin(angle), math.cos(angle)]

        rows = [features(i, d) for i, d in enumerate(dates)]
        coefficients = _ols(rows, list(values))

        def predict(future_dates: Sequence[date]) -> list[float]:
            return [
                sum(c * x for c, x in zip(coefficients, features(n + h, d), strict=True))
                for h, d in enumerate(future_dates)
            ]

        return FittedModel(self.name, predict)


def _ols(rows: list[list[float]], targets: list[float]) -> list[float]:
    """Ordinary least squares via the normal equations, solved by Gaussian
    elimination. `rows` is small (4 columns) and `len(rows)` is at most a few
    hundred weekly points, so this plain approach is fast enough and needs no
    numeric library."""
    k = len(rows[0])
    xtx = [[sum(r[i] * r[j] for r in rows) for j in range(k)] for i in range(k)]
    xty = [sum(r[i] * y for r, y in zip(rows, targets, strict=True)) for i in range(k)]
    return _solve(xtx, xty)


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting for a small dense system.
    Falls back to an all-zero solution (a flat forecast at zero-effect
    calendar terms) if the system is singular, rather than raising — a
    handful of collinear points must not crash a forecast request."""
    n = len(vector)
    augmented = [row[:] + [vector[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot_row = max(range(col, n), key=lambda r: abs(augmented[r][col]))
        if abs(augmented[pivot_row][col]) < 1e-9:
            return [0.0] * n
        augmented[col], augmented[pivot_row] = augmented[pivot_row], augmented[col]
        pivot = augmented[col][col]
        augmented[col] = [x / pivot for x in augmented[col]]
        for r in range(n):
            if r != col:
                factor = augmented[r][col]
                augmented[r] = [
                    a - factor * b for a, b in zip(augmented[r], augmented[col], strict=True)
                ]
    return [row[-1] for row in augmented]
