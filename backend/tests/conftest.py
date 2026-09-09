import asyncio
import os
import shutil
from pathlib import Path
from uuid import uuid4

import pytest


# Set this before pytest imports any app module, keeping test data separate from
# the user's local workspaces.
TEST_DATA_DIR = Path(__file__).resolve().parents[1] / ".pytest-runs" / uuid4().hex
os.environ["AIBI_DATA_DIR"] = str(TEST_DATA_DIR)


@pytest.fixture(autouse=True)
def isolated_database():
    """Give every test a clean schema and storage tree without touching local user data."""
    from app.database import Base, engine, ensure_compat_schema

    async def reset():
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
            await connection.run_sync(Base.metadata.create_all)
            await connection.run_sync(ensure_compat_schema)

    asyncio.run(reset())
    yield


@pytest.fixture
def tmp_path(request):
    path = TEST_DATA_DIR / "tmp" / f"{request.node.name}-{uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def pytest_sessionfinish(session, exitstatus):
    from app.database import engine

    asyncio.run(engine.dispose())
    shutil.rmtree(TEST_DATA_DIR, ignore_errors=True)
