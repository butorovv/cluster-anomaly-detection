"""Integration databases are unique, owned by each test and removed only by exact name."""
import os
from pathlib import Path
import uuid

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
import pytest

from tools.dataset.tests.conftest import synthetic_dataset  # noqa: F401
from build_dataset import build

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def database_url():
    admin = os.environ.get("TEST_DATABASE_URL")
    if not admin:
        pytest.skip("TEST_DATABASE_URL not set: real PostgreSQL integration not executed")
    name = "kr_f18_test_" + uuid.uuid4().hex
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(name)))
    parameters = conninfo_to_dict(admin)
    parameters["dbname"] = name
    url = make_conninfo(**parameters)
    try:
        with psycopg.connect(url) as conn:
            conn.execute((ROOT / "db/migrations/V1__core_schema.sql").read_text(encoding="utf-8"))
        yield url
    finally:
        # The generated database name is the entire deletion scope; no caller-supplied DB is dropped.
        assert name.startswith("kr_f18_test_") and len(name) == len("kr_f18_test_") + 32
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.fixture
def prepared_fixture(synthetic_dataset):
    fixture = synthetic_dataset
    build(fixture["paths"], fixture["output"], fixture["mapping"])
    return fixture
