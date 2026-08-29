from decimal import Decimal

from app.modules.sales.money import line_totals


def test_tax_uses_unrounded_line_net_before_independent_rounding() -> None:
    # ACCOUNTING.md §6: net and tax are independently rounded per line. This
    # input distinguishes that rule from taxing the already-rounded net.
    net, tax, total = line_totals(
        Decimal("2.5"), Decimal("0.3333"), Decimal("0"), Decimal("0.500000")
    )
    assert net == Decimal("0.8333")
    assert tax == Decimal("0.4166")
    assert total == Decimal("1.2499")
