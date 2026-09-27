import datetime as dt

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select

from app.api.serializers import credit_note_out, invoice_detail, invoice_summary, payment_out
from app.core.deps import Ctx, require
from app.core.idempotency import Idem, idempotent
from app.core.money import ZERO, q
from app.core.pagination import Page, PageParams, like, paginate, paginate_rows
from app.core.permissions import P
from app.core.timeutil import day_bounds_utc, local_today
from app.enums import InvoiceStatus, PaymentKind, PaymentMethod, PaymentStatus
from app.models import CreditNote, Customer, Invoice, LedgerEntry, Payment
from app.schemas.sales import (
    CreditNoteIn,
    CreditNoteOut,
    CustomerIn,
    CustomerOut,
    CustomerPaymentIn,
    CustomerUpdate,
    InvoiceDraftIn,
    InvoiceOut,
    InvoicePostIn,
    InvoiceSummaryOut,
    LedgerEntryOut,
    LedgerOut,
    PaymentIn,
    PaymentOut,
)
from app.services import customers as customer_svc
from app.services import invoicing

router = APIRouter()


# ================================================================== invoices
@router.get("/invoices", response_model=Page[InvoiceSummaryOut], tags=["invoices"])
def list_invoices(
    params: PageParams = Depends(),
    status: InvoiceStatus | None = None,
    payment_status: PaymentStatus | None = None,
    customer_id: int | None = None,
    start_date: dt.date | None = None,
    end_date: dt.date | None = None,
    overdue: bool | None = None,
    ctx: Ctx = Depends(require(P.invoices_create)),
):
    today = local_today(ctx.shop.timezone)
    stmt = select(Invoice).outerjoin(Customer, Invoice.customer_id == Customer.id).where(
        Invoice.shop_id == ctx.shop_id
    )
    if not ctx.can(P.invoices_read_all):
        stmt = stmt.where(or_(Invoice.created_by == ctx.user.id, Invoice.posted_by == ctx.user.id))
    if status:
        stmt = stmt.where(Invoice.status == status)
    if payment_status:
        stmt = stmt.where(Invoice.payment_status == payment_status, Invoice.status != InvoiceStatus.draft)
    if customer_id is not None:
        stmt = stmt.where(Invoice.customer_id == customer_id)
    if start_date:
        stmt = stmt.where(Invoice.invoice_date >= start_date)
    if end_date:
        stmt = stmt.where(Invoice.invoice_date <= end_date)
    if overdue is True:
        stmt = stmt.where(Invoice.status != InvoiceStatus.draft, Invoice.balance_due > 0, Invoice.due_date < today)
    if params.q:
        term = like(params.q)
        stmt = stmt.where(or_(Invoice.number.ilike(term), Customer.name.ilike(term), Customer.phone.ilike(term)))
    items, total = paginate(
        ctx.db,
        stmt,
        params,
        {
            "created_at": Invoice.created_at,
            "invoice_date": Invoice.invoice_date,
            "number": Invoice.number,
            "grand_total": Invoice.grand_total,
            "balance_due": Invoice.balance_due,
            "due_date": Invoice.due_date,
        },
        "-created_at",
        Invoice.id,
    )
    return Page(
        items=[invoice_summary(i, today) for i in items], total=total, page=params.page, page_size=params.page_size
    )


@router.post("/invoices", response_model=InvoiceOut, status_code=201, tags=["invoices"])
def create_invoice_draft(
    data: InvoiceDraftIn, ctx: Ctx = Depends(require(P.invoices_create)), idem: Idem = Depends(idempotent)
):
    """Create a draft. Stock is not reserved or deducted until the invoice is posted."""
    inv = invoicing.create_draft(ctx, data)
    return idem.commit(invoice_detail(ctx, inv.id), 201)


@router.get("/invoices/{invoice_id}", response_model=InvoiceOut, tags=["invoices"])
def get_invoice(invoice_id: int, ctx: Ctx = Depends(require(P.invoices_create))):
    return invoice_detail(ctx, invoice_id)


@router.put("/invoices/{invoice_id}", response_model=InvoiceOut, tags=["invoices"])
def update_invoice_draft(
    invoice_id: int,
    data: InvoiceDraftIn,
    ctx: Ctx = Depends(require(P.invoices_create)),
    idem: Idem = Depends(idempotent),
):
    invoicing.update_draft(ctx, invoice_id, data)
    return idem.commit(invoice_detail(ctx, invoice_id))


@router.delete("/invoices/{invoice_id}", tags=["invoices"])
def delete_invoice_draft(
    invoice_id: int, ctx: Ctx = Depends(require(P.invoices_create)), idem: Idem = Depends(idempotent)
):
    invoicing.delete_draft(ctx, invoice_id)
    return idem.commit({"deleted": True, "id": invoice_id})


