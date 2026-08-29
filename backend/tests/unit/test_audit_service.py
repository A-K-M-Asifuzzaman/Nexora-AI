from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DomainValidationError
from app.core.pagination import encode_cursor
from app.modules.audit.service import AuditService


class UnusedSession:
    pass


def service() -> AuditService:
    return AuditService(cast(AsyncSession, UnusedSession()))


@pytest.mark.asyncio
async def test_audit_rejects_reversed_date_range_before_querying() -> None:
    now = datetime.now(UTC)
    with pytest.raises(DomainValidationError):
        await service().list_events(
            limit=50,
            cursor=None,
            action=None,
            resource_type=None,
            resource_id=None,
            actor_user_id=None,
            from_time=now,
            to_time=now - timedelta(seconds=1),
        )


@pytest.mark.asyncio
async def test_audit_rejects_cursor_with_naive_timestamp() -> None:
    cursor = encode_cursor("2026-08-29T01:00:00", "018f0000-0000-7000-8000-000000000000")
    with pytest.raises(DomainValidationError):
        await service().list_events(
            limit=50,
            cursor=cursor,
            action=None,
            resource_type=None,
            resource_id=None,
            actor_user_id=None,
            from_time=None,
            to_time=None,
        )
