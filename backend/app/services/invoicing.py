"""Invoices, payments, credit notes and the customer khata ledger.

Every public function runs inside the caller's transaction; the API layer commits (together with the
idempotency record). Any exception rolls everything back, including stock and ledger changes.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.deps import Ctx
from app.core.errors import Conflict, Forbidden, InsufficientStock, NotFound, ValidationFailed
from app.core.money import ZERO, q
from app.core.permissions import P
from app.core.timeutil import local_today, utcnow
from app.enums import (
    InvoiceStatus,
    LedgerEntryType,
    MovementType,
    PaymentKind,
    PaymentStatus,
)
from app.models import (
    CreditNote,
    CreditNoteItem,
    Customer,
    Invoice,
    InvoiceItem,
    LedgerEntry,
    Payment,
    Product,
)
from app.schemas.sales import CreditNoteIn, CustomerPaymentIn, InvoiceDraftIn, InvoicePostIn, PaymentIn
from app.services import tax
from app.services.common import get_scoped, next_counter
from app.services.inventory import apply_movement, lock_products


# ------------------------------------------------------------------ helpers
def _visible_invoice(ctx: Ctx, invoice_id: int, *, lock: bool = False) -> Invoice:
    inv = get_scoped(ctx.db, Invoice, invoice_id, ctx.shop_id, lock=lock, label="invoice")
    if not ctx.can(P.invoices_read_all) and ctx.user.id not in (inv.created_by, inv.posted_by):
        raise NotFound(f"invoice {invoice_id} not found")
    return inv


def _customer(ctx: Ctx, customer_id: int | None) -> Customer | None:
    if customer_id is None:
        return None
    return get_scoped(ctx.db, Customer, customer_id, ctx.shop_id, label="customer")


def _refresh_payment_state(inv: Invoice) -> None:
    inv.balance_due = inv.grand_total - inv.credited_total - inv.amount_paid
    if inv.balance_due < ZERO:  # pragma: no cover - guarded by callers
        raise ValidationFailed("invoice would be over-paid")
    if inv.balance_due == ZERO:
        inv.payment_status = PaymentStatus.paid
    elif inv.amount_paid > ZERO:
        inv.payment_status = PaymentStatus.partial
    else:
        inv.payment_status = PaymentStatus.unpaid


def _ledger(
    ctx: Ctx,
    customer_id: int | None,
    entry_type: LedgerEntryType,
    *,
    debit: Decimal = ZERO,
    credit: Decimal = ZERO,
    description: str,
    occurred_at: dt.datetime,
    invoice_id: int | None = None,
    payment_id: int | None = None,
    credit_note_id: int | None = None,
) -> None:
    if customer_id is None or (debit == ZERO and credit == ZERO):
        return
    ctx.db.add(
        LedgerEntry(
            shop_id=ctx.shop_id,
            customer_id=customer_id,
            entry_type=entry_type,
            debit=debit,
            credit=credit,
            description=description,
            occurred_at=occurred_at,
            invoice_id=invoice_id,
            payment_id=payment_id,
            credit_note_id=credit_note_id,
            created_by=ctx.user.id,
        )
    )


def customer_balance(db: Session, shop_id: int, customer_id: int) -> Decimal:
    value = db.scalar(
        select(func.coalesce(func.sum(LedgerEntry.debit - LedgerEntry.credit), 0)).where(
            LedgerEntry.shop_id == shop_id, LedgerEntry.customer_id == customer_id
        )
    )
    return q(value)


# ------------------------------------------------------------------ drafts
def _build_items(ctx: Ctx, inv: Invoice, items_in, products: dict[int, Product]) -> None:
    can_override = ctx.can(P.products_write)
    totals = tax.Totals()
    new_items: list[InvoiceItem] = []
    for idx, item in enumerate(items_in, start=1):
        product = products[item.product_id]
        if not product.is_active:
            raise ValidationFailed(f"product {product.sku} is archived", code="product_archived")
        if item.unit_price is not None and item.unit_price != product.sale_price and not can_override:
            raise Forbidden("only owners and managers can override the sale price")
        unit_price = item.unit_price if item.unit_price is not None else product.sale_price
        gross = q(unit_price * item.quantity)
        try:
            discount = tax.discount_from(gross, item.discount_amount, item.discount_percent)
            line = tax.compute_line(item.quantity, unit_price, product.gst_rate, discount, inv.supply_type)
        except ValueError as exc:
            raise ValidationFailed(f"line {idx} ({product.sku}): {exc}") from exc
        totals.add(line)
        new_items.append(_item_from(ctx.shop_id, idx, product, item.quantity, unit_price, line))
    inv.items = new_items
    _apply_totals(inv, totals)


def _item_from(shop_id: int, line_no: int, product: Product, qty: int, unit_price: Decimal, line) -> InvoiceItem:
    return InvoiceItem(
        shop_id=shop_id,
        line_no=line_no,
        product_id=product.id,
        product_name=product.name,
        sku=product.sku,
        hsn_code=product.hsn_code,
        category_id=product.category_id,
        category_name=product.category.name if product.category else None,
        unit=product.unit,
        quantity=qty,
        unit_price=unit_price,
        cost_price=product.cost_price,
        gst_rate=product.gst_rate,
        gross_amount=line.gross,
        discount_amount=line.discount,
        taxable_value=line.taxable,
        cgst_amount=line.cgst,
        sgst_amount=line.sgst,
        igst_amount=line.igst,
        line_total=line.total,
    )


def _apply_totals(inv: Invoice, totals: tax.Totals) -> None:
    inv.subtotal = totals.subtotal
    inv.discount_total = totals.discount_total
    inv.taxable_total = totals.taxable_total
    inv.cgst_total = totals.cgst_total
    inv.sgst_total = totals.sgst_total
    inv.igst_total = totals.igst_total
    inv.grand_total = totals.grand_total
    inv.balance_due = totals.grand_total


def _set_header(ctx: Ctx, inv: Invoice, data: InvoiceDraftIn) -> None:
    customer = _customer(ctx, data.customer_id)
    if customer is not None and not customer.is_active:
        raise ValidationFailed("customer is inactive")
    place = data.place_of_supply or (customer.state_code if customer and customer.state_code else None)
    place = place or ctx.shop.state_code
    inv.customer_id = customer.id if customer else None
    inv.place_of_supply = place
    inv.supply_type = tax.supply_type_for(ctx.shop.state_code, place)
    inv.due_date = data.due_date
    inv.notes = data.notes


def _products_for(ctx: Ctx, items_in) -> dict[int, Product]:
    ids = {i.product_id for i in items_in}
    rows = ctx.db.scalars(select(Product).where(Product.shop_id == ctx.shop_id, Product.id.in_(ids))).all()
    found = {p.id: p for p in rows}
    missing = sorted(ids - found.keys())
    if missing:
        raise NotFound(f"product(s) {missing} not found")
    return found


def create_draft(ctx: Ctx, data: InvoiceDraftIn) -> Invoice:
    inv = Invoice(
        shop_id=ctx.shop_id,
        status=InvoiceStatus.draft,
        created_by=ctx.user.id,
        amount_paid=ZERO,
        credited_total=ZERO,
        credit_amount=ZERO,
        payment_status=PaymentStatus.unpaid,
    )
    _set_header(ctx, inv, data)
    _build_items(ctx, inv, data.items, _products_for(ctx, data.items))
    ctx.db.add(inv)
    ctx.db.flush()
    return inv


def update_draft(ctx: Ctx, invoice_id: int, data: InvoiceDraftIn) -> Invoice:
    inv = _visible_invoice(ctx, invoice_id, lock=True)
    if inv.status != InvoiceStatus.draft:
        raise Conflict("posted invoices cannot be edited; issue a credit note instead", code="invoice_immutable")
    _set_header(ctx, inv, data)
    inv.items.clear()
    ctx.db.flush()
    _build_items(ctx, inv, data.items, _products_for(ctx, data.items))
    ctx.db.flush()
    return inv


def delete_draft(ctx: Ctx, invoice_id: int) -> None:
    inv = _visible_invoice(ctx, invoice_id, lock=True)
    if inv.status != InvoiceStatus.draft:
        raise Conflict("posted invoices cannot be deleted; issue a credit note instead", code="invoice_immutable")
    ctx.db.delete(inv)
    ctx.db.flush()


# ------------------------------------------------------------------ posting
def post_invoice(ctx: Ctx, invoice_id: int, data: InvoicePostIn) -> Invoice:
    """Atomically post a draft: lock stock, validate, re-snapshot lines, deduct stock, number, take payment."""
    inv = _visible_invoice(ctx, invoice_id, lock=True)
    if inv.status != InvoiceStatus.draft:
        raise Conflict(f"invoice is already {inv.status.value}", code="invoice_not_draft")
    if not inv.items:
        raise ValidationFailed("invoice has no items")

    products = lock_products(ctx.db, ctx.shop_id, [i.product_id for i in inv.items])

    # Validate availability for the aggregated quantity of each product before touching anything.
    wanted: dict[int, int] = defaultdict(int)
    for item in inv.items:
        wanted[item.product_id] += item.quantity
    shortages = [
        {"product_id": pid, "sku": products[pid].sku, "available": products[pid].quantity, "requested": qty}
        for pid, qty in wanted.items()
        if products[pid].quantity < qty
    ]
    if shortages:
        detail = ", ".join(f"{s['sku']} (available {s['available']}, requested {s['requested']})" for s in shortages)
        raise InsufficientStock(f"insufficient stock: {detail}", extra={"shortages": shortages})

    # Re-snapshot product data at posting time and recompute every line.
    totals = tax.Totals()
    for item in inv.items:
        product = products[item.product_id]
        if not product.is_active:
            raise ValidationFailed(f"product {product.sku} is archived", code="product_archived")
        line = tax.compute_line(item.quantity, item.unit_price, product.gst_rate, item.discount_amount,
                                inv.supply_type)
        totals.add(line)
        fresh = _item_from(ctx.shop_id, item.line_no, product, item.quantity, item.unit_price, line)
        for col in ("product_name", "sku", "hsn_code", "category_id", "category_name", "unit", "cost_price",
                    "gst_rate", "gross_amount", "discount_amount", "taxable_value", "cgst_amount",
                    "sgst_amount", "igst_amount", "line_total"):
            setattr(item, col, getattr(fresh, col))
    ctx.db.flush()  # item snapshots must be written while the invoice is still a draft
    _apply_totals(inv, totals)

    now = utcnow()
    today = local_today(ctx.shop.timezone, now)
    seq = next_counter(ctx.db, ctx.shop_id, "invoice")
    inv.number = f"{ctx.shop.invoice_prefix}{seq:06d}"
    inv.status = InvoiceStatus.posted
    inv.invoice_date = today
    inv.posted_at = now
    inv.posted_by = ctx.user.id
    ctx.db.flush()

    for item in inv.items:
        apply_movement(
            ctx.db,
            products[item.product_id],
            MovementType.sale,
            -item.quantity,
            user_id=ctx.user.id,
            reason=f"Invoice {inv.number}",
            reference_type="invoice",
            reference_id=inv.id,
            unit_cost=item.cost_price,
        )

    paid = sum((p.amount for p in data.payments), ZERO)
    if paid > inv.grand_total:
        raise ValidationFailed(
            f"payments ({paid}) exceed the invoice total ({inv.grand_total})", code="overpayment"
        )
    credit = inv.grand_total - paid
    if credit > ZERO:
        if inv.customer_id is None:
            raise ValidationFailed(
                "walk-in invoices must be paid in full; select a customer to sell on credit (khata)",
                code="credit_requires_customer",
            )
        customer = ctx.db.get(Customer, inv.customer_id)
        if customer.credit_limit is not None:
            exposure = customer_balance(ctx.db, ctx.shop_id, customer.id) + credit
            if exposure > customer.credit_limit:
                raise Conflict(
                    f"credit limit exceeded: outstanding would be {exposure}, limit {customer.credit_limit}",
                    code="credit_limit_exceeded",
                )
    inv.credit_amount = credit
    if inv.due_date is None and credit > ZERO:
        inv.due_date = today + dt.timedelta(days=ctx.shop.default_credit_days)

    _ledger(ctx, inv.customer_id, LedgerEntryType.invoice, debit=inv.grand_total,
            description=f"Invoice {inv.number}", occurred_at=now, invoice_id=inv.id)
    inv.amount_paid = ZERO
    for pay in data.payments:
        _add_receipt(ctx, inv, pay, now)
    _refresh_payment_state(inv)
    ctx.db.flush()
    return inv


def _add_receipt(ctx: Ctx, inv: Invoice, pay: PaymentIn, default_time: dt.datetime) -> Payment:
    payment = Payment(
        shop_id=ctx.shop_id,
        invoice_id=inv.id,
        customer_id=inv.customer_id,
        kind=PaymentKind.receipt,
        method=pay.method,
        amount=pay.amount,
        reference=pay.reference,
        paid_at=pay.paid_at or default_time,
        created_by=ctx.user.id,
    )
    ctx.db.add(payment)
    ctx.db.flush()
    inv.amount_paid += pay.amount
    _ledger(ctx, inv.customer_id, LedgerEntryType.payment, credit=pay.amount,
            description=f"Payment ({pay.method.value}) for {inv.number}", occurred_at=payment.paid_at,
            invoice_id=inv.id, payment_id=payment.id)
    return payment


# ------------------------------------------------------------------ payments
def record_payment(ctx: Ctx, invoice_id: int, data: PaymentIn) -> Payment:
    inv = _visible_invoice(ctx, invoice_id, lock=True)
    if inv.status == InvoiceStatus.draft:
        raise Conflict("post the invoice before recording payments", code="invoice_not_posted")
    if data.amount > inv.balance_due:
        raise ValidationFailed(
            f"payment ({data.amount}) exceeds the balance due ({inv.balance_due})", code="overpayment"
        )
    payment = _add_receipt(ctx, inv, data, utcnow())
    _refresh_payment_state(inv)
    ctx.db.flush()
    return payment


def record_customer_payment(ctx: Ctx, customer_id: int, data: CustomerPaymentIn) -> list[Payment]:
    """Settle khata: allocate one payment across the customer's open invoices, oldest first."""
    customer = get_scoped(ctx.db, Customer, customer_id, ctx.shop_id, lock=True, label="customer")
    open_invoices = ctx.db.scalars(
        select(Invoice)
        .where(
            Invoice.shop_id == ctx.shop_id,
            Invoice.customer_id == customer.id,
            Invoice.status != InvoiceStatus.draft,
            Invoice.balance_due > 0,
        )
        .order_by(Invoice.invoice_date, Invoice.id)
        .with_for_update(of=Invoice)
    ).all()
    outstanding = sum((i.balance_due for i in open_invoices), ZERO)
    if data.amount > outstanding:
        raise ValidationFailed(
            f"payment ({data.amount}) exceeds the customer's outstanding invoices ({outstanding})",
            code="overpayment",
        )
    remaining = data.amount
    now = utcnow()
    payments = []
    for inv in open_invoices:
        if remaining == ZERO:
            break
        portion = min(remaining, inv.balance_due)
        payments.append(_add_receipt(ctx, inv, data.model_copy(update={"amount": portion}), now))
        _refresh_payment_state(inv)
        remaining -= portion
    ctx.db.flush()
    return payments


