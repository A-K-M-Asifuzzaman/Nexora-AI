from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

naming_convention = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=naming_convention)


def import_all_models() -> None:
    # Imports are deliberately local so Alembic can populate Base.metadata.
    from app.modules.audit import models as audit_models  # noqa: F401
    from app.modules.auth import models as auth_models  # noqa: F401
    from app.modules.branches import models as branch_models  # noqa: F401
    from app.modules.idempotency import models as idempotency_models  # noqa: F401
    from app.modules.outbox import models as outbox_models  # noqa: F401
    from app.modules.rbac import models as rbac_models  # noqa: F401
    from app.modules.tenancy import models as tenancy_models  # noqa: F401
