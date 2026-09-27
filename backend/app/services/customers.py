import datetime as dt
from decimal import Decimal

from sqlalchemy import Select, and_, func, select
from sqlalchemy.exc import IntegrityError

from app.core.deps import Ctx
from app.core.errors import Conflict
from app.core.money import ZERO, q
from app.core.timeutil import local_today
from app.enums import InvoiceStatus
from app.models import Customer, Invoice, LedgerEntry
from app.schemas.sales import CustomerIn, CustomerOut, CustomerUpdate
from app.services.common import get_scoped


def balance_subquery(shop_id: int):
    return (
        select(
            LedgerEntry.customer_id.label("customer_id"),
            func.sum(LedgerEntry.debit - LedgerEntry.credit).label("balance"),
        )
        .where(LedgerEntry.shop_id == shop_id)
        .group_by(LedgerEntry.customer_id)
        .subquery()
    )


def overdue_subquery(shop_id: int, today: dt.date):
    return (
        select(Invoice.customer_id.label("customer_id"), func.sum(Invoice.balance_due).label("overdue"))
        .where(
            Invoice.shop_id == shop_id,
            Invoice.status != InvoiceStatus.draft,
            Invoice.balance_due > 0,
            Invoice.due_date < today,
        )
        .group_by(Invoice.customer_id)
        .subquery()
    )


def customers_with_balances(ctx: Ctx) -> tuple[Select, object, object]:
    bal = balance_subquery(ctx.shop_id)
    over = overdue_subquery(ctx.shop_id, local_today(ctx.shop.timezone))
    balance_col = func.coalesce(bal.c.balance, 0)
    overdue_col = func.coalesce(over.c.overdue, 0)
    stmt = (
        select(Customer, balance_col.label("balance"), overdue_col.label("overdue"))
        .outerjoin(bal, bal.c.customer_id == Customer.id)
        .outerjoin(over, over.c.customer_id == Customer.id)
        .where(Customer.shop_id == ctx.shop_id)
    )
    return stmt, balance_col, overdue_col


def to_out(customer: Customer, balance: Decimal | None = None, overdue: Decimal | None = None) -> CustomerOut:
    out = CustomerOut.model_validate(customer)
    out.balance = q(balance or ZERO)
    out.overdue_amount = q(overdue or ZERO)
    return out


def get_with_balance(ctx: Ctx, customer_id: int) -> CustomerOut:
    stmt, _, _ = customers_with_balances(ctx)
    row = ctx.db.execute(stmt.where(Customer.id == customer_id)).first()
    if row is None:
        get_scoped(ctx.db, Customer, customer_id, ctx.shop_id, label="customer")  # raises NotFound
    return to_out(*row)


def _flush(ctx: Ctx) -> None:
    try:
        with ctx.db.begin_nested():
            ctx.db.flush()
    except IntegrityError as exc:
        if "uq_customers_shop_phone" in str(exc.orig):
            raise Conflict("a customer with this phone number already exists", code="phone_taken") from exc
        raise


def create(ctx: Ctx, data: CustomerIn) -> Customer:
    customer = Customer(shop_id=ctx.shop_id, is_active=True, **data.model_dump())
    ctx.db.add(customer)
    _flush(ctx)
    return customer


def update(ctx: Ctx, customer_id: int, data: CustomerUpdate) -> Customer:
    customer = get_scoped(ctx.db, Customer, customer_id, ctx.shop_id, lock=True, label="customer")
    for key, value in data.model_dump(exclude_unset=True).items():
        if key in {"name", "is_active"} and value is None:
            continue
        setattr(customer, key, value)
    _flush(ctx)
    return customer


def open_invoice_filter(shop_id: int, customer_id: int):
    return and_(
        Invoice.shop_id == shop_id,
        Invoice.customer_id == customer_id,
        Invoice.status != InvoiceStatus.draft,
        Invoice.balance_due > 0,
    )
