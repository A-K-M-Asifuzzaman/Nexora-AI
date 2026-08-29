from decimal import Decimal

import pytest
from pydantic import BaseModel, ValidationError

from app.core.money import MoneyStr, round_money


class MoneyPayload(BaseModel):
    amount: MoneyStr


def test_money_rejects_json_float_and_serializes_as_string() -> None:
    with pytest.raises(ValidationError):
        MoneyPayload(amount=1.1)
    payload = MoneyPayload(amount="1.1000")
    assert payload.model_dump(mode="json") == {"amount": "1.1000"}


def test_rounding_is_half_up_at_currency_minor_units() -> None:
    assert round_money(Decimal("1.005"), 2) == Decimal("1.01")
    assert round_money(Decimal("1.5"), 0) == Decimal("2")
