"""Shared PG fixtures using mocked connections.

Provides a fake PgConnectionManager that never touches a real database.
All cursor operations are MagicMock-based so callers can configure
return values per-test.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from backend.memory.pg.connection import PgConnectionManager


class FakePool:
    """Minimal stand-in for psycopg2.pool.ThreadedConnectionPool."""

    def __init__(self):
        self._conn = MagicMock()
        self._cursor = MagicMock()
        self._conn.cursor.return_value.__enter__ = MagicMock(return_value=self._cursor)
        self._conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    def getconn(self):
        return self._conn

    def putconn(self, conn):
        pass

    def closeall(self):
        pass


@pytest.fixture
def fake_pool():
    """Return a FakePool instance."""
    return FakePool()


@pytest.fixture
def mock_conn_mgr(fake_pool):
    """Build a PgConnectionManager backed by FakePool (no real DB)."""
    with patch("backend.memory.pg.connection.psycopg2.pool.ThreadedConnectionPool",
               return_value=fake_pool):
        mgr = PgConnectionManager(dsn="postgresql://fake:fake@localhost/fake")
    return mgr


@pytest.fixture
def conn_mgr_with_mocks():
    """Return a PgConnectionManager with fully mocked convenience methods.

    Use this when you only need to control execute / execute_dict / execute_one
    return values without caring about the underlying pool.
    """
    mgr = MagicMock(spec=PgConnectionManager)
    mgr.execute = MagicMock(return_value=[])
    mgr.execute_one = MagicMock(return_value=None)
    mgr.execute_dict = MagicMock(return_value=[])
    mgr.execute_many = MagicMock(return_value=0)

    @contextmanager
    def _fake_get_connection():
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        yield conn

    mgr.get_connection = _fake_get_connection
    return mgr
