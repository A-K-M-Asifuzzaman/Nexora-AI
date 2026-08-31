from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_serializer

from app.modules.anomaly.models import AlertStatus, Detector, ResourceType, Severity

__all__ = [
    "AlertResponse",
    "AlertStatus",
    "Detector",
    "ResourceType",
    "RunDetectorsResponse",
    "Severity",
]


class MoneyOut(BaseModel):
    """Every numeric alert figure is a computed statistic, not a JSON
    number — the same "money crosses the API as a string" rule this
    project applies everywhere a Decimal reaches a client."""

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("*", when_used="json")
    def _decimal_strings(self, value: Any) -> Any:
        return str(value) if isinstance(value, Decimal) else value


class AlertResponse(MoneyOut):
    id: UUID
    detector: Detector
    severity: Severity
    observed_value: Decimal
    expected_low: Decimal
    expected_high: Decimal
    deviation: Decimal
    reason: str
    occurred_at: datetime
    resource_type: ResourceType
    resource_id: UUID | None
    label: str | None
    status: AlertStatus


class RunDetectorsResponse(BaseModel):
    alerts_created: int