@router.post("/invoices/{invoice_id}/post", response_model=InvoiceOut, tags=["invoices"])
def post_invoice(
    invoice_id: int,
    data: InvoicePostIn | None = None,
    ctx: Ctx = Depends(require(P.invoices_create)),
    idem: Idem = Depends(idempotent),
):
    """Post a draft: validates and deducts stock atomically, assigns the invoice number, records payments.

    Any unpaid remainder goes to the customer's khata (credit sale)."""
    invoicing.post_invoice(ctx, invoice_id, data or InvoicePostIn())
    return idem.commit(invoice_detail(ctx, invoice_id))


@router.post("/invoices/{invoice_id}/payments", response_model=PaymentOut, status_code=201, tags=["payments"])
def record_payment(
    invoice_id: int,
    data: PaymentIn,
    ctx: Ctx = Depends(require(P.payments_record)),
    idem: Idem = Depends(idempotent),
):
    payment = invoicing.record_payment(ctx, invoice_id, data)
    inv = ctx.db.get(Invoice, invoice_id)
    return idem.commit(payment_out(payment, inv.number), 201)


@router.post("/invoices/{invoice_id}/credit-notes", response_model=CreditNoteOut, status_code=201,
             tags=["credit notes"])
def create_credit_note(
    invoice_id: int,
    data: CreditNoteIn,
    ctx: Ctx = Depends(require(P.credit_notes_create)),
    idem: Idem = Depends(idempotent),
):
    """Correct or return (part of) a posted invoice. Optionally restores stock and refunds the excess."""
    note = invoicing.create_credit_note(ctx, invoice_id, data)
    inv = ctx.db.get(Invoice, invoice_id)
    return idem.commit(credit_note_out(note, inv.number), 201)


# ================================================================== payments / credit notes
@router.get("/payments", response_model=Page[PaymentOut], tags=["payments"])
def list_payments(
    params: PageParams = Depends(),
    method: PaymentMethod | None = None,
    kind: PaymentKind | None = None,
    invoice_id: int | None = None,
    customer_id: int | None = None,
    start_date: dt.date | None = None,
    end_date: dt.date | None = None,
    ctx: Ctx = Depends(require(P.invoices_read_all)),
):
    stmt = select(Payment, Invoice.number).join(Invoice, Payment.invoice_id == Invoice.id).where(
        Payment.shop_id == ctx.shop_id
    )
    if method:
        stmt = stmt.where(Payment.method == method)
    if kind:
        stmt = stmt.where(Payment.kind == kind)
    if invoice_id is not None:
        stmt = stmt.where(Payment.invoice_id == invoice_id)
    if customer_id is not None:
        stmt = stmt.where(Payment.customer_id == customer_id)
    if start_date or end_date:
        lo, hi = day_bounds_utc(start_date or dt.date(1970, 1, 1), end_date or dt.date(9998, 12, 30),
                                ctx.shop.timezone)
        stmt = stmt.where(Payment.paid_at >= lo, Payment.paid_at < hi)
    if params.q:
        term = like(params.q)
        stmt = stmt.where(or_(Invoice.number.ilike(term), Payment.reference.ilike(term)))
    rows, total = paginate_rows(
        ctx.db, stmt, params, {"paid_at": Payment.paid_at, "amount": Payment.amount}, "-paid_at", Payment.id
    )
    return Page(items=[payment_out(p, n) for p, n in rows], total=total, page=params.page,
                page_size=params.page_size)


@router.get("/credit-notes", response_model=Page[CreditNoteOut], tags=["credit notes"])
def list_credit_notes(
    params: PageParams = Depends(),
    invoice_id: int | None = None,
    customer_id: int | None = None,
    start_date: dt.date | None = None,
    end_date: dt.date | None = None,
    ctx: Ctx = Depends(require(P.invoices_read_all)),
):
    stmt = select(CreditNote).where(CreditNote.shop_id == ctx.shop_id)
    if invoice_id is not None:
        stmt = stmt.where(CreditNote.invoice_id == invoice_id)
    if customer_id is not None:
        stmt = stmt.where(CreditNote.customer_id == customer_id)
    if start_date:
        stmt = stmt.where(CreditNote.note_date >= start_date)
    if end_date:
        stmt = stmt.where(CreditNote.note_date <= end_date)
    if params.q:
        stmt = stmt.where(or_(CreditNote.number.ilike(like(params.q)), CreditNote.reason.ilike(like(params.q))))
    items, total = paginate(
        ctx.db, stmt, params, {"issued_at": CreditNote.issued_at, "total": CreditNote.total}, "-issued_at",
        CreditNote.id,
    )
    numbers = dict(
        ctx.db.execute(select(Invoice.id, Invoice.number).where(Invoice.id.in_({n.invoice_id for n in items}))).all()
    ) if items else {}
    return Page(items=[credit_note_out(n, numbers.get(n.invoice_id)) for n in items], total=total,
                page=params.page, page_size=params.page_size)


