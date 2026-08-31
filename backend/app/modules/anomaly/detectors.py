"""Statistical detectors (`AI.md` §5). Pure functions: given a series and the
latest observation, decide whether it is anomalous. No database access here —
that is `service.py`'s job, which is what makes these directly unit-testable
against seeded synthetic scenarios rather than only through a live database.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

# 1.4826 rescales MAD so it estimates the standard deviation consistently
# for a normal distribution — the standard constant, not a tuned magic number.
_MAD_TO_SIGMA = 1.4826


@dataclass(frozen=True, slots=True)
class Verdict:
    is_anomaly: bool
    observed: float
    expected_low: float
    expected_high: float
    deviation: float


def mad_threshold(history: list[float], observed: float, k: float = 3.5) -> Verdict:
    """Rolling-median + MAD threshold. Robust to the outliers being hunted,
    unlike mean/σ, which the same outliers contaminate (`AI.md` §5).

    `history` must not include `observed` — it is the baseline `observed` is
    being judged against.
    """
    if len(history) < 4:
        return Verdict(False, observed, observed, observed, 0.0)
    median = statistics.median(history)
    mad = statistics.median([abs(x - median) for x in history])
    sigma = mad * _MAD_TO_SIGMA
    if sigma < 1e-9:
        # A perfectly flat baseline: any deviation at all is meaningful,
        # but without a denominator "how many sigma" is undefined. Fall back
        # to flagging any nonzero deviation from that flat value.
        deviation = observed - median
        return Verdict(observed != median, observed, median, median, deviation)
    low, high = median - k * sigma, median + k * sigma
    deviation = (observed - median) / sigma
    return Verdict(observed < low or observed > high, observed, low, high, deviation)


def z_score(history: list[float], observed: float, threshold: float = 2.5) -> Verdict:
    """Mean/σ threshold — used only where the series does not itself contain
    the outliers that would contaminate mean/σ (`AI.md` §5 reserves this for
    "where the distribution warrants it"; `service.py` uses it for revenue,
    which a single day's anomaly does not retroactively distort as much as a
    ratio series does)."""
    if len(history) < 4:
        return Verdict(False, observed, observed, observed, 0.0)
    mean = statistics.mean(history)
    sigma = statistics.pstdev(history)
    if sigma < 1e-9:
        deviation = observed - mean
        return Verdict(observed != mean, observed, mean, mean, deviation)
    low, high = mean - threshold * sigma, mean + threshold * sigma
    deviation = (observed - mean) / sigma
    return Verdict(observed < low or observed > high, observed, low, high, deviation)


def ratio_rule(numerator: float, denominator: float, threshold: float) -> Verdict:
    """A fixed-threshold ratio check — for a series too thin, per period, for
    a statistical baseline to be meaningful (`AI.md` §5 names this
    explicitly for refunds/discounts; `service.py` also uses it for
    per-cashier void rate for the same reason: a single cashier's daily
    count is usually too small for MAD to mean anything)."""
    if denominator <= 0:
        return Verdict(False, 0.0, 0.0, threshold, 0.0)
    ratio = numerator / denominator
    deviation = ratio - threshold
    return Verdict(ratio > threshold, ratio, 0.0, threshold, deviation)
