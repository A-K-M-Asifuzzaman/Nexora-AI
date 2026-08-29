from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AuditEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    actor_user_id: UUID | None
    actor_membership_id: UUID | None
    action: str
    resource_type: str
    resource_id: UUID | None
    request_id: str | None
    metadata: dict[str, Any] = Field(validation_alias="metadata_")
    occurred_at: datetime
