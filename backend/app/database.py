from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import DATA_DIR, DATABASE_URL


DATA_DIR.mkdir(parents=True, exist_ok=True)
engine = create_async_engine(DATABASE_URL, future=True)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def ensure_compat_schema(connection) -> None:
    """Add nullable lineage columns to databases created by the V2 prototype."""
    if connection.dialect.name != "sqlite":
        return
    columns = {
        "projects": {"analysis_brief": "JSON NOT NULL DEFAULT '{}'"},
        "datasets": {"project_id": "VARCHAR(36)", "current_version_id": "VARCHAR(36)", "semantics": "JSON NOT NULL DEFAULT '{}'"},
        "cleaning_recipes": {"source_version_id": "VARCHAR(36)", "result_version_id": "VARCHAR(36)"},
        "reports": {"project_id": "VARCHAR(36)", "dataset_version_id": "VARCHAR(36)", "run_id": "VARCHAR(36)", "deleted_at": "DATETIME"},
        "conversations": {"project_id": "VARCHAR(36)", "clarification_mode": "VARCHAR(16) NOT NULL DEFAULT 'auto'", "analysis_capabilities": "JSON NOT NULL DEFAULT '{}'"},
        "llm_usage_logs": {
            "stage": "VARCHAR(24) NOT NULL DEFAULT 'unknown'",
            "run_id": "VARCHAR(36)",
            "report_id": "VARCHAR(36)",
            "dashboard_id": "VARCHAR(36)",
            "purpose": "VARCHAR(120) NOT NULL DEFAULT ''",
            "usage_unavailable": "BOOLEAN NOT NULL DEFAULT 0",
        },
        "analysis_runs": {
            "project_id": "VARCHAR(36)",
            "dataset_version_ids": "JSON NOT NULL DEFAULT '[]'",
            "analysis_spec": "JSON NOT NULL DEFAULT '{}'",
            "idempotency_key": "VARCHAR(180)",
            "approval_granted": "BOOLEAN NOT NULL DEFAULT 0",
        },
    }
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    for table, additions in columns.items():
        if table not in tables:
            continue
        existing = {item["name"] for item in inspector.get_columns(table)}
        for name, ddl in additions.items():
            if name not in existing:
                connection.exec_driver_sql(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {ddl}')
    if "analysis_runs" in tables:
        connection.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_analysis_runs_idempotency_key ON analysis_runs (idempotency_key)"
        )


async def get_session():
    async with SessionLocal() as session:
        yield session
