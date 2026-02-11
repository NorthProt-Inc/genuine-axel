"""Pytest fixtures for core tests."""

import pytest
from backend.memory.recent.connection import SQLiteConnectionManager
from backend.memory.recent.schema import SchemaManager


@pytest.fixture
def connection_manager(tmp_path):
    """Fresh SQLiteConnectionManager with a temp DB file."""
    mgr = SQLiteConnectionManager(db_path=tmp_path / "test_core.db")
    yield mgr
    mgr.close()


@pytest.fixture
def initialized_db(connection_manager):
    """ConnectionManager with schema already initialized."""
    SchemaManager(connection_manager).initialize()
    return connection_manager
