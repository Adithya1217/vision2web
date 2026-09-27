from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import Ctx, get_ctx, require
from app.core.idempotency import Idem, idempotent
from app.core.pagination import Page, PageParams, like, paginate
from app.core.permissions import ROLE_PERMISSIONS, P
from app.db import get_db
from app.models import User
from app.schemas.auth import (
    LoginIn,
    MeOut,
    RegisterIn,
    ShopOut,
    ShopUpdate,
    TokenOut,
    UserCreate,
    UserOut,
    UserUpdate,
)
from app.services import accounts
from app.services.common import get_scoped

router = APIRouter()


@router.post("/auth/register", response_model=TokenOut, status_code=201, tags=["auth"])
def register(data: RegisterIn, db: Session = Depends(get_db)):
    """Create a new shop (tenant) together with its first owner account."""
    _, token, exp = accounts.register(db, data)
    return TokenOut(access_token=token, expires_in=exp)


@router.post("/auth/login", response_model=TokenOut, tags=["auth"])
def login(data: LoginIn, db: Session = Depends(get_db)):
    token, exp = accounts.login(db, data.email, data.password)
    return TokenOut(access_token=token, expires_in=exp)


@router.get("/auth/me", response_model=MeOut, tags=["auth"])
def me(ctx: Ctx = Depends(get_ctx)):
    return MeOut(
        user=UserOut.model_validate(ctx.user),
        shop=ShopOut.model_validate(ctx.shop),
        permissions=sorted(p.value for p in ROLE_PERMISSIONS[ctx.role]),
    )


@router.get("/roles", tags=["users"])
def roles(ctx: Ctx = Depends(get_ctx)):
    return {role.value: sorted(p.value for p in perms) for role, perms in ROLE_PERMISSIONS.items()}


@router.get("/users", response_model=Page[UserOut], tags=["users"])
def list_users(params: PageParams = Depends(), ctx: Ctx = Depends(require(P.users_manage))):
    stmt = select(User).where(User.shop_id == ctx.shop_id)
    if params.q:
        stmt = stmt.where(User.full_name.ilike(like(params.q)) | User.email.ilike(like(params.q)))
    items, total = paginate(
        ctx.db,
        stmt,
        params,
        {"name": User.full_name, "email": User.email, "role": User.role, "created_at": User.created_at},
        "name",
        User.id,
    )
    return Page(items=items, total=total, page=params.page, page_size=params.page_size)


@router.post("/users", response_model=UserOut, status_code=201, tags=["users"])
def create_user(
    data: UserCreate, ctx: Ctx = Depends(require(P.users_manage)), idem: Idem = Depends(idempotent)
):
    return idem.commit(UserOut.model_validate(accounts.create_user(ctx, data)), 201)


@router.get("/users/{user_id}", response_model=UserOut, tags=["users"])
def get_user(user_id: int, ctx: Ctx = Depends(require(P.users_manage))):
    return get_scoped(ctx.db, User, user_id, ctx.shop_id, label="user")


@router.patch("/users/{user_id}", response_model=UserOut, tags=["users"])
def update_user(
    user_id: int,
    data: UserUpdate,
    ctx: Ctx = Depends(require(P.users_manage)),
    idem: Idem = Depends(idempotent),
):
    return idem.commit(UserOut.model_validate(accounts.update_user(ctx, user_id, data)))


@router.get("/shop", response_model=ShopOut, tags=["shop"])
def get_shop(ctx: Ctx = Depends(get_ctx)):
    return ctx.shop


@router.patch("/shop", response_model=ShopOut, tags=["shop"])
def update_shop(
    data: ShopUpdate, ctx: Ctx = Depends(require(P.shop_settings)), idem: Idem = Depends(idempotent)
):
    return idem.commit(ShopOut.model_validate(accounts.update_shop(ctx, data)))
