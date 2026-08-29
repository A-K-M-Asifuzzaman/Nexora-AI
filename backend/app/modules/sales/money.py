"""Line arithmetic for priced documents.

`ACCOUNTING.md` §6: `ROUND_HALF_UP`, applied **per line**, then summed. Not
banker's rounding, and not rounded only at the total — per-line rounding is what
makes a printed line agree with the total a human checks it against.
"""

from decimal import ROUND_HALF_UP, Decimal

CENTS = Decimal("0.0001")


def round_money(amount: Decimal) -> Decimal:
    """Quantize to the NUMERIC(18,4) storage scale."""
    return amount.quantize(CENTS, rounding=ROUND_HALF_UP)


def line_totals(
    quantity: Decimal, unit_price: Decimal, discount_rate: Decimal, tax_rate: Decimal
) -> tuple[Decimal, Decimal, Decimal]:
    """Return `(net, tax, total)` for one line, each already rounded.

    Rounding net before computing tax is deliberate: tax is charged on the
    amount actually invoiced, which is the rounded net, not on an unrounded
    intermediate the customer never sees.
    """
    gross = quantity * unit_price
    net = round_money(gross * (Decimal("1") - discount_rate))
    tax = round_money(net * tax_rate)
    return net, tax, net + tax
