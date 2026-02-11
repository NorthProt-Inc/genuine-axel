"""PostgreSQL memory backend — pgvector-based replacement for ChromaDB/SQLite/JSON."""

from .connection import PgConnectionManager

__all__ = ["PgConnectionManager"]
