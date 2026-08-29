import base64
import json
from typing import Any

from pydantic import BaseModel, Field


class Page[T](BaseModel):
    items: list[T]
    page: int
    page_size: int
    total: int
    total_pages: int


class CursorPage[T](BaseModel):
    items: list[T]
    next_cursor: str | None
    has_more: bool


class OffsetParams(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=25, ge=1, le=100)


def encode_cursor(sort_key: str, resource_id: str) -> str:
    payload = json.dumps([sort_key, resource_id], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[str, str]:
    try:
        padding = "=" * (-len(cursor) % 4)
        value: Any = json.loads(base64.urlsafe_b64decode(cursor + padding))
        if (
            not isinstance(value, list)
            or len(value) != 2
            or not all(isinstance(x, str) for x in value)
        ):
            raise ValueError
        return value[0], value[1]
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid pagination cursor") from exc
