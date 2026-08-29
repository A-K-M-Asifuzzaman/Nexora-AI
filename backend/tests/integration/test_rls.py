import os
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL not configured")


@pytest.fixture
async def app_engine():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    yield engine
    await engine.dispose()


async def test_application_role_is_not_owner_and_cannot_bypass_rls(app_engine) -> None:
    async with app_engine.connect() as connection:
        role = (
            await connection.execute(
                text(
                    "SELECT r.rolname, r.rolsuper, r.rolbypassrls "
                    "FROM pg_roles r WHERE r.rolname = current_user"
                )
            )
        ).one()
        owner_count = await connection.scalar(
            text(
                "SELECT count(*) FROM pg_class c JOIN pg_roles r ON r.oid = c.relowner "
                "WHERE c.relname = 'branches' AND r.rolname = current_user"
            )
        )

    assert role.rolname == "nexora_app"
    assert role.rolsuper is False
    assert role.rolbypassrls is False
    assert owner_count == 0


async def test_unset_tenant_guc_returns_zero_tenant_rows(app_engine) -> None:
    async with app_engine.connect() as connection:
        count = await connection.scalar(text("SELECT count(*) FROM branches"))
    assert count == 0


async def test_audit_stream_cannot_be_updated_by_application_role(app_engine) -> None:
    async with app_engine.connect() as connection:
        can_update = await connection.scalar(
            text("SELECT has_table_privilege(current_user, 'audit_events', 'UPDATE')")
        )
        can_delete = await connection.scalar(
            text("SELECT has_table_privilege(current_user, 'audit_events', 'DELETE')")
        )
    assert can_update is False
    assert can_delete is False


async def test_roles_expose_system_and_current_tenant_only(app_engine) -> None:
    tenant_a = uuid4()
    tenant_b = uuid4()
    role_a = uuid4()
    role_b = uuid4()
    async with app_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            await connection.execute(
                text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                {"tenant_id": str(tenant_a)},
            )
            await connection.execute(
                text(
                    "INSERT INTO tenants (id, name, slug, base_currency, status) "
                    "VALUES (:id, 'Tenant A', :slug, 'USD', 'ACTIVE')"
                ),
                {"id": tenant_a, "slug": f"tenant-a-{tenant_a.hex}"},
            )
            await connection.execute(
                text(
                    "INSERT INTO roles (id, tenant_id, code, name, is_system) "
                    "VALUES (:id, :tenant_id, 'CUSTOM_A', 'Custom A', false)"
                ),
                {"id": role_a, "tenant_id": tenant_a},
            )

            await connection.execute(
                text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                {"tenant_id": str(tenant_b)},
            )
            await connection.execute(
                text(
                    "INSERT INTO tenants (id, name, slug, base_currency, status) "
                    "VALUES (:id, 'Tenant B', :slug, 'USD', 'ACTIVE')"
                ),
                {"id": tenant_b, "slug": f"tenant-b-{tenant_b.hex}"},
            )
            await connection.execute(
                text(
                    "INSERT INTO roles (id, tenant_id, code, name, is_system) "
                    "VALUES (:id, :tenant_id, 'CUSTOM_B', 'Custom B', false)"
                ),
                {"id": role_b, "tenant_id": tenant_b},
            )

            visible_ids = set(await connection.scalars(text("SELECT id FROM roles")))
            assert role_b in visible_ids
            assert role_a not in visible_ids
            assert (
                await connection.scalar(text("SELECT count(*) FROM roles WHERE tenant_id IS NULL"))
                == 8
            )
        finally:
            await transaction.rollback()
