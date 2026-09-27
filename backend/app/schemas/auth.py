import datetime as dt
from zoneinfo import available_timezones

from pydantic import EmailStr, Field, field_validator

from app.enums import Role
from app.schemas.common import ORM, StateCode, Strict

Email = EmailStr


def _tz(value: str) -> str:
    if value not in available_timezones():
        raise ValueError("unknown IANA timezone")
    return value


class LoginIn(Strict):
    email: Email
    password: str = Field(min_length=1, max_length=200)


class TokenOut(ORM):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class ShopIn(Strict):
    name: str = Field(min_length=1, max_length=200)
    legal_name: str | None = Field(None, max_length=200)
    gstin: str | None = Field(None, pattern=r"^[0-9A-Z]{15}$")
    state_code: StateCode
    address: str | None = None
    phone: str | None = Field(None, max_length=20)
    timezone: str = "Asia/Kolkata"
    invoice_prefix: str = Field("INV-", max_length=16)
    credit_note_prefix: str = Field("CN-", max_length=16)
    po_prefix: str = Field("PO-", max_length=16)
    default_credit_days: int = Field(30, ge=0, le=365)

    _tz = field_validator("timezone")(_tz)


class ShopUpdate(Strict):
    name: str | None = Field(None, min_length=1, max_length=200)
    legal_name: str | None = Field(None, max_length=200)
    gstin: str | None = Field(None, pattern=r"^[0-9A-Z]{15}$")
    state_code: StateCode | None = None
    address: str | None = None
    phone: str | None = Field(None, max_length=20)
    timezone: str | None = None
    invoice_prefix: str | None = Field(None, max_length=16)
    credit_note_prefix: str | None = Field(None, max_length=16)
    po_prefix: str | None = Field(None, max_length=16)
    default_credit_days: int | None = Field(None, ge=0, le=365)

    @field_validator("timezone")
    @classmethod
    def _check_tz(cls, v: str | None) -> str | None:
        return None if v is None else _tz(v)


class ShopOut(ORM):
    id: int
    name: str
    legal_name: str | None
    gstin: str | None
    state_code: str
    address: str | None
    phone: str | None
    timezone: str
    currency: str
    invoice_prefix: str
    credit_note_prefix: str
    po_prefix: str
    default_credit_days: int


class RegisterIn(Strict):
    shop: ShopIn
    owner_name: str = Field(min_length=1, max_length=200)
    email: Email
    password: str = Field(min_length=8, max_length=200)


class UserCreate(Strict):
    email: Email
    full_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=200)
    role: Role


class UserUpdate(Strict):
    full_name: str | None = Field(None, min_length=1, max_length=200)
    role: Role | None = None
    is_active: bool | None = None
    password: str | None = Field(None, min_length=8, max_length=200)


class UserOut(ORM):
    id: int
    email: str
    full_name: str
    role: Role
    is_active: bool
    created_at: dt.datetime
    last_login_at: dt.datetime | None


class MeOut(ORM):
    user: UserOut
    shop: ShopOut
    permissions: list[str]
