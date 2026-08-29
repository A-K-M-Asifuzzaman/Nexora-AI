import pytest
from pydantic import ValidationError

from app.modules.tenancy.schemas import TenantCreate


def valid_payload() -> dict[str, str]:
    return {
        "name": "Example Organization",
        "slug": "example-organization",
        "base_currency": "BDT",
        "timezone": "Asia/Dhaka",
        "country_code": "BD",
        "default_branch_code": "HQ",
        "default_branch_name": "Head Office",
        "default_warehouse_code": "HQ-WH",
        "default_warehouse_name": "Head Office Warehouse",
    }


def test_tenant_create_rejects_client_supplied_tenant_id() -> None:
    payload = valid_payload()
    payload["tenant_id"] = "018f0000-0000-7000-8000-000000000000"
    with pytest.raises(ValidationError) as caught:
        TenantCreate.model_validate(payload)
    assert caught.value.errors()[0]["type"] == "extra_forbidden"


def test_tenant_create_rejects_invalid_timezone_and_slug() -> None:
    payload = valid_payload()
    payload["timezone"] = "Not/A-Timezone"
    payload["slug"] = "Invalid Slug"
    with pytest.raises(ValidationError) as caught:
        TenantCreate.model_validate(payload)
    assert {error["loc"] for error in caught.value.errors()} == {("slug",), ("timezone",)}
