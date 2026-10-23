"""Connection pool shared by the API routes."""

from contextlib import contextmanager

from psycopg.rows import dict_row
from psycopg.types.numeric import FloatLoader
from psycopg_pool import ConnectionPool

from backend.config import settings


def _configure(c) -> None:
    # numeric (from extract(epoch ...), round(...), avg(int)) -> float, so JSON gets numbers not strings
    c.adapters.register_loader("numeric", FloatLoader)


pool = ConnectionPool(
    settings.database_url,
    min_size=1,
    max_size=10,
    open=False,
    configure=_configure,
    kwargs={"row_factory": dict_row},
)


@contextmanager
def conn():
    with pool.connection() as c:
        yield c


def rows(sql: str, params=None) -> list[dict]:
    with conn() as c:
        return c.execute(sql, params).fetchall()


def one(sql: str, params=None) -> dict | None:
    with conn() as c:
        return c.execute(sql, params).fetchone()
