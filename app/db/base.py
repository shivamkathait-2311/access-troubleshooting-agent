from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for operational models (models/*.py).

    Audit models (models/audit_event.py) target a dedicated schema
    (settings.AUDIT_DB_SCHEMA) on the same instance for Phase 0 — see the
    project plan's "audit storage" decision — but still inherit from this
    same Base so Alembic autogenerate sees the whole metadata in one place.
    """
