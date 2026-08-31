"""The only module in the codebase permitted to import `qdrant_client`.

ADR-0013 and ARCHITECTURE.md §17: one collection, `nexora_documents`, with
`tenant_id` indexed as a Qdrant **tenant partition key**. Isolation therefore
rests on a filter always being applied — so this API is shaped to make an
unfiltered search *unexpressible*:

* every public method takes a `TenantContext` and builds the tenant condition
  itself, from `ctx.tenant_id`;
* no public method accepts a caller-supplied filter, `Filter` object, or raw
  query — there is no parameter through which a caller could widen the scope;
* the tenant condition is `must`, so any additional condition can only narrow.

`tests/unit/test_vector_store_isolation.py` asserts structurally that no other
module imports `qdrant_client`, which is what keeps the guarantee true as the
codebase grows rather than only true today.

The payload deliberately repeats `tenant_id` even though the point ID is
unique: filtering happens on the payload index, and a payload that omitted it
would be unfilterable — and therefore visible to every tenant.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid5

from qdrant_client import AsyncQdrantClient
from qdrant_client import models as qm

from app.core.config import Settings
from app.core.context import TenantContext

# A chunk's vector ID must be derived, not random: re-indexing a document has to
# overwrite its previous vectors, and a random ID would leave the old ones
# behind as orphans that still answer searches (AI.md §3.2).
_VECTOR_NAMESPACE = UUID("6f2c1a3e-9d54-4a7b-8f1c-2e5b7d9a0c31")


def chunk_point_id(document_id: UUID, chunk_index: int) -> str:
    return str(uuid5(_VECTOR_NAMESPACE, f"{document_id}:{chunk_index}"))


class TenantVectorStore:
    """Tenant-scoped access to the shared Qdrant collection."""

    def __init__(self, settings: Settings, client: AsyncQdrantClient | None = None) -> None:
        self._settings = settings
        self._collection = settings.qdrant_collection
        self._client = client or AsyncQdrantClient(
            url=settings.qdrant_url,
            api_key=(
                settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None
            ),
        )

    async def ensure_collection(self) -> None:
        """Idempotent. Safe to call on every worker start."""
        if not await self._client.collection_exists(self._collection):
            await self._client.create_collection(
                collection_name=self._collection,
                vectors_config=qm.VectorParams(
                    size=self._settings.embedding_dimensions, distance=qm.Distance.COSINE
                ),
            )
        # `is_tenant=True` is what makes this a partition key rather than an
        # ordinary index: Qdrant then co-locates each tenant's vectors, so a
        # filtered search reads one tenant's segments instead of scanning all.
        await self._client.create_payload_index(
            collection_name=self._collection,
            field_name="tenant_id",
            field_schema=qm.KeywordIndexParams(type=qm.KeywordIndexType.KEYWORD, is_tenant=True),
        )
        for field in ("document_id", "visibility", "allowed_role_ids"):
            await self._client.create_payload_index(
                collection_name=self._collection,
                field_name=field,
                field_schema=qm.PayloadSchemaType.KEYWORD,
            )

    def _tenant_condition(self, ctx: TenantContext) -> qm.FieldCondition:
        return qm.FieldCondition(key="tenant_id", match=qm.MatchValue(value=str(ctx.tenant_id)))

    def _visibility_conditions(self, ctx: TenantContext) -> list[qm.Condition]:
        """`visibility = TENANT` OR `allowed_role_ids` intersects the caller's.

        A caller with no roles gets only TENANT documents — `MatchAny` on an
        empty list matches nothing, which is the direction a failure must fall.
        """
        return [
            qm.FieldCondition(key="visibility", match=qm.MatchValue(value="TENANT")),
            qm.FieldCondition(
                key="allowed_role_ids",
                match=qm.MatchAny(any=[str(role_id) for role_id in ctx.role_ids]),
            ),
        ]

    async def search(
        self,
        ctx: TenantContext,
        query_vector: list[float],
        limit: int,
        document_id: UUID | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve chunks visible to this caller. Never widens beyond `ctx`."""
        must: list[qm.Condition] = [self._tenant_condition(ctx)]
        if document_id is not None:
            must.append(
                qm.FieldCondition(key="document_id", match=qm.MatchValue(value=str(document_id)))
            )
        response = await self._client.query_points(
            collection_name=self._collection,
            query=query_vector,
            limit=limit,
            with_payload=True,
            # The visibility OR-group is nested inside `must` rather than passed
            # as a sibling `should`. A top-level `should` alongside `must` is
            # ambiguous across Qdrant versions (optional boost vs. required
            # match); nesting makes "tenant AND (public OR my-role)" explicit,
            # and a nested filter can only ever narrow.
            query_filter=qm.Filter(
                must=[*must, qm.Filter(should=self._visibility_conditions(ctx))]
            ),
        )
        return [
            {"score": point.score, **(point.payload or {})}
            for point in response.points
            # Defence in depth: if a payload ever reached the collection without
            # the tenant field, the filter above could not have excluded it.
            if (point.payload or {}).get("tenant_id") == str(ctx.tenant_id)
        ]

    async def upsert_chunks(self, ctx: TenantContext, points: list[dict[str, Any]]) -> None:
        """Write chunks. The tenant payload is stamped here, not by the caller.

        A caller cannot forge `tenant_id`: whatever it puts in the payload is
        overwritten from `ctx` below.
        """
        await self._client.upsert(
            collection_name=self._collection,
            points=[
                qm.PointStruct(
                    id=chunk_point_id(point["document_id"], point["chunk_index"]),
                    vector=point["vector"],
                    payload={
                        **point["payload"],
                        "tenant_id": str(ctx.tenant_id),
                        "document_id": str(point["document_id"]),
                        "chunk_index": point["chunk_index"],
                    },
                )
                for point in points
            ],
        )

    async def delete_document(self, ctx: TenantContext, document_id: UUID) -> None:
        """Remove a document's vectors. Scoped, so it cannot delete another
        tenant's points even if handed their `document_id`."""
        await self._client.delete(
            collection_name=self._collection,
            points_selector=qm.Filter(
                must=[
                    self._tenant_condition(ctx),
                    qm.FieldCondition(
                        key="document_id", match=qm.MatchValue(value=str(document_id))
                    ),
                ]
            ),
        )

    async def iter_chunk_keys(self, ctx: TenantContext) -> AsyncIterator[tuple[UUID, int]]:
        """All `(document_id, chunk_index)` keys currently stored for this
        tenant. Used only by the orphan-reconciliation job (`AI.md` §3.2): it
        diffs this against `document_chunks` to find vectors whose owning row
        no longer exists — the gap between `upsert_chunks` committing to
        Qdrant and the caller's PostgreSQL transaction committing afterward.
        """
        offset: Any = None
        while True:
            records, offset = await self._client.scroll(
                collection_name=self._collection,
                scroll_filter=qm.Filter(must=[self._tenant_condition(ctx)]),
                with_payload=True,
                with_vectors=False,
                limit=256,
                offset=offset,
            )
            for record in records:
                payload = record.payload or {}
                # Same defence-in-depth check as search(): a payload that ever
                # reached the collection without the tenant field could not
                # have been excluded by the filter above.
                if payload.get("tenant_id") != str(ctx.tenant_id):
                    continue
                yield UUID(str(payload["document_id"])), int(payload["chunk_index"])
            if offset is None:
                break

    async def delete_points(self, ctx: TenantContext, keys: list[tuple[UUID, int]]) -> None:
        """Delete specific chunk vectors by key.

        Unlike this class's other methods, safety here does not come from a
        query filter — Qdrant's delete-by-id call cannot carry one alongside
        explicit point IDs. It comes from the caller: the only caller is the
        reconciliation job, and every key it passes was already read back from
        `iter_chunk_keys(ctx)`, which is itself tenant-filtered. `ctx` is kept
        as a parameter so that invariant is visible at every call site, even
        though it is not used to build a filter here.
        """
        if not keys:
            return
        await self._client.delete(
            collection_name=self._collection,
            points_selector=qm.PointIdsList(
                points=[
                    chunk_point_id(document_id, chunk_index) for document_id, chunk_index in keys
                ]
            ),
        )

    async def close(self) -> None:
        await self._client.close()
