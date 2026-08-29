from sqlalchemy import REAL, Double, Float, UniqueConstraint

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
        # A UniqueConstraint leading with tenant_id satisfies this rule as fully
        # as an Index does: PostgreSQL implements one with a unique index on
        # exactly those columns. Verified on the live schema —
        # `UniqueConstraint("tenant_id", "series", "period")` on
        # document_sequences produces
        #   CREATE UNIQUE INDEX uq_document_sequences_tenant_id_series_period
        #     ON public.document_sequences USING btree (tenant_id, series, period)
        # Counting only `table.indexes` missed those and would have forced a
        # second, redundant index on every such table. The rule is unchanged;
        # this widens what the guard can see, not what it permits.
        leading_unique = [
            constraint
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
            and list(constraint.columns)
            and list(constraint.columns)[0].name == "tenant_id"
        ]
        if "tenant_id" not in table.columns or not (leading_indexes or leading_unique):
            offenders.append(model.__name__)
    assert not offenders, f"Tenant index rule violated by: {', '.join(offenders)}"