# ------------------------------------------------------------------ credit notes
def create_credit_note(ctx: Ctx, invoice_id: int, data: CreditNoteIn) -> CreditNote:
    inv = get_scoped(ctx.db, Invoice, invoice_id, ctx.shop_id, lock=True, label="invoice")
    if inv.status != InvoiceStatus.posted:
        raise Conflict(f"cannot credit a {inv.status.value} invoice", code="invoice_not_creditable")

    by_id = {i.id: i for i in inv.items}
    prior = _credited_by_item(ctx.db, list(by_id))
    requested: dict[int, int] = defaultdict(int)
    for line in data.items:
        if line.invoice_item_id not in by_id:
            raise NotFound(f"invoice item {line.invoice_item_id} is not on invoice {inv.number}")
        requested[line.invoice_item_id] += line.quantity

    now = utcnow()
    note = CreditNote(
        shop_id=ctx.shop_id,
        invoice_id=inv.id,
        customer_id=inv.customer_id,
        reason=data.reason,
        restock=data.restock,
        note_date=local_today(ctx.shop.timezone, now),
        issued_at=now,
        created_by=ctx.user.id,
        refund_amount=ZERO,
    )
    totals = {k: ZERO for k in ("gross", "discount", "taxable", "cgst", "sgst", "igst", "total")}
    for item_id, qty in requested.items():
        item = by_id[item_id]
        done = prior.get(item_id)
        already = done["quantity"] if done else 0
        if qty > item.quantity - already:
            raise ValidationFailed(
                f"{item.sku}: can credit at most {item.quantity - already} more unit(s)", code="over_credit"
            )
        final = qty == item.quantity - already
        amounts = {}
        for field, col in (("gross", "gross_amount"), ("discount", "discount_amount"),
                           ("taxable", "taxable_value"), ("cgst", "cgst_amount"), ("sgst", "sgst_amount"),
                           ("igst", "igst_amount")):
            original = getattr(item, col)
            if final:  # the last return takes the exact remainder so totals never drift by a paisa
                amounts[field] = original - (done[field] if done else ZERO)
            else:
                amounts[field] = tax.prorate(original, qty, item.quantity)
        amounts["total"] = amounts["taxable"] + amounts["cgst"] + amounts["sgst"] + amounts["igst"]
        for k in totals:
            totals[k] += amounts[k]
        note.items.append(
            CreditNoteItem(
                shop_id=ctx.shop_id,
                invoice_item_id=item.id,
                product_id=item.product_id,
                product_name=item.product_name,
                sku=item.sku,
                quantity=qty,
                unit_price=item.unit_price,
                gst_rate=item.gst_rate,
                gross_amount=amounts["gross"],
                discount_amount=amounts["discount"],
                taxable_value=amounts["taxable"],
                cgst_amount=amounts["cgst"],
                sgst_amount=amounts["sgst"],
                igst_amount=amounts["igst"],
                line_total=amounts["total"],
            )
        )

    note.gross_amount = totals["gross"]
    note.discount_total = totals["discount"]
    note.taxable_total = totals["taxable"]
    note.cgst_total = totals["cgst"]
    note.sgst_total = totals["sgst"]
    note.igst_total = totals["igst"]
    note.total = totals["total"]

    unpaid = inv.grand_total - inv.credited_total - inv.amount_paid
    excess = note.total - unpaid
    if excess > ZERO and data.refund_method is None:
        raise ValidationFailed(
            f"credit exceeds the unpaid balance by {excess}; choose a refund_method", code="refund_required",
            extra={"refund_amount": str(excess)},
        )
    if excess > ZERO:  # credit notes are append-only, so refund details are set before the insert
        note.refund_amount = excess
        note.refund_method = data.refund_method
    seq = next_counter(ctx.db, ctx.shop_id, "credit_note")
    note.number = f"{ctx.shop.credit_note_prefix}{seq:06d}"
    ctx.db.add(note)
    ctx.db.flush()

    if data.restock:
        products = lock_products(ctx.db, ctx.shop_id, [ci.product_id for ci in note.items])
        for ci in note.items:
            apply_movement(ctx.db, products[ci.product_id], MovementType.return_, ci.quantity,
                           user_id=ctx.user.id, reason=f"Credit note {note.number}: {data.reason}",
                           reference_type="credit_note", reference_id=note.id)

    inv.credited_total += note.total
    _ledger(ctx, inv.customer_id, LedgerEntryType.credit_note, credit=note.total,
            description=f"Credit note {note.number} against {inv.number}", occurred_at=now,
            invoice_id=inv.id, credit_note_id=note.id)
    if excess > ZERO:
        refund = Payment(
            shop_id=ctx.shop_id, invoice_id=inv.id, customer_id=inv.customer_id, credit_note_id=note.id,
            kind=PaymentKind.refund, method=data.refund_method, amount=excess, paid_at=now,
            reference=note.number, created_by=ctx.user.id,
        )
        ctx.db.add(refund)
        ctx.db.flush()
        inv.amount_paid -= excess
        _ledger(ctx, inv.customer_id, LedgerEntryType.refund, debit=excess,
                description=f"Refund ({data.refund_method.value}) for {note.number}", occurred_at=now,
                invoice_id=inv.id, payment_id=refund.id, credit_note_id=note.id)
    if inv.credited_total == inv.grand_total:
        inv.status = InvoiceStatus.cancelled
    _refresh_payment_state(inv)
    ctx.db.flush()
    return note


