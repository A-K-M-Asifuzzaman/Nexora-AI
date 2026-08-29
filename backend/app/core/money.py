from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated

from pydantic import BeforeValidator, PlainSerializer


def reject_float(value: object) -> object:
    if isinstance(value, float):
        raise ValueError("Monetary values must be JSON strings")
    return value


MoneyStr = Annotated[
    Decimal,
    BeforeValidator(reject_float),
    PlainSerializer(lambda value: format(value, "f"), return_type=str),
]


def round_money(amount: Decimal, minor_units: int) -> Decimal:
    quantum = Decimal(1).scaleb(-minor_units)
    return amount.quantize(quantum, rounding=ROUND_HALF_UP)
