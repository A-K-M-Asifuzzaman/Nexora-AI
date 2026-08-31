"""DocumentStorage.ensure_bucket: create only on an actually missing bucket.

`head_bucket` carries no response body, so botocore reports the bare HTTP
status as the error code rather than a named one — these pin that "404"
(and the named "NoSuchBucket") are the only codes that should trigger
`create_bucket`; anything else must surface, not be papered over.
"""

from typing import Any

import pytest
from botocore.exceptions import ClientError

from app.core.config import get_settings
from app.modules.documents.storage import DocumentStorage


class _FakeS3Client:
    def __init__(self, head_error_code: str | None) -> None:
        self._head_error_code = head_error_code
        self.created = False

    def head_bucket(self, Bucket: str) -> None:  # noqa: N803 -- boto3's own casing
        if self._head_error_code is not None:
            raise ClientError(
                {"Error": {"Code": self._head_error_code, "Message": "x"}}, "HeadBucket"
            )

    def create_bucket(self, Bucket: str) -> dict[str, Any]:  # noqa: N803
        self.created = True
        return {}


async def test_a_missing_bucket_is_created() -> None:
    client = _FakeS3Client(head_error_code="404")
    storage = DocumentStorage(get_settings(), client=client)
    await storage.ensure_bucket()
    assert client.created is True


async def test_named_no_such_bucket_is_also_treated_as_missing() -> None:
    client = _FakeS3Client(head_error_code="NoSuchBucket")
    storage = DocumentStorage(get_settings(), client=client)
    await storage.ensure_bucket()
    assert client.created is True


async def test_an_existing_bucket_is_left_alone() -> None:
    client = _FakeS3Client(head_error_code=None)
    storage = DocumentStorage(get_settings(), client=client)
    await storage.ensure_bucket()
    assert client.created is False


async def test_a_permissions_error_is_not_papered_over_as_missing() -> None:
    """The old code caught every `ClientError` identically, so a 403 on a
    bucket that exists but this credential cannot HEAD would trigger a
    doomed — or worse, conflicting — `create_bucket` call instead of
    surfacing the real problem."""
    client = _FakeS3Client(head_error_code="403")
    storage = DocumentStorage(get_settings(), client=client)
    with pytest.raises(ClientError):
        await storage.ensure_bucket()
    assert client.created is False
