"""Object storage for uploaded documents, under a per-tenant key prefix.

The prefix is built here from the `TenantContext`, never from a caller-supplied
string, for the same reason the vector filter is built inside the vector store:
a path a caller can influence is a path a caller can traverse. `_safe_name`
strips everything but a conservative character set, so a filename of
`../../../etc/passwd` becomes `etcpasswd` rather than an escape.
"""

from __future__ import annotations

import re
from functools import partial
from typing import Any
from uuid import UUID

import anyio
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.core.config import Settings
from app.core.context import TenantContext

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def _safe_name(filename: str) -> str:
    cleaned = _UNSAFE.sub("", filename.replace("/", "").replace("\\", ""))
    # A name that was entirely separators must not collapse to an empty
    # segment, which would make the key end in a slash and collide.
    return (cleaned or "document")[:120]


def storage_key(ctx: TenantContext, document_id: UUID, filename: str) -> str:
    return f"tenants/{ctx.tenant_id}/documents/{document_id}/{_safe_name(filename)}"


class DocumentStorage:
    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self._bucket = settings.s3_bucket
        self._client = client or boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region,
            aws_access_key_id=(
                settings.s3_access_key_id.get_secret_value() if settings.s3_access_key_id else None
            ),
            aws_secret_access_key=(
                settings.s3_secret_access_key.get_secret_value()
                if settings.s3_secret_access_key
                else None
            ),
            # Path style is required by MinIO and harmless against real S3.
            # A short connect timeout, specifically here: nothing on the
            # upload path should hang for boto3's much longer network default
            # if the endpoint is unreachable — the caller gets a fast, clear
            # failure instead.
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                connect_timeout=3,
                read_timeout=10,
                retries={"max_attempts": 1},
            ),
        )

    async def ensure_bucket(self) -> None:
        def _create() -> None:
            try:
                self._client.head_bucket(Bucket=self._bucket)
            except ClientError as exc:
                # HEAD responses carry no body, so botocore reports the bare
                # HTTP status as the error code here rather than a named one
                # — "404" is what a missing bucket actually looks like.
                # Anything else (403 on a bucket that exists but this
                # credential can't HEAD, a throttled request, a network
                # blip) must not be papered over by attempting to create a
                # bucket that may already exist under someone else's grant.
                code = exc.response.get("Error", {}).get("Code", "")
                if code not in ("404", "NoSuchBucket"):
                    raise
                self._client.create_bucket(Bucket=self._bucket)

        # boto3 is synchronous; running it inline would block the event loop for
        # the whole upload.
        await anyio.to_thread.run_sync(_create)

    async def put(self, key: str, body: bytes, content_type: str) -> None:
        # No caller provisions the bucket ahead of time (nothing else in this
        # codebase calls `ensure_bucket`), so the first upload against a fresh
        # deployment would otherwise fail with `NoSuchBucket`. Idempotent —
        # `head_bucket` is the fast path once the bucket exists.
        await self.ensure_bucket()
        await anyio.to_thread.run_sync(
            partial(
                self._client.put_object,
                Bucket=self._bucket,
                Key=key,
                Body=body,
                ContentType=content_type,
            )
        )

    async def get(self, key: str) -> bytes:
        def _read() -> bytes:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            data: bytes = response["Body"].read()
            return data

        return await anyio.to_thread.run_sync(_read)

    async def delete(self, key: str) -> None:
        await anyio.to_thread.run_sync(
            partial(self._client.delete_object, Bucket=self._bucket, Key=key)
        )
