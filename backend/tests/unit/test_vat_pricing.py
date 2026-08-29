"""VAT arithmetic (ACCOUNTING.md §6). Pure, so no database is needed."""

from decimal import Decimal

import pytest

from app.modules.vat.pricing import exclusive, inclusive


def test_exclusive_adds_vat_to_the_net() -> None:
    net, vat, gross = exclusive(Decimal("1000.0000"), Decimal("0.150000"))
    assert (net, vat, gross) == (Decimal("1000.0000"), Decimal("150.0000"), Decimal("1150.0000"))


def test_inclusive_backs_vat_out_of_the_gross() -> None:
    net, vat, gross = inclusive(Decimal("1150.0000"), Decimal("0.150000"))
    assert net == Decimal("1000.0000")
    assert vat == Decimal("150.0000")
    assert gross == Decimal("1150.0000")


def test_inclusive_parts_always_sum_to_the_gross() -> None:
    """VAT is the remainder, not an independent product.

    Computing `net` and `vat` separately can leave a one-minor-unit gap that
    makes a printed total disagree with the sum of its own lines. Taking the
    remainder makes that impossible by construction.
    """
    for amount in ("0.0100", "33.3300", "99.9900", "1234.5600", "7.7700"):
        for rate in ("0.050000", "0.150000", "0.175000", "0.200000"):
            net, vat, gross = inclusive(Decimal(amount), Decimal(rate))
            assert net + vat == gross, (amount, rate, net, vat, gross)


def test_per_line_rounding_matches_the_worked_example() -> None:
    """ACCOUNTING.md §6: 3 items at 33.333 with 15% VAT.

    Each line rounds independently, then the lines sum — because each printed
    line must be verifiable on its own by whoever holds the invoice.
    """
    lines = [exclusive(Decimal("33.3330"), Decimal("0.150000")) for _ in range(3)]
    total_net = sum(line[0] for line in lines)
    total_vat = sum(line[1] for line in lines)
    assert total_net == Decimal("99.9990")
    # 33.333 x 0.15 = 4.99995, which rounds half-up to 5.0000 per line.
    assert total_vat == Decimal("15.0000")


def test_zero_rate_is_valid_and_charges_nothing() -> None:
    net, vat, gross = exclusive(Decimal("500.0000"), Decimal("0"))
    assert vat == Decimal("0") and gross == net


def test_negative_rate_is_rejected() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        inclusive(Decimal("100.0000"), Decimal("-0.100000"))
