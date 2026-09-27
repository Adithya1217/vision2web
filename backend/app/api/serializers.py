import datetime as dt

from app.core.deps import Ctx
from app.core.timeutil import local_today
from app.enums import InvoiceStatus
from app.models import CreditNote, Invoice, Payment
from app.schemas.sales import CreditNoteOut, InvoiceOut, InvoiceSummaryOut, PaymentOut
from app.services import invoicing


def is_overdue(inv: Invoice, today: dt.date) -> bool:
    return (
        inv.status != InvoiceStatus.draft
        and inv.balance_due > 0
        and inv.due_date is not None
        and inv.due_date < today
    )


def invoice_summary(inv: Invoice, today: dt.date) -> InvoiceSummaryOut:
    out = InvoiceSummaryOut.model_validate(inv)
    out.customer_name = inv.customer.name if inv.customer else None
    out.is_overdue = is_overdue(inv, today)
    return out


def credit_note_out(note: CreditNote, invoice_number: str | None) -> CreditNoteOut:
    out = CreditNoteOut.model_validate(note)
    out.invoice_number = invoice_number
    return out


def payment_out(p: Payment, invoice_number: str | None) -> PaymentOut:
    out = PaymentOut.model_validate(p)
    out.invoice_number = invoice_number
    return out


def invoice_detail(ctx: Ctx, invoice_id: int) -> InvoiceOut:
    inv, payments, notes = invoicing.load_invoice_detail(ctx, invoice_id)
    returned = invoicing.returned_quantities(ctx.db, inv)
    out = InvoiceOut.model_validate(inv)
    out.customer_name = inv.customer.name if inv.customer else None
    out.is_overdue = is_overdue(inv, local_today(ctx.shop.timezone))
    for item in out.items:
        item.returned_quantity = returned.get(item.id, 0)
    out.payments = [payment_out(p, inv.number) for p in payments]
    out.credit_notes = [credit_note_out(n, inv.number) for n in notes]
    return out
