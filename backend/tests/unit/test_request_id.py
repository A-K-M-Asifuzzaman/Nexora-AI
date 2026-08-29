import pytest

from app.core.context import is_valid_request_id


@pytest.mark.parametrize("value", ["request-123", "edge.proxy_01", "A" * 64])
def test_request_id_accepts_safe_values(value: str) -> None:
    assert is_valid_request_id(value)


@pytest.mark.parametrize("value", ["", "bad value", "line\nbreak", "A" * 65, "bad/header"])
def test_request_id_rejects_unsafe_values(value: str) -> None:
    assert not is_valid_request_id(value)
