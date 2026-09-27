from dataclasses import dataclass

import jwt
from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.core.errors import Forbidden, Unauthorized
from app.core.permissions import P, has_permission
from app.core.security import decode_token
from app.db import get_db
from app.enums import Role
from app.models import Shop, User


@dataclass
class Ctx:
    """Authenticated request context. ``shop_id`` is the only tenant scope services may use."""

    db: Session
    user: User
    shop: Shop

    @property
    def shop_id(self) -> int:
        return self.shop.id

    @property
    def role(self) -> Role:
        return self.user.role

    def can(self, perm: P) -> bool:
        return has_permission(self.user.role, perm)


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise Unauthorized("missing bearer token")
    return authorization.split(" ", 1)[1].strip()


def get_ctx(db: Session = Depends(get_db), authorization: str | None = Header(default=None)) -> Ctx:
    try:
        claims = decode_token(_bearer(authorization))
    except jwt.PyJWTError as exc:
        raise Unauthorized("invalid or expired token") from exc
    if claims.get("type") != "access":
        raise Unauthorized("invalid token type")
    user = db.get(User, int(claims["sub"]))
    if user is None or not user.is_active or user.shop_id != claims.get("shop_id"):
        raise Unauthorized("user is inactive or no longer exists")
    return Ctx(db=db, user=user, shop=user.shop)


def require(*perms: P):
    def dep(ctx: Ctx = Depends(get_ctx)) -> Ctx:
        for perm in perms:
            if not ctx.can(perm):
                raise Forbidden(f"your role ({ctx.role.value}) lacks permission '{perm.value}'")
        return ctx

    return dep
