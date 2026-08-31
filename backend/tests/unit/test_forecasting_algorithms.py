"""Forecasting candidates (`AI.md` §4): each model's `fit().predict()`
against a known series, checked by hand — pure functions, no database."""

from datetime import date, timedelta

from app.modules.forecasting.algorithms import (
    CalendarRegression,
    Holt,
    HoltWinters,
    MovingAverage,
    Naive,
)

_START = date(2026, 1, 5)  # a Monday


def _weeks(n: int) -> list[date]:
    return [_START + timedelta(weeks=i) for i in range(n)]


class TestNaive:
    def test_repeats_the_last_observed_value(self) -> None:
        values = [10.0, 20.0, 15.0, 30.0]
        dates = _weeks(4)
        fitted = Naive().fit(values, dates)
        assert fitted.predict(_weeks(3)) == [30.0, 30.0, 30.0]

    def test_an_empty_series_forecasts_zero_rather_than_raising(self) -> None:
        fitted = Naive().fit([], [])
        assert fitted.predict(_weeks(1)) == [0.0]


class TestMovingAverage:
    def test_averages_exactly_the_trailing_window(self) -> None:
        values = [10.0, 10.0, 10.0, 10.0, 20.0, 20.0, 20.0, 20.0]
        fitted = MovingAverage(window=4).fit(values, _weeks(8))
        # Only the last 4 points (all 20s) should count, not the first 4.
        assert fitted.predict(_weeks(1)) == [20.0]

    def test_a_window_wider_than_the_series_uses_everything_available(self) -> None:
        values = [10.0, 20.0, 30.0]
        fitted = MovingAverage(window=10).fit(values, _weeks(3))
        assert fitted.predict(_weeks(1)) == [20.0]


class TestHolt:
    def test_extrapolates_a_perfectly_linear_trend(self) -> None:
        """10, 20, 30, 40, ... — a trend simple enough that Holt should
        converge to it almost exactly and keep extending it."""
        values = [10.0 * (i + 1) for i in range(10)]
        fitted = Holt(alpha=0.9, beta=0.9).fit(values, _weeks(10))
        forecast = fitted.predict(_weeks(2))
        # Not exact (smoothing lags a perfect line slightly) but must
        # clearly continue climbing at roughly the same ~10/period rate.
        assert forecast[1] > forecast[0] > values[-1]

    def test_a_flat_series_forecasts_flat(self) -> None:
        values = [50.0] * 6
        fitted = Holt().fit(values, _weeks(6))
        forecast = fitted.predict(_weeks(3))
        assert all(abs(v - 50.0) < 1e-6 for v in forecast)

    def test_a_single_point_does_not_raise(self) -> None:
        fitted = Holt().fit([42.0], _weeks(1))
        assert fitted.predict(_weeks(1)) == [42.0]


class TestHoltWinters:
    def test_falls_back_to_holt_when_history_is_too_short(self) -> None:
        """Fewer than two full seasonal cycles: the caller is responsible
        for not offering this candidate, but a direct call must still
        degrade gracefully rather than raise or index out of range."""
        values = [10.0, 12.0, 11.0]
        fitted = HoltWinters(season_length=4).fit(values, _weeks(3))
        assert fitted.predict(_weeks(1))  # does not raise

    def test_reproduces_a_clean_seasonal_pattern(self) -> None:
        """Two identical 4-period cycles: the third cycle's forecast should
        closely track the same shape, not flatten it out."""
        cycle = [10.0, 20.0, 10.0, 5.0]
        values = cycle * 3
        fitted = HoltWinters(season_length=4, alpha=0.5, beta=0.1, gamma=0.5).fit(
            values, _weeks(12)
        )
        forecast = fitted.predict(_weeks(4))
        # The high point of the cycle (index 1) must still forecast higher
        # than the low points (index 2, 3), not converge to a flat average.
        assert forecast[1] > forecast[2]
        assert forecast[1] > forecast[3]


class TestCalendarRegression:
    def test_fits_a_simple_linear_trend(self) -> None:
        values = [float(i) for i in range(20)]
        fitted = CalendarRegression().fit(values, _weeks(20))
        forecast = fitted.predict(_weeks(2))
        # Index 20 should continue at roughly +1/week from index 19.
        assert forecast[0] > values[-1]
        assert forecast[1] > forecast[0]

    def test_an_empty_series_forecasts_zero_rather_than_raising(self) -> None:
        fitted = CalendarRegression().fit([], [])
        assert fitted.predict(_weeks(1)) == [0.0]
