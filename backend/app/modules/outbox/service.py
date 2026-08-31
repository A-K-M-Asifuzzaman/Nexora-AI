"""Transactional outbox writer (ADR-0020).

Rows are added to the caller's session so they commit **with** the business
operation. That is the whole point: an email is enqueued if and only if the work
that justifies it was committed. Dispatch happens afterwards, from a worker.

Never send mail (or make any external call) inside a business transaction — a
rollback would still have sent it, and a provider timeout would hold row locks.
"""

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import uuid7
from app.modules.outbox.models import OutboxEvent

TOPIC_EMAIL = "email.send"
TOPIC_DOCUMENT_INDEX = "documents.index"


class OutboxService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def enqueue_email(self, to: str, template: str, payload: dict[str, Any]) -> OutboxEvent:
        """Stage an email on the current transaction.

        The payload carries the single-use token for verification and reset mail.
        `outbox_events` has no tenant-facing read path and is not exposed by any
        endpoint, so the token is only ever read by the dispatch worker.
        """
        event = OutboxEvent(
            id=uuid7(),
            tenant_id=None,
            topic=TOPIC_EMAIL,
            payload={"to": to, "template": template, **payload},
        )
        self.session.add(event)
        return event

    def enqueue_document_index(self, tenant_id: UUID, document_id: UUID) -> OutboxEvent:
        """Stage an indexing run on the current transaction.

        The route used to commit the document row and then call
        `index_document.delay(...)` directly — a crash between those two
        lines left the row PENDING with nothing that would ever retry it.
        Routing through the outbox instead means the enqueue survives that
        crash the same way the document row itself does: both commit
        together, or neither does.
        """
        event = OutboxEvent(
            id=uuid7(),
            tenant_id=tenant_id,
            topic=TOPIC_DOCUMENT_INDEX,
            payload={"tenant_id": str(tenant_id), "document_id": str(document_id)},
        )
        self.session.add(event)
        return event
