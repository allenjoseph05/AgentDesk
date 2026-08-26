"""Database lifecycle and transaction-scoped repository unit of work."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine

from packages.config import load_project_environment

if TYPE_CHECKING:
    from packages.persistence.repositories import RepositoryUnitOfWork

DEFAULT_DATABASE_URL = "postgresql+psycopg://agentdesk:agentdesk@localhost:5432/agentdesk"


def database_url_from_environment() -> str:
    """Resolve the service database URL without reading environment at import time."""
    load_project_environment()
    return _psycopg_database_url(os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL))


def _psycopg_database_url(database_url: str) -> str:
    """Select psycopg 3 for provider URLs that omit a SQLAlchemy driver."""
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


def create_database_engine(database_url: str | None = None) -> Engine:
    """Create the shared synchronous engine used behind repository boundaries."""
    return sa.create_engine(
        database_url or database_url_from_environment(),
        pool_pre_ping=True,
    )


class Database:
    """Own an engine and expose atomic repository transactions."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @classmethod
    def connect(cls, database_url: str | None = None) -> Database:
        return cls(create_database_engine(database_url))

    @property
    def engine(self) -> Engine:
        return self._engine

    @contextmanager
    def transaction(self) -> Iterator[RepositoryUnitOfWork]:
        from packages.persistence.repositories import RepositoryUnitOfWork

        with self._engine.begin() as connection:
            yield RepositoryUnitOfWork(connection)

    def repositories(self, connection: Connection) -> RepositoryUnitOfWork:
        from packages.persistence.repositories import RepositoryUnitOfWork

        return RepositoryUnitOfWork(connection)

    def dispose(self) -> None:
        self._engine.dispose()
