import datetime as dt
from decimal import Decimal

from pydantic import Field, field_validator, model_validator

from app.enums import InvoiceStatus, LedgerEntryType, PaymentKind, PaymentMethod, PaymentStatus, SupplyType
from app.schemas.common import ORM, MoneyIn, PositiveMoneyIn, RateIn, StateCode, Strict


# ---------------------------------------------------------------- customers
class CustomerIn(Strict):
    name: str = Field(min_length=1, max_length=200)
    phone: str | None = Field(None, max_length=20, pattern=r"^\+?[0-9 \-]{6,20}$")
    email: str | None = Field(None, max_length=254)
    gstin: str | None = Field(None, pattern=r"^[0-9A-Z]{15}$")
    state_code: StateCode | None = None
    address: str | None = None
    credit_limit: MoneyIn | None = None


class CustomerUpdate(Strict):
    name: str | None = Field(None, min_length=1, max_length=200)
    phone: str | None = Field(None, max_length=20, pattern=r"^\+?[0-9 \-]{6,20}$")
    email: str | None = Field(None, max_length=254)
    gstin: str | None = Field(None, pattern=r"^[0-9A-Z]{15}$")
    state_code: StateCode | None = None
    address: str | None = None
    credit_limit: MoneyIn | None = None
    is_active: bool | None = None


class CustomerOut(ORM):
    id: int
    name: str
    phone: str | None
    email: str | None
    gstin: str | None
    state_code: str | None
    address: str | None
    credit_limit: Decimal | None
    is_active: bool
    created_at: dt.datetime
    balance: Decimal = Decimal("0.00")
    overdue_amount: Decimal = Decimal("0.00")


# ---------------------------------------------------------------- invoices
class InvoiceItemIn(Strict):
    product_id: int
    quantity: int = Field(gt=0, le=1_000_000)
    unit_price: MoneyIn | None = Field(None, description="Override the product price (owner/manager only)")
    discount_amount: MoneyIn | None = None
    discount_percent: RateIn | None = None

    @model_validator(mode="after")
    def _one_discount(self):
        if self.discount_amount is not None and self.discount_percent is not None:
            raise ValueError("give either discount_amount or discount_percent, not both")
        return self


class InvoiceDraftIn(Strict):
    customer_id: int | None = None
    place_of_supply: StateCode | None = Field(
        None, description="Defaults to the customer's state, then the shop's state"
    )
    due_date: dt.date | None = None
    notes: str | None = Field(None, max_length=2000)
    items: list[InvoiceItemIn] = Field(min_length=1, max_length=200)


class PaymentIn(Strict):
    method: PaymentMethod
    amount: PositiveMoneyIn
    reference: str | None = Field(None, max_length=120)
    paid_at: dt.datetime | None = None

    @field_validator("method")
    @classmethod
    def _no_credit(cls, v: PaymentMethod) -> PaymentMethod:
        if v == PaymentMethod.credit:
            raise ValueError("'credit' is not a receipt; leave the amount unpaid to put it on khata")
        return v


class InvoicePostIn(Strict):
    payments: list[PaymentIn] = Field(default_factory=list, max_length=10)


class InvoiceItemOut(ORM):
    id: int
    line_no: int
    product_id: int
    product_name: str
    sku: str
    hsn_code: str | None
    unit: str
    quantity: int
    unit_price: Decimal
    gst_rate: Decimal
    gross_amount: Decimal
    discount_amount: Decimal
    taxable_value: Decimal
    cgst_amount: Decimal
    sgst_amount: Decimal
    igst_amount: Decimal
    line_total: Decimal
    returned_quantity: int = 0


class PaymentOut(ORM):
    id: int
    invoice_id: int
    invoice_number: str | None = None
    customer_id: int | None
    credit_note_id: int | None
    kind: PaymentKind
    method: PaymentMethod
    amount: Decimal
    reference: str | None
    paid_at: dt.datetime
    created_by: int | None


class CreditNoteItemOut(ORM):
    id: int
    invoice_item_id: int
    product_id: int
    product_name: str
    sku: str
    quantity: int
    unit_price: Decimal
    gst_rate: Decimal
    taxable_value: Decimal
    cgst_amount: Decimal
    sgst_amount: Decimal
    igst_amount: Decimal
    line_total: Decimal


class CreditNoteOut(ORM):
    id: int
    number: str
    invoice_id: int
    invoice_number: str | None = None
    customer_id: int | None
    reason: str
    restock: bool
    note_date: dt.date
    issued_at: dt.datetime
    taxable_total: Decimal
    cgst_total: Decimal
    sgst_total: Decimal
    igst_total: Decimal
    total: Decimal
    refund_amount: Decimal
    refund_method: PaymentMethod | None
    items: list[CreditNoteItemOut] = []


class InvoiceSummaryOut(ORM):
    id: int
    number: str | None
    status: InvoiceStatus
    customer_id: int | None
    customer_name: str | None = None
    invoice_date: dt.date | None
    due_date: dt.date | None
    grand_total: Decimal
    amount_paid: Decimal
    credited_total: Decimal
    balance_due: Decimal
    payment_status: PaymentStatus
    is_overdue: bool = False
    created_at: dt.datetime
    posted_at: dt.datetime | None


class InvoiceOut(InvoiceSummaryOut):
    supply_type: SupplyType
    place_of_supply: str
    notes: str | None
    subtotal: Decimal
    discount_total: Decimal
    taxable_total: Decimal
    cgst_total: Decimal
    sgst_total: Decimal
    igst_total: Decimal
    credit_amount: Decimal
    created_by: int | None
    posted_by: int | None
    items: list[InvoiceItemOut]
    payments: list[PaymentOut] = []
    credit_notes: list[CreditNoteOut] = []


class CreditNoteItemIn(Strict):
    invoice_item_id: int
    quantity: int = Field(gt=0)


class CreditNoteIn(Strict):
    reason: str = Field(min_length=3, max_length=500)
    restock: bool = Field(True, description="Return the credited units to stock")
    items: list[CreditNoteItemIn] = Field(min_length=1, max_length=200)
    refund_method: PaymentMethod | None = Field(
        None, description="Required when the credit exceeds what is still unpaid on the invoice"
    )

    @field_validator("refund_method")
    @classmethod
    def _no_credit(cls, v):
        if v == PaymentMethod.credit:
            raise ValueError("refund_method must be a money method")
        return v


# ---------------------------------------------------------------- khata
class CustomerPaymentIn(PaymentIn):
    """A khata payment, allocated to the customer's oldest open invoices first."""


class LedgerEntryOut(ORM):
    id: int
    entry_type: LedgerEntryType
    description: str
    debit: Decimal
    credit: Decimal
    running_balance: Decimal
    invoice_id: int | None
    payment_id: int | None
    credit_note_id: int | None
    occurred_at: dt.datetime


class LedgerOut(ORM):
    customer: CustomerOut
    entries: list[LedgerEntryOut]
    total_entries: int
    balance: Decimal
    invoice_outstanding: Decimal
    overdue_amount: Decimal
    oldest_overdue_date: dt.date | None
    reconciled: bool
    open_invoices: list[InvoiceSummaryOut]
