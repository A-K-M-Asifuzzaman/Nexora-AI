"""Shared fixtures for Phase 9 (RAG) integration tests.

Real PostgreSQL, real Qdrant, real MinIO — nothing here is mocked (`CLAUDE.md`:
"Real PostgreSQL only; never SQLite", and the same principle extends to the
other stateful stores this phase adds). The one thing that is faked is the
embedder: a real embedding call needs a paid provider key, and — exactly as
`AI.md` §2.6 and the Phase 8 guardrail tests already establish for the
copilot — the guarantees this phase proves (tenant isolation, ACL, citation
re-authorization) are structural and must not depend on one being configured.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.context import TenantContext, reset_tenant_context, set_tenant_context
from app.core.ids import uuid7
from app.db.session import create_engine, create_session_factory
from app.modules.documents.service import DocumentService
from app.modules.documents.storage import DocumentStorage
from app.modules.documents.vector_store import TenantVectorStore
from tests.integration.auth.test_password_and_verification import latest_token
from tests.integration.conftest import PASSWORD, tenant_headers


class FakeEmbedder:
    """Deterministic, dependency-free stand-in for a real embedding model.

    Same text always yields the same vector, and different text yields a
    different one — enough for the search-relevance assertions this suite
    makes ("a distinctive phrase returns the chunk it came from"). What is
    being proven throughout is the *tenant filter*, not embedding quality, so
    a hash is sufficient; nothing here would be more correct with a real
    model. Produces vectors at the application's real configured width
    (`Settings.embedding_dimensions`, 1536 by default) rather than a smaller
    test-only size: `app.main`'s startup hook provisions the Qdrant collection
    at that width the first time any test app is built, and a later attempt to
    upsert a different width into the same collection would fail — this
    suite's fake embedder must agree with production's width, not invent its
    own.
    """

    def __init__(self, dimensions: int) -> None:
        self._dimensions = dimensions

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        # Tile the hash digest out to the full width rather than truncating a
        # short one — a real embedding call always returns exactly this many
        # dimensions, and DocumentService._embed() rejects anything shorter.
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return [digest[i % len(digest)] / 255 for i in range(self._dimensions)]


@pytest.fixture
def documents_settings() -> Settings:
    return get_settings()


@pytest.fixture(autouse=True)
def _fake_search_provider(monkeypatch: pytest.MonkeyPatch, documents_settings: Settings) -> None:
    """`POST /documents/search` builds its embedder via `build_provider`
    (a real LLM provider needing a paid API key) inside the router. Patched at
    the router's own binding — `router.py` does `from ...providers_impl import
    build_provider`, so the name lives in `router`'s namespace, not only in
    `providers_impl`'s.
    """
    from app.modules.documents import router as documents_router

    embedder = FakeEmbedder(documents_settings.embedding_dimensions)
    monkeypatch.setattr(documents_router, "build_provider", lambda _settings: embedder)


async def index_now(
    session: AsyncSession, ctx: TenantContext, settings: Settings, document_id: uuid.UUID
) -> None:
    """Run the indexing pipeline synchronously, in place of the Celery task.

    Mirrors `app/workers/tasks/documents.py::_index` exactly — same store,
    same storage, same zero-permission shape of context — except for the
    embedder, and except that it shares the caller's session/transaction
    instead of opening its own, so the test can assert on the result without a
    second round trip.

    Two separate layers both need telling, independently, or the row is
    invisible for two different reasons:

    * Layer 2 (`app/db/tenant_guard.py`) reads the active tenant from a
      contextvar, not from whatever `TenantContext` object a caller happens to
      hold — `set_tenant_context`/`reset_tenant_context`, exactly like the
      real worker task.
    * Layer 3, PostgreSQL RLS, reads its own session-local GUC
      (`app.tenant_id`), set the same way `UnitOfWork` sets it for a real
      request — `SELECT set_config('app.tenant_id', ..., true)` — which is
      local to the current transaction and must be re-set after every commit,
      not merely once per session.
    """
    token = set_tenant_context(ctx)
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": str(ctx.tenant_id)},
    )
    store = TenantVectorStore(settings)
    try:
        await store.ensure_collection()
        await DocumentService(
            session,
            ctx,
            settings,
            store,
            DocumentStorage(settings),
            FakeEmbedder(settings.embedding_dimensions),
        ).index(document_id)
    finally:
        reset_tenant_context(token)
        await store.close()


def system_context(tenant_id: uuid.UUID) -> TenantContext:
    """Same shape the real worker uses: no roles, no permissions (`AI.md` §3.1
    — indexing must read every chunk regardless of who may later retrieve it,
    and must never act with a user's rights)."""
    return TenantContext(
        tenant_id=tenant_id,
        membership_id=uuid7(),
        user_id=uuid7(),
        role_ids=frozenset(),
        permissions=frozenset(),
        branch_ids=None,
    )


@pytest.fixture
async def db_session(documents_settings: Settings) -> AsyncIterator[AsyncSession]:
    engine = create_engine(documents_settings)
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()


async def upload_document(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    *,
    title: str,
    content: bytes = b"placeholder",
    content_type: str = "text/plain",
    filename: str = "doc.txt",
    visibility: str = "TENANT",
    role_ids: list[str] | None = None,
) -> dict[str, object]:
    files = {"file": (filename, content, content_type)}
    # A dict value, not a list of `("role_ids", x)` tuples: httpx's AsyncClient
    # only builds an async-compatible `MultipartStream` when `data` is a dict
    # (a list of pairs falls back to its sync url-encoded path even alongside
    # `files=`, which then fails with "Attempted to send a sync request with
    # an AsyncClient instance"). A list value repeats the field, which is what
    # a multi-role ACL needs.
    form_data: dict[str, str | list[str]] = {"title": title, "visibility": visibility}
    if role_ids:
        form_data["role_ids"] = role_ids
    response = await client.post("/api/v1/documents", headers=headers, data=form_data, files=files)
    assert response.status_code == 202, response.text
    return dict(response.json())


async def second_member_with_role(
    client: httpx.AsyncClient, owner_headers: dict[str, str], role_code: str
) -> tuple[dict[str, str], str]:
    """Invite, accept, log in and switch into the owner's own tenant under a
    named system role. Returns (auth headers, role_id)."""
    roles = (await client.get("/api/v1/roles/", headers=owner_headers)).json()
    role = next(r for r in roles if r["code"] == role_code)
    email = f"member-{uuid.uuid4().hex[:10]}@acme-demo.com"
    invited = await client.post(
        "/api/v1/invitations/", headers=owner_headers, json={"email": email, "role_id": role["id"]}
    )
    assert invited.status_code == 201, invited.text
    token = await latest_token(email, "invitation")
    accepted = await client.post(
        "/api/v1/invitations/accept",
        json={"token": token, "full_name": "Member", "password": PASSWORD},
    )
    assert accepted.status_code == 200, accepted.text
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    membership = login.json()["memberships"][0]
    switched = await client.post(
        "/api/v1/auth/switch-tenant",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json={"tenant_id": membership["tenant_id"]},
    )
    assert switched.status_code == 200, switched.text
    return {"Authorization": f"Bearer {switched.json()['access_token']}"}, role["id"]


async def owner_and_tenant_id(client: httpx.AsyncClient, email: str) -> tuple[dict[str, str], str]:
    headers = await tenant_headers(client, email)
    me = (await client.get("/api/v1/auth/me", headers=headers)).json()
    return headers, me["active_tenant_id"]
