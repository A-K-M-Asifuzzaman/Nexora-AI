"""Statistical detectors (`AI.md` §5): seeded synthetic scenarios, not a live
database — these are pure functions, and what needs proving is the math, not
that a database round-trip works."""

from app.modules.anomaly.detectors import mad_threshold, ratio_rule, z_score


class TestMadThreshold:
    def test_a_flat_baseline_with_no_deviation_is_not_anomalous(self) -> None:
        verdict = mad_threshold([10.0, 10.0, 10.0, 10.0], 10.0)
        assert verdict.is_anomaly is False

    def test_a_stable_series_flags_a_real_outlier(self) -> None:
        history = [10.0, 11.0, 9.0, 10.0, 10.0, 11.0, 9.0, 10.0]
        verdict = mad_threshold(history, 40.0)
        assert verdict.is_anomaly is True
        assert verdict.observed == 40.0

    def test_a_stable_series_does_not_flag_ordinary_noise(self) -> None:
        history = [10.0, 11.0, 9.0, 10.0, 10.0, 11.0, 9.0, 10.0]
        verdict = mad_threshold(history, 11.0)
        assert verdict.is_anomaly is False

    def test_fewer_than_four_points_is_never_anomalous(self) -> None:
        """Too little history for a baseline to mean anything — the
        detector must decline to judge, not manufacture a threshold."""
        verdict = mad_threshold([10.0, 10.0], 1000.0)
        assert verdict.is_anomaly is False

    def test_a_perfectly_flat_baseline_falls_back_to_any_deviation(self) -> None:
        """MAD is zero on a flat series — "how many sigma" is undefined, so
        any nonzero deviation at all is what counts instead."""
        verdict = mad_threshold([5.0, 5.0, 5.0, 5.0, 5.0], 5.5)
        assert verdict.is_anomaly is True
        verdict_same = mad_threshold([5.0, 5.0, 5.0, 5.0, 5.0], 5.0)
        assert verdict_same.is_anomaly is False

    def test_an_outlier_within_the_baseline_does_not_contaminate_the_threshold(self) -> None:
        """The property MAD is chosen for: a single wild point in the
        history must not drag the threshold wide enough to hide a second
        anomaly, the way mean/stdev would."""
        history_with_outlier = [10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 500.0]
        verdict = mad_threshold(history_with_outlier, 40.0)
        assert verdict.is_anomaly is True


class TestZScore:
    def test_a_normal_value_is_not_anomalous(self) -> None:
        history = [100.0, 102.0, 98.0, 101.0, 99.0, 100.0]
        verdict = z_score(history, 101.0)
        assert verdict.is_anomaly is False

    def test_a_large_deviation_is_anomalous(self) -> None:
        history = [100.0, 102.0, 98.0, 101.0, 99.0, 100.0]
        verdict = z_score(history, 10.0)
        assert verdict.is_anomaly is True

    def test_fewer_than_four_points_is_never_anomalous(self) -> None:
        verdict = z_score([100.0, 100.0], 1.0)
        assert verdict.is_anomaly is False


class TestRatioRule:
    def test_a_ratio_below_threshold_is_not_anomalous(self) -> None:
        verdict = ratio_rule(numerator=3, denominator=100, threshold=0.15)
        assert verdict.is_anomaly is False

    def test_a_ratio_above_threshold_is_anomalous(self) -> None:
        verdict = ratio_rule(numerator=25, denominator=100, threshold=0.15)
        assert verdict.is_anomaly is True
        assert verdict.observed == 0.25

    def test_a_ratio_exactly_at_threshold_is_not_anomalous(self) -> None:
        """Strictly greater than, not greater-or-equal — the threshold
        itself is the accepted edge, not the first flagged value."""
        verdict = ratio_rule(numerator=15, denominator=100, threshold=0.15)
        assert verdict.is_anomaly is False

    def test_a_zero_denominator_is_not_anomalous(self) -> None:
        """No activity at all (no sales, no voids) is not evidence of
        anything — dividing by zero must not be reached."""
        verdict = ratio_rule(numerator=0, denominator=0, threshold=0.15)
        assert verdict.is_anomaly is False
