"""PostgreSQL connection manager using psycopg2 ThreadedConnectionPool."""

import atexit
from contextlib import contextmanager
from typing import List, Optional, Tuple

import psycopg2
import psycopg2.extras
import psycopg2.pool

from backend.core.logging import get_logger

_log = get_logger("memory.pg.connection")


class PgConnectionManager:
    """Manages a psycopg2 ThreadedConnectionPool with convenience methods.

    Args:
        dsn: PostgreSQL connection string.
        minconn: Minimum pool connections.
        maxconn: Maximum pool connections.
    """

    def __init__(self, dsn: str, minconn: int = 2, maxconn: int = 10):
        self._dsn = dsn
        self._pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None
        try:
            self._pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=minconn,
                maxconn=maxconn,
                dsn=dsn,
            )
            _log.info("PG pool opened", minconn=minconn, maxconn=maxconn)
        except Exception as e:
            _log.error("PG pool creation failed", error=str(e))
            raise

        atexit.register(self.close)

    # ── Context manager for a single connection ──────────────────────

    @contextmanager
    def get_connection(self):
        """Yield a connection from the pool with auto-commit/rollback.

        On normal exit the transaction is committed.
        On exception the transaction is rolled back before re-raising.
        """
        if self._pool is None:
            raise RuntimeError("PG connection pool is closed")
        conn = self._pool.getconn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._pool.putconn(conn)

    # ── Convenience helpers ──────────────────────────────────────────

    def execute(
        self,
        sql: str,
        params: tuple = None,
    ) -> List[Tuple]:
        """Execute a query and return all rows (empty list for non-SELECT)."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                if cur.description:
                    return cur.fetchall()
                return []

    def execute_one(
        self,
        sql: str,
        params: tuple = None,
    ) -> Optional[Tuple]:
        """Execute a query and return the first row, or None."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                if cur.description:
                    return cur.fetchone()
                return None

    def execute_dict(
        self,
        sql: str,
        params: tuple = None,
    ) -> List[dict]:
        """Execute a query and return rows as dicts."""
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                if cur.description:
                    return [dict(row) for row in cur.fetchall()]
                return []

    def execute_many(
        self,
        sql: str,
        params_list: List[tuple],
    ) -> int:
        """Execute a parameterised statement for each params tuple.

        Returns the total rowcount (-1 means unknown for some drivers).
        """
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(sql, params_list)
                return cur.rowcount

    def health_check(self) -> bool:
        """Return True if the pool can execute ``SELECT 1``."""
        try:
            result = self.execute_one("SELECT 1")
            return result is not None and result[0] == 1
        except Exception as e:
            _log.warning("PG health check failed", error=str(e))
            return False

    # ── Lifecycle ────────────────────────────────────────────────────

    def close(self) -> None:
        """Close all pool connections. Idempotent."""
        if self._pool is not None:
            try:
                self._pool.closeall()
                _log.info("PG pool closed")
            except Exception:
                pass
            self._pool = None
