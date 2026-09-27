from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.models import ShopCounter

M = TypeVar("M")


def get_scoped(db: Session, model: type[M], obj_id: int, shop_id: int, *, lock: bool = False, label=None) -> M:
    """Fetch a row by id *within the tenant*. Rows of other shops are indistinguishable from missing rows."""
    stmt = select(model).where(model.id == obj_id, model.shop_id == shop_id)  # type: ignore[attr-defined]
    if lock:
        stmt = stmt.with_for_update(of=model)
    obj = db.execute(stmt).unique().scalar_one_or_none()
    if obj is None:
        raise NotFound(f"{label or model.__name__} {obj_id} not found")
    return obj


def next_counter(db: Session, shop_id: int, name: str) -> int:
    """Gapless per-shop counter; the row stays locked until the surrounding transaction ends."""
    stmt = (
        insert(ShopCounter)
        .values(shop_id=shop_id, name=name, value=1)
        .on_conflict_do_update(index_elements=["shop_id", "name"], set_={"value": ShopCounter.value + 1})
        .returning(ShopCounter.value)
    )
    return int(db.execute(stmt).scalar_one())