# ================================================================== customers & khata
@router.get("/customers", response_model=Page[CustomerOut], tags=["customers"])
def list_customers(
    params: PageParams = Depends(),
    status: str = Query("active", pattern="^(active|inactive|all)$"),
    has_balance: bool | None = None,
    overdue: bool | None = None,
    ctx: Ctx = Depends(require(P.customers_read)),
):
    stmt, balance_col, overdue_col = customer_svc.customers_with_balances(ctx)
    if status != "all":
        stmt = stmt.where(Customer.is_active.is_(status == "active"))
    if params.q:
        term = like(params.q)
        stmt = stmt.where(or_(Customer.name.ilike(term), Customer.phone.ilike(term), Customer.email.ilike(term)))
    if has_balance is True:
        stmt = stmt.where(balance_col > 0)
    if overdue is True:
        stmt = stmt.where(overdue_col > 0)
    sort_map = {"name": func.lower(Customer.name), "balance": balance_col, "overdue": overdue_col,
                "created_at": Customer.created_at}
    rows, total = paginate_rows(ctx.db, stmt, params, sort_map, "name", Customer.id)
    return Page(items=[customer_svc.to_out(c, b, o) for c, b, o in rows], total=total, page=params.page,
                page_size=params.page_size)


@router.post("/customers", response_model=CustomerOut, status_code=201, tags=["customers"])
def create_customer(
    data: CustomerIn, ctx: Ctx = Depends(require(P.customers_write)), idem: Idem = Depends(idempotent)
):
    return idem.commit(customer_svc.to_out(customer_svc.create(ctx, data)), 201)


@router.get("/customers/{customer_id}", response_model=CustomerOut, tags=["customers"])
def get_customer(customer_id: int, ctx: Ctx = Depends(require(P.customers_read))):
    return customer_svc.get_with_balance(ctx, customer_id)


@router.patch("/customers/{customer_id}", response_model=CustomerOut, tags=["customers"])
def update_customer(
    customer_id: int,
    data: CustomerUpdate,
    ctx: Ctx = Depends(require(P.customers_write)),
    idem: Idem = Depends(idempotent),
):
    customer_svc.update(ctx, customer_id, data)
    return idem.commit(customer_svc.get_with_balance(ctx, customer_id))


@router.get("/customers/{customer_id}/ledger", response_model=LedgerOut, tags=["khata"])
def customer_ledger(
    customer_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    ctx: Ctx = Depends(require(P.khata_read)),
):
    """Khata ledger with running balance. The balance is derived from ledger rows and reconciled against
    the open balances of the customer's invoices."""
    customer = customer_svc.get_with_balance(ctx, customer_id)
    running = func.sum(LedgerEntry.debit - LedgerEntry.credit).over(
        order_by=(LedgerEntry.occurred_at, LedgerEntry.id)
    )
    inner = (
        select(LedgerEntry, running.label("running_balance"))
        .where(LedgerEntry.shop_id == ctx.shop_id, LedgerEntry.customer_id == customer_id)
        .subquery()
    )
    total = ctx.db.scalar(
        select(func.count()).where(LedgerEntry.shop_id == ctx.shop_id, LedgerEntry.customer_id == customer_id)
    )
    rows = ctx.db.execute(
        select(inner).order_by(inner.c.occurred_at.desc(), inner.c.id.desc())
        .limit(page_size).offset((page - 1) * page_size)
    ).mappings().all()
    entries = [LedgerEntryOut.model_validate(dict(r)) for r in rows]

    today = local_today(ctx.shop.timezone)
    open_invoices = ctx.db.scalars(
        select(Invoice).where(customer_svc.open_invoice_filter(ctx.shop_id, customer_id))
        .order_by(Invoice.invoice_date, Invoice.id)
    ).all()
    outstanding = q(sum((i.balance_due for i in open_invoices), ZERO))
    overdue = [i for i in open_invoices if i.due_date and i.due_date < today]
    return LedgerOut(
        customer=customer,
        entries=entries,
        total_entries=total,
        balance=customer.balance,
        invoice_outstanding=outstanding,
        overdue_amount=q(sum((i.balance_due for i in overdue), ZERO)),
        oldest_overdue_date=min((i.due_date for i in overdue), default=None),
        reconciled=customer.balance == outstanding,
        open_invoices=[invoice_summary(i, today) for i in open_invoices],
    )


@router.post("/customers/{customer_id}/payments", response_model=list[PaymentOut], status_code=201,
             tags=["khata"])
def record_customer_payment(
    customer_id: int,
    data: CustomerPaymentIn,
    ctx: Ctx = Depends(require(P.payments_record)),
    idem: Idem = Depends(idempotent),
):
    """Receive a khata payment; it is allocated to open invoices oldest-first."""
    payments = invoicing.record_customer_payment(ctx, customer_id, data)
    numbers = dict(ctx.db.execute(
        select(Invoice.id, Invoice.number).where(Invoice.id.in_({p.invoice_id for p in payments}))
    ).all())
    return idem.commit([payment_out(p, numbers.get(p.invoice_id)) for p in payments], 201)
