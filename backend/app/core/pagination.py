from typing import Any, Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.errors import ValidationFailed

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class PageParams:
    def __init__(
        self,
        page: int = Query(1, ge=1),
        page_size: int = Query(25, ge=1, le=200),
        sort: str | None = Query(None, description="Sort field; prefix with '-' for descending"),
        q: str | None = Query(None, max_length=100, description="Free-text search"),
    ):
        self.page = page
        self.page_size = page_size
        self.sort = sort
        self.q = q.strip() if q and q.strip() else None


def _ordered(stmt: Select, params: PageParams, sort_map: dict[str, Any], default_sort: str, id_column: Any):
    raw = params.sort or default_sort
    desc = raw.startswith("-")
    key = raw.lstrip("-")
    if key not in sort_map:
        raise ValidationFailed(f"cannot sort by '{key}'; allowed: {', '.join(sorted(sort_map))}")
    col = sort_map[key]
    # The id tiebreaker makes ordering total, so pages never overlap or skip rows.
    return stmt.order_by(col.desc() if desc else col.asc(), id_column.desc() if desc else id_column.asc())


def paginate_rows(
    db: Session, stmt: Select, params: PageParams, sort_map: dict[str, Any], default_sort: str, id_column: Any
) -> tuple[list[Any], int]:
    """Like :func:`paginate` but returns full result rows (for multi-column selects)."""
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    ordered = _ordered(stmt, params, sort_map, default_sort, id_column)
    rows = db.execute(ordered.limit(params.page_size).offset((params.page - 1) * params.page_size)).all()
    return list(rows), int(total)


def paginate(
    db: Session,
    stmt: Select,
    params: PageParams,
    sort_map: dict[str, Any],
    default_sort: str,
    id_column: Any,
) -> tuple[list[Any], int]:
    """Apply whitelisted sorting with an ``id`` tiebreaker so pages are stable, then page the query."""
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    ordered = _ordered(stmt, params, sort_map, default_sort, id_column)
    rows = db.execute(ordered.limit(params.page_size).offset((params.page - 1) * params.page_size))
    return list(rows.unique().scalars().all()), int(total)


def like(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
