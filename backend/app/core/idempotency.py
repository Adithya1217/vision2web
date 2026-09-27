"""Idempotency for every mutating endpoint.

The key row is inserted inside the *same* transaction as the business change and the response is written
to it before commit. A retry with the same key therefore either replays the committed response, or (if
the first attempt rolled back) runs again from scratch. Concurrent duplicates block on the unique index
until the first commits, then replay it.
"""

import hashlib
from typing import Any

from fastapi import Depends, Header, Request
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core.deps import Ctx, get_ctx
from app.core.errors import Conflict, IdempotentReplay, ValidationFailed
from app.models import IdempotencyKey


async def request_fingerprint(request: Request) -> str:
    body = await request.body()
    h = hashlib.sha256()
    h.update(request.method.encode())
    h.update(b"\0")
    h.update(request.url.path.encode())
    h.update(b"\0")
    h.update(body)
    return h.hexdigest()


class Idem:
    def __init__(self, ctx: Ctx, row_id: int):
        self.ctx = ctx
        self.row_id = row_id

    def commit(self, result: Any, status_code: int = 200) -> Any:
        """Store the response alongside the business change and commit both atomically."""
        encoded = jsonable_encoder(result)
        row = self.ctx.db.get(IdempotencyKey, self.row_id)
        row.status_code = status_code
        row.response_body = encoded
        self.ctx.db.commit()
        return result


def idempotent(
    ctx: Ctx = Depends(get_ctx),
    fingerprint: str = Depends(request_fingerprint),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> Idem:
    key = (idempotency_key or "").strip()
    if not key:
        raise ValidationFailed("Idempotency-Key header is required for this operation", code="idempotency_required")
    if len(key) > 128:
        raise ValidationFailed("Idempotency-Key must be at most 128 characters")
    db = ctx.db
    scope = (IdempotencyKey.shop_id == ctx.shop_id, IdempotencyKey.user_id == ctx.user.id, IdempotencyKey.key == key)

    stmt = (
        insert(IdempotencyKey)
        .values(shop_id=ctx.shop_id, user_id=ctx.user.id, key=key, request_hash=fingerprint)
        .on_conflict_do_nothing(constraint="uq_idempotency_scope")
        .returning(IdempotencyKey.id)
    )
    new_id = db.execute(stmt).scalar()
    if new_id is not None:
        return Idem(ctx, new_id)

    existing = db.scalars(select(IdempotencyKey).where(*scope)).one()
    db.rollback()
    if existing.request_hash != fingerprint:
        raise Conflict(
            "Idempotency-Key was already used with a different request", code="idempotency_key_reused"
        )
    if existing.status_code is None:  # pragma: no cover - only visible under READ UNCOMMITTED
        raise Conflict("a request with this Idempotency-Key is still in progress", code="idempotency_in_progress")
    raise IdempotentReplay(existing.status_code, existing.response_body)