def _credited_by_item(db: Session, item_ids: list[int]) -> dict[int, dict]:
    rows = db.execute(
        select(
            CreditNoteItem.invoice_item_id,
            func.sum(CreditNoteItem.quantity),
            func.sum(CreditNoteItem.gross_amount),
            func.sum(CreditNoteItem.discount_amount),
            func.sum(CreditNoteItem.taxable_value),
            func.sum(CreditNoteItem.cgst_amount),
            func.sum(CreditNoteItem.sgst_amount),
            func.sum(CreditNoteItem.igst_amount),
        )
        .where(CreditNoteItem.invoice_item_id.in_(item_ids))
        .group_by(CreditNoteItem.invoice_item_id)
    ).all()
    keys = ("quantity", "gross", "discount", "taxable", "cgst", "sgst", "igst")
    return {r[0]: dict(zip(keys, r[1:], strict=True)) for r in rows}


def returned_quantities(db: Session, invoice: Invoice) -> dict[int, int]:
    return {k: int(v["quantity"]) for k, v in _credited_by_item(db, [i.id for i in invoice.items]).items()}


def load_invoice_detail(ctx: Ctx, invoice_id: int) -> tuple[Invoice, list[Payment], list[CreditNote]]:
    inv = _visible_invoice(ctx, invoice_id)
    payments = ctx.db.scalars(
        select(Payment).where(Payment.shop_id == ctx.shop_id, Payment.invoice_id == inv.id).order_by(Payment.id)
    ).all()
    notes = ctx.db.scalars(
        select(CreditNote)
        .options(selectinload(CreditNote.items))
        .where(CreditNote.shop_id == ctx.shop_id, CreditNote.invoice_id == inv.id)
        .order_by(CreditNote.id)
    ).all()
    return inv, list(payments), list(notes)

