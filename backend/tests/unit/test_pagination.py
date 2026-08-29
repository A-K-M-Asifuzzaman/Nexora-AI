import pytest

from app.core.pagination import decode_cursor, encode_cursor


def test_cursor_round_trip() -> None:
    cursor = encode_cursor("2026-08-29T00:00:00Z", "018f0000-0000-7000-8000-000000000000")
    assert decode_cursor(cursor) == (
        "2026-08-29T00:00:00Z",
        "018f0000-0000-7000-8000-000000000000",
    )


@pytest.mark.parametrize("cursor", ["bad", "e30", "WzFd"])
def test_cursor_rejects_tampering(cursor: str) -> None:
    with pytest.raises(ValueError, match="Invalid pagination cursor"):
        decode_cursor(cursor)
