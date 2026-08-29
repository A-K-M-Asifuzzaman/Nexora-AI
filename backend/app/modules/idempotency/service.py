"""Idempotency, exactly as ARCHITECTURE.md §11 specifies it.

The key row is written **in the same transaction as the business operation**, so
it is impossible to end up with a recorded key and no sale, or a sale with no
key. That is the whole point: a client retrying after a timeout must not be able
to pay twice.

Before this existed, `POST /sales/payments` and `POST /purchases/payments`
required an `Idempotency-Key` header, stored it on the row, and enforced
nothing. Measured: replaying one key twice produced two payments and left an
invoice showing `paid_amount 200.0000` against a single 100.00 payment.
Requiring the header made the endpoint *look* safe, which is worse than not
requiring it, because a client retries confidently.
"""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, DomainValidationError
from app.core.ids import uuid7
from app.modules.idempotency.models import IdempotencyKey

RETENTION = timedelta(hours=24)

IN_PROGRESS = "IN_PROGRESS"
COMPLETED = "COMPLETED"


def request_hash(payload: Any) -> str:
    """Stable hash of the request body.

    `sort_keys` matters: the same request serialized with keys in a different
    order must hash identically, or a client library that reorders JSON would
    turn a legitimate retry into `IDEMPOTENCY_KEY_REUSE`.
    """
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


class IdempotencyService:
    def __init__(self, session: AsyncSession, tenant_id: UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id

    async def claim(
        self, *, endpoint: str, key: str, payload: Any
    ) -> tuple[bool, dict[str, Any] | None, int | None]:
        """Try to claim `key` for `endpoint`.

        Returns `(won, stored_response, stored_status)`. `won=True` means this
        request owns the operation and must execute it, then call `complete`.
        `won=False` means a stored response is being replayed.

        Raises rather than returning for the two states that are client errors:
        a reused key with a different body, and a concurrent request still in
        flight.
        """
        digest = request_hash(payload)
        now = datetime.now(UTC)

        # ON CONFLICT DO NOTHING, in this transaction. Winning the insert and
        # doing the work are then inseparable — they commit or roll back
        # together.
        statement = (
            insert(IdempotencyKey)
            .values(
                id=uuid7(),
                tenant_id=self.tenant_id,
                endpoint=endpoint,
                key=key,
                request_hash=digest,
                status=IN_PROGRESS,
                expires_at=now + RETENTION,
            )
            .on_conflict_do_nothing(index_elements=["tenant_id", "endpoint", "key"])
            .returning(IdempotencyKey.id)
        )
        if (await self.session.scalar(statement)) is not None:
            return True, None, None

        existing = await self.session.scalar(
            select(IdempotencyKey).where(
                IdempotencyKey.endpoint == endpoint, IdempotencyKey.key == key
            )
        )
        if existing is None:
            # The conflicting row is invisible to this transaction, which means
            # a concurrent request holds it and has not committed. Retryable.
            raise ConflictError(
                "REQUEST_IN_PROGRESS", "An identical request is already being processed."
            )

        if existing.request_hash != digest:
            # One key must never mean two different operations.
            raise DomainValidationError(
                "IDEMPOTENCY_KEY_REUSE",
                "This Idempotency-Key was already used with a different request body.",
            )
        if existing.status == IN_PROGRESS:
            raise ConflictError(
                "REQUEST_IN_PROGRESS", "An identical request is already being processed."
            )
        return False, existing.response_body, existing.response_status

    async def complete(
        self, *, endpoint: str, key: str, response_status: int, response_body: dict[str, Any]
    ) -> None:
        """Snapshot the response so a later retry replays it verbatim."""
        await self.session.execute(
            text("""
                UPDATE idempotency_keys
                   SET status = :status,
                       response_status = :response_status,
                       response_body = CAST(:response_body AS jsonb)
                 WHERE tenant_id = :tenant_id AND endpoint = :endpoint AND key = :key
            """),
            {
                "status": COMPLETED,
                "response_status": response_status,
                "response_body": json.dumps(response_body, default=str),
                "tenant_id": str(self.tenant_id),
                "endpoint": endpoint,
                "key": key,
            },
        )
