"""VAT arithmetic, kept pure so it is testable without a database.

`ACCOUNTING.md` §6 is the committed rule: **ROUND_HALF_UP, applied per line,
then summed** — because "each printed line must be independently verifiable by
the person holding the invoice". Computing VAT on a rounded total instead gives
the same answer on the worked example in §6 and a different one on other inputs.
"""

from decimal import ROUND_HALF_UP, Decimal

SCALE = Decimal("0.0001")


def quantize(amount: Decimal) -> Decimal:
    """Round to the NUMERIC(18,4) storage scale."""
    return amount.quantize(SCALE, rounding=ROUND_HALF_UP)


def exclusive(net: Decimal, rate: Decimal) -> tuple[Decimal, Decimal, Decimal]:
    """Price excludes VAT: the customer pays `net + net × rate`.

    Returns `(net, vat, gross)`, each rounded.
    """
    net_r = quantize(net)
    vat = quantize(net_r * rate)
    return net_r, vat, net_r + vat


def inclusive(gross: Decimal, rate: Decimal) -> tuple[Decimal, Decimal, Decimal]:
    """Price already includes VAT: back it out.

    `net = gross / (1 + rate)`, and VAT is the remainder rather than
    `net × rate`. Taking the remainder guarantees `net + vat == gross` exactly;
    computing both independently can leave a one-minor-unit gap that makes the
    printed total disagree with the sum of its parts.
    """
    if rate < 0:
        raise ValueError("VAT rate cannot be negative")
    gross_r = quantize(gross)
    net = quantize(gross_r / (Decimal("1") + rate))
    return net, gross_r - net, gross_r
