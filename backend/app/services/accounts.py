from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import Ctx
from app.core.errors import Conflict, Unauthorized, ValidationFailed
from app.core.security import create_access_token, hash_password, verify_password
from app.core.timeutil import utcnow
from app.enums import Role
from app.models import Shop, User
from app.schemas.auth import RegisterIn, ShopUpdate, UserCreate, UserUpdate
from app.services.common import get_scoped


def _email_taken(db: Session, email: str) -> bool:
    return db.scalar(select(func.count()).where(func.lower(User.email) == email.lower())) > 0


def register(db: Session, data: RegisterIn) -> tuple[User, str, int]:
    if _email_taken(db, data.email):
        raise Conflict("an account with this email already exists", code="email_taken")
    shop = Shop(**data.shop.model_dump())
    db.add(shop)
    db.flush()
    user = User(
        shop_id=shop.id,
        email=data.email.lower(),
        full_name=data.owner_name,
        password_hash=hash_password(data.password),
        role=Role.owner,
    )
    db.add(user)
    db.commit()
    token, exp = create_access_token(user.id, shop.id, user.role.value)
    return user, token, exp


def login(db: Session, email: str, password: str) -> tuple[str, int]:
    user = db.scalars(select(User).where(func.lower(User.email) == email.lower())).first()
    if user is None or not verify_password(password, user.password_hash) or not user.is_active:
        raise Unauthorized("invalid email or password")
    user.last_login_at = utcnow()
    db.commit()
    return create_access_token(user.id, user.shop_id, user.role.value)


def create_user(ctx: Ctx, data: UserCreate) -> User:
    if _email_taken(ctx.db, data.email):
        raise Conflict("an account with this email already exists", code="email_taken")
    user = User(
        shop_id=ctx.shop_id,
        email=data.email.lower(),
        full_name=data.full_name,
        password_hash=hash_password(data.password),
        role=data.role,
    )
    ctx.db.add(user)
    ctx.db.flush()
    return user


def update_user(ctx: Ctx, user_id: int, data: UserUpdate) -> User:
    user = get_scoped(ctx.db, User, user_id, ctx.shop_id, lock=True, label="user")
    changes = data.model_dump(exclude_unset=True)
    demoting_owner = user.role == Role.owner and (
        changes.get("role", Role.owner) != Role.owner or changes.get("is_active") is False
    )
    if demoting_owner:
        owners = ctx.db.scalar(
            select(func.count()).where(
                User.shop_id == ctx.shop_id, User.role == Role.owner, User.is_active.is_(True)
            )
        )
        if owners <= 1:
            raise ValidationFailed("a shop must keep at least one active owner", code="last_owner")
    if "password" in changes:
        user.password_hash = hash_password(changes.pop("password"))
    for key, value in changes.items():
        setattr(user, key, value)
    ctx.db.flush()
    return user


def update_shop(ctx: Ctx, data: ShopUpdate) -> Shop:
    shop = ctx.db.get(Shop, ctx.shop_id, with_for_update=True)
    for key, value in data.model_dump(exclude_unset=True).items():
        if value is None and key in {"name", "state_code", "timezone"}:
            continue
        setattr(shop, key, value)
    ctx.db.flush()
    return shop
