"""Tests for backend.memory.pg.connection — PgConnectionManager.

Covers:
- __init__ pool creation and error handling
- get_connection context manager (commit / rollback / putconn)
- execute, execute_one, execute_dict, execute_many convenience methods
- health_check success and failure
- close idempotent behavior
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch, call

import pytest

from backend.memory.pg.connection import PgConnectionManager


# ============================================================================
# Construction
# ============================================================================

class TestPgConnectionManagerInit:

    @patch("backend.memory.pg.connection.psycopg2.pool.ThreadedConnectionPool")
    def test_creates_pool(self, mock_pool_class):
        mgr = PgConnectionManager(dsn="postgresql://u:p@host/db", minconn=1, maxconn=5)
        mock_pool_class.assert_called_once_with(minconn=1, maxconn=5, dsn="postgresql://u:p@host/db")
        assert mgr._pool is not None

    @patch("backend.memory.pg.connection.psycopg2.pool.ThreadedConnectionPool",
           side_effect=Exception("connection refused"))
    def test_init_raises_on_pool_failure(self, mock_pool_class):
        with pytest.raises(Exception, match="connection refused"):
            PgConnectionManager(dsn="bad-dsn")


# ============================================================================
# get_connection context manager
# ============================================================================

class TestGetConnection:

    @patch("backend.memory.pg.connection.psycopg2.pool.ThreadedConnectionPool")
    def test_yields_connection_and_commits(self, mock_pool_class):
        fake_conn = MagicMock()
        mock_pool = MagicMock()
        mock_pool.getconn.return_value = fake_conn
        mock_pool_class.return_value = mock_pool

        mgr = PgConnectionManager(dsn="postgresql://test")
        with mgr.get_connection() as conn:
            assert conn is fake_conn

        fake_conn.commit.assert_called_once()
        mock_pool.putconn.assert_called_once_with(fake_conn)

    @patch("backend.memory.pg.connection.psycopg2.pool.ThreadedConnectionPool")
    def test_rollback_on_exception(self, mock_pool_class):
        fake_conn = MagicMock()
        mock_pool = MagicMock()
        mock_pool.getconn.return_value = fake_conn
        mock_pool_class.return_value = mock_pool

        mgr = PgConnectionManager(dsn="postgresql://test")
        with pytest.raises(ValueError):
            with mgr.get_connection() as conn:
                raise ValueError("boom")

        fake_conn.rollback.assert_called_once()
        fake_conn.commit.assert_not_called()
        mock_pool.putconn.assert_called_once_with(fake_conn)

    @patch("backend.memory.pg.connection.psycopg2.pool.ThreadedConnectionPool")
    def test_raises_if_pool_is_closed(self, mock_pool_class):
        mock_pool_class.return_value = MagicMock()
        mgr = PgConnectionManager(dsn="postgresql://test")
        mgr._pool = None

        with pytest.raises(RuntimeError, match="pool is closed"):
            with mgr.get_connection():
                pass


# ============================================================================
# Convenience methods
# ============================================================================

class TestExecute:

    def test_execute_returns_rows_for_select(self, mock_conn_mgr):
        """execute() should return fetchall() for SELECT-like queries."""
        fake_cursor = MagicMock()
        fake_cursor.description = [("col",)]
        fake_cursor.fetchall.return_value = [(1,), (2,)]

        fake_conn = MagicMock()
        fake_conn.cursor.return_value.__enter__ = MagicMock(return_value=fake_cursor)
        fake_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        @contextmanager
        def _get_conn():
            yield fake_conn

        mock_conn_mgr.get_connection = _get_conn

        real_execute = PgConnectionManager.execute.__get__(mock_conn_mgr, PgConnectionManager)
        result = real_execute("SELECT * FROM t")
        assert result == [(1,), (2,)]

    def test_execute_returns_empty_for_non_select(self, mock_conn_mgr):
        fake_cursor = MagicMock()
        fake_cursor.description = None

        fake_conn = MagicMock()
        fake_conn.cursor.return_value.__enter__ = MagicMock(return_value=fake_cursor)
        fake_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        @contextmanager
        def _get_conn():
            yield fake_conn

        mock_conn_mgr.get_connection = _get_conn

        real_execute = PgConnectionManager.execute.__get__(mock_conn_mgr, PgConnectionManager)
        result = real_execute("INSERT INTO t VALUES (1)")
        assert result == []


class TestExecuteOne:

    def test_returns_first_row(self, mock_conn_mgr):
        fake_cursor = MagicMock()
        fake_cursor.description = [("col",)]
        fake_cursor.fetchone.return_value = (42,)

        fake_conn = MagicMock()
        fake_conn.cursor.return_value.__enter__ = MagicMock(return_value=fake_cursor)
        fake_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        @contextmanager
        def _get_conn():
            yield fake_conn

        mock_conn_mgr.get_connection = _get_conn
        real_method = PgConnectionManager.execute_one.__get__(mock_conn_mgr, PgConnectionManager)
        result = real_method("SELECT 1")
        assert result == (42,)

    def test_returns_none_for_non_select(self, mock_conn_mgr):
        fake_cursor = MagicMock()
        fake_cursor.description = None

        fake_conn = MagicMock()
        fake_conn.cursor.return_value.__enter__ = MagicMock(return_value=fake_cursor)
        fake_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        @contextmanager
        def _get_conn():
            yield fake_conn

        mock_conn_mgr.get_connection = _get_conn
        real_method = PgConnectionManager.execute_one.__get__(mock_conn_mgr, PgConnectionManager)
        result = real_method("UPDATE t SET x=1")
        assert result is None


class TestExecuteDict:

    def test_returns_list_of_dicts(self, mock_conn_mgr):
        fake_cursor = MagicMock()
        fake_cursor.description = [("id",), ("name",)]
        fake_cursor.fetchall.return_value = [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]

        fake_conn = MagicMock()
        fake_conn.cursor.return_value.__enter__ = MagicMock(return_value=fake_cursor)
        fake_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        @contextmanager
        def _get_conn():
            yield fake_conn

        mock_conn_mgr.get_connection = _get_conn
        real_method = PgConnectionManager.execute_dict.__get__(mock_conn_mgr, PgConnectionManager)
        result = real_method("SELECT id, name FROM t")
        assert len(result) == 2
        assert result[0]["id"] == 1


class TestExecuteMany:

    def test_returns_rowcount(self, mock_conn_mgr):
        fake_cursor = MagicMock()
        fake_cursor.rowcount = 3

        fake_conn = MagicMock()
        fake_conn.cursor.return_value.__enter__ = MagicMock(return_value=fake_cursor)
        fake_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        @contextmanager
        def _get_conn():
            yield fake_conn

        mock_conn_mgr.get_connection = _get_conn
        real_method = PgConnectionManager.execute_many.__get__(mock_conn_mgr, PgConnectionManager)
        result = real_method("INSERT INTO t VALUES (%s)", [(1,), (2,), (3,)])
        assert result == 3


# ============================================================================
# health_check
# ============================================================================

class TestHealthCheck:

    @patch("backend.memory.pg.connection.psycopg2.pool.ThreadedConnectionPool")
    def test_health_check_success(self, mock_pool_class):
        fake_cursor = MagicMock()
        fake_cursor.description = [("?column?",)]
        fake_cursor.fetchone.return_value = (1,)

        fake_conn = MagicMock()
        fake_conn.cursor.return_value.__enter__ = MagicMock(return_value=fake_cursor)
        fake_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        mock_pool = MagicMock()
        mock_pool.getconn.return_value = fake_conn
        mock_pool_class.return_value = mock_pool

        mgr = PgConnectionManager(dsn="postgresql://test")
        assert mgr.health_check() is True

    @patch("backend.memory.pg.connection.psycopg2.pool.ThreadedConnectionPool")
    def test_health_check_failure(self, mock_pool_class):
        mock_pool = MagicMock()
        mock_pool.getconn.side_effect = Exception("no connection")
        mock_pool_class.return_value = mock_pool

        mgr = PgConnectionManager(dsn="postgresql://test")
        assert mgr.health_check() is False


# ============================================================================
# close
# ============================================================================

class TestClose:

    @patch("backend.memory.pg.connection.psycopg2.pool.ThreadedConnectionPool")
    def test_close_closes_pool(self, mock_pool_class):
        mock_pool = MagicMock()
        mock_pool_class.return_value = mock_pool

        mgr = PgConnectionManager(dsn="postgresql://test")
        mgr.close()

        mock_pool.closeall.assert_called_once()
        assert mgr._pool is None

    @patch("backend.memory.pg.connection.psycopg2.pool.ThreadedConnectionPool")
    def test_close_is_idempotent(self, mock_pool_class):
        mock_pool = MagicMock()
        mock_pool_class.return_value = mock_pool

        mgr = PgConnectionManager(dsn="postgresql://test")
        mgr.close()
        mgr.close()  # second call should not raise
        assert mgr._pool is None
