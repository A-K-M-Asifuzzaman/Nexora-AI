from sqlalchemy import REAL, Double, Float

from app.db.base import Base, import_all_models
from app.db.mixins import TenantScoped


def test_financial_metadata_contains_no_float_types() -> None:
    import_all_models()
    offenders = [
        f"{table.name}.{column.name}"
        for table in Base.metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, (Float, REAL, Double))
    ]
    assert not offenders, f"No-float-money rule violated by: {', '.join(offenders)}"


def test_tenant_models_have_leading_tenant_index() -> None:
    import_all_models()
    offenders: list[str] = []
    for mapper in Base.registry.mappers:
        model = mapper.class_
        if not issubclass(model, TenantScoped):
            continue
        table = mapper.local_table
        leading_indexes = [
            index
            for index in table.indexes
            if list(index.columns) and list(index.columns)[0].name == "tenant_id"
        ]
        if "tenant_id" not in table.columns or not leading_indexes:
            offenders.append(model.__name__)
    assert not offenders, f"Tenant index rule violated by: {', '.join(offenders)}"
