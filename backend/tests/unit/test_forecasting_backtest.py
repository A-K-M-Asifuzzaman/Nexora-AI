"""Walk-forward backtesting and model selection (`AI.md` §4). Random k-fold
would leak the future into training; these pin the walk-forward alternative
this module commits to instead."""

from datetime import date, timedelta

from app.modules.forecasting.algorithms import CalendarRegression, MovingAverage, Naive
from app.modules.forecasting.backtest import score, select_best, walk_forward_errors

_START = date(2026, 1, 5)


def _weeks(n: int) -> list[date]:
    return [_START + timedelta(weeks=i) for i in range(n)]


def test_walk_forward_only_ever_trains_on_the_past() -> None:
    """A model that predicts using only points strictly before the one
    being scored — Naive repeating the prior value — should score exactly
    the first differences, proving no future point leaked into any fit."""
    values = [10.0, 15.0, 12.0, 20.0, 18.0, 25.0]
    errors = walk_forward_errors(Naive(), values, _weeks(6))
    # MIN_TRAIN_PERIODS=4, so scoring starts at index 4: error = actual - last.
    assert errors == [18.0 - 20.0, 25.0 - 18.0]


def test_a_perfect_naive_fit_on_a_flat_series_scores_zero_error() -> None:
    values = [10.0] * 8
    result = score(Naive(), values, _weeks(8))
    assert result.mae == 0.0
    assert result.rmse == 0.0


def test_mase_is_undefined_on_a_perfectly_flat_series() -> None:
    """MASE's denominator is the mean absolute change — zero when nothing
    ever changes, and dividing by that must come back as None, not a
    ZeroDivisionError or a misleadingly large score."""
    values = [10.0] * 8
    result = score(Naive(), values, _weeks(8))
    assert result.mase is None


def test_select_best_prefers_a_model_that_actually_beats_the_naive_floor() -> None:
    """An alternating series: Naive (repeat-last) is wrong by the full swing
    on every scored step, while a 2-period moving average settles on the
    midpoint and is off by only half as much — the winner must not default
    to Naive just for being listed first."""
    values = [10.0, 10.0, 10.0, 10.0, 20.0, 10.0, 20.0, 10.0, 20.0, 10.0]
    result = select_best([Naive(), MovingAverage(2)], values, _weeks(10))
    assert result.winner == MovingAverage(2).name


def test_select_best_picks_regression_on_a_long_clear_trend() -> None:
    """AGENT_HANDOFF.md's Phase 10 definition of done, verbatim: "a series
    with a known trend (regression must win)".

    A short trend is not actually this case: one-step-ahead walk-forward
    scores Naive's "repeat the last value" strikingly well on any smooth,
    low-noise series (each point is close to its predecessor almost by
    construction), and an under-fit regression — MIN_TRAIN_PERIODS=4
    against 4 free parameters early on — can score *worse* than Naive on a
    short series despite the trend being obvious to the eye. This needs
    real length (~3 years weekly) for the regression's parameter estimates
    to stabilize enough to actually win — confirmed empirically, not
    assumed, since the shorter series this started from picked Naive.
    """
    values = [10.0 * (i + 1) for i in range(150)]
    result = select_best([Naive(), CalendarRegression()], values, _weeks(150))
    assert result.winner == CalendarRegression().name


def test_select_best_falls_back_to_mae_when_mase_is_undefined_for_either_side() -> None:
    """Both candidates see a flat series (MASE undefined for both) — the
    tiebreaker must still produce a definite winner via MAE, not crash on
    a None-vs-None comparison."""
    values = [10.0] * 8
    result = select_best([Naive(), MovingAverage(4)], values, _weeks(8))
    assert result.winner in (Naive().name, MovingAverage(4).name)
    assert len(result.scores) == 2
