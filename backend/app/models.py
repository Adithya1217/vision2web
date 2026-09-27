"""SQLAlchemy models.

Every operational table carries ``shop_id``. Money is ``NUMERIC(14,2)``; stock quantities are integer units.
Stock movements and khata ledger entries are append-only (enforced by database triggers, see
``app/ddl.py``).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.enums import (
    InvoiceStatus,
    LedgerEntryType,
    MovementType,
    PaymentKind,
    PaymentMethod,
    PaymentStatus,
    POStatus,
    Role,
    SupplyType,
)

Money = Numeric(14, 2)
Rate = Numeric(5, 2)


def enum_col(enum_cls, name: str):
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=False,
        length=32,
        validate_strings=True,
        values_callable=lambda e: [m.value for m in e],
    )


def now_col():
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def shop_fk():
    return mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), nullable=False, index=True)


class Shop(Base):
    __tablename__ = "shops"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    legal_name: Mapped[str | None] = mapped_column(String(200))
    gstin: Mapped[str | None] = mapped_column(String(15))
    state_code: Mapped[str] = mapped_column(String(2))
    address: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(String(20))
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    invoice_prefix: Mapped[str] = mapped_column(String(16), default="INV-")
    credit_note_prefix: Mapped[str] = mapped_column(String(16), default="CN-")
    po_prefix: Mapped[str] = mapped_column(String(16), default="PO-")
    default_credit_days: Mapped[int] = mapped_column(Integer, default=30)
    created_at: Mapped[dt.datetime] = now_col()


class ShopCounter(Base):
    """Per-shop gapless document sequences (invoice, credit note, purchase order numbers)."""

    __tablename__ = "shop_counters"

    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), primary_key=True)
    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, default=0)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = shop_fk()
    email: Mapped[str] = mapped_column(String(254))
    full_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[Role] = mapped_column(enum_col(Role, "role"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = now_col()
    last_login_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    shop: Mapped[Shop] = relationship(lazy="joined")

    __table_args__ = (Index("uq_users_email_lower", func.lower(email), unique=True),)


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = shop_fk()
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[dt.datetime] = now_col()

    __table_args__ = (Index("uq_categories_shop_name", "shop_id", func.lower(name), unique=True),)


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = shop_fk()
    name: Mapped[str] = mapped_column(String(200))
    sku: Mapped[str] = mapped_column(String(64))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"))
    hsn_code: Mapped[str | None] = mapped_column(String(16))
    unit: Mapped[str] = mapped_column(String(16), default="pcs")
    sale_price: Mapped[Decimal] = mapped_column(Money)
    cost_price: Mapped[Decimal | None] = mapped_column(Money)
    gst_rate: Mapped[Decimal] = mapped_column(Rate, default=Decimal("0"))
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    low_stock_threshold: Mapped[int] = mapped_column(Integer, default=0)
    reorder_quantity: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = now_col()
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    category: Mapped[Category | None] = relationship(lazy="joined")

    __table_args__ = (
        Index("uq_products_shop_sku", "shop_id", func.lower(sku), unique=True),
        Index("ix_products_shop_name", "shop_id", func.lower(name)),
        CheckConstraint("quantity >= 0", name="quantity_non_negative"),
        CheckConstraint("sale_price >= 0", name="sale_price_non_negative"),
        CheckConstraint("cost_price IS NULL OR cost_price >= 0", name="cost_price_non_negative"),
        CheckConstraint("gst_rate >= 0 AND gst_rate <= 100", name="gst_rate_range"),
        CheckConstraint("low_stock_threshold >= 0 AND reorder_quantity >= 0", name="thresholds"),
    )


class StockMovement(Base):
    __tablename__ = "stock_movements"

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = shop_fk()
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    movement_type: Mapped[MovementType] = mapped_column(enum_col(MovementType, "movement_type"))
    quantity_delta: Mapped[int] = mapped_column(Integer)
    balance_after: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(Text)
    reference_type: Mapped[str | None] = mapped_column(String(32))
    reference_id: Mapped[int | None] = mapped_column(Integer)
    unit_cost: Mapped[Decimal | None] = mapped_column(Money)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[dt.datetime] = now_col()

    product: Mapped[Product] = relationship(lazy="joined")

    __table_args__ = (
        Index("ix_stock_movements_shop_product_created", "shop_id", "product_id", "created_at"),
        Index("ix_stock_movements_shop_created", "shop_id", "created_at"),
        CheckConstraint("quantity_delta <> 0", name="delta_nonzero"),
        CheckConstraint("balance_after >= 0", name="balance_non_negative"),
    )


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = shop_fk()
    name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(254))
    gstin: Mapped[str | None] = mapped_column(String(15))
    state_code: Mapped[str | None] = mapped_column(String(2))
    address: Mapped[str | None] = mapped_column(Text)
    credit_limit: Mapped[Decimal | None] = mapped_column(Money)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = now_col()

    __table_args__ = (
        Index(
            "uq_customers_shop_phone", "shop_id", "phone", unique=True, postgresql_where=text("phone IS NOT NULL")
        ),
        Index("ix_customers_shop_name", "shop_id", func.lower(name)),
    )


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = shop_fk()
    name: Mapped[str] = mapped_column(String(200))
    contact_person: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(254))
    gstin: Mapped[str | None] = mapped_column(String(15))
    state_code: Mapped[str | None] = mapped_column(String(2))
    address: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = now_col()


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = shop_fk()
    number: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[InvoiceStatus] = mapped_column(enum_col(InvoiceStatus, "invoice_status"))
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id", ondelete="RESTRICT"))
    supply_type: Mapped[SupplyType] = mapped_column(enum_col(SupplyType, "supply_type"))
    place_of_supply: Mapped[str] = mapped_column(String(2))
    invoice_date: Mapped[dt.date | None] = mapped_column(Date)
    due_date: Mapped[dt.date | None] = mapped_column(Date)
    posted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)

    subtotal: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    discount_total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    taxable_total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    cgst_total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    sgst_total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    igst_total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    grand_total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    amount_paid: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    credited_total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    # Portion of the grand total deferred to khata at the moment of posting ("credit" sale).
    credit_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    balance_due: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    payment_status: Mapped[PaymentStatus] = mapped_column(
        enum_col(PaymentStatus, "payment_status"), default=PaymentStatus.unpaid
    )

    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    posted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[dt.datetime] = now_col()
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    items: Mapped[list[InvoiceItem]] = relationship(
        back_populates="invoice", order_by="InvoiceItem.line_no", cascade="all, delete-orphan"
    )
    customer: Mapped[Customer | None] = relationship(lazy="joined")

    __table_args__ = (
        UniqueConstraint("shop_id", "number", name="uq_invoices_shop_number"),
        Index("ix_invoices_shop_posted", "shop_id", "posted_at"),
        Index("ix_invoices_shop_customer", "shop_id", "customer_id"),
        CheckConstraint("balance_due >= 0", name="balance_non_negative"),
        CheckConstraint("amount_paid >= 0", name="paid_non_negative"),
        CheckConstraint("status = 'draft' OR number IS NOT NULL", name="posted_has_number"),
    )


class InvoiceItem(Base):
    """Invoice line. All descriptive and monetary fields are snapshots and never change once posted."""

    __tablename__ = "invoice_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = shop_fk()
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), index=True)
    product_name: Mapped[str] = mapped_column(String(200))
    sku: Mapped[str] = mapped_column(String(64))
    hsn_code: Mapped[str | None] = mapped_column(String(16))
    category_id: Mapped[int | None] = mapped_column(Integer)
    category_name: Mapped[str | None] = mapped_column(String(120))
    unit: Mapped[str] = mapped_column(String(16))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(Money)
    cost_price: Mapped[Decimal | None] = mapped_column(Money)
    gst_rate: Mapped[Decimal] = mapped_column(Rate)
    gross_amount: Mapped[Decimal] = mapped_column(Money)
    discount_amount: Mapped[Decimal] = mapped_column(Money)
    taxable_value: Mapped[Decimal] = mapped_column(Money)
    cgst_amount: Mapped[Decimal] = mapped_column(Money)
    sgst_amount: Mapped[Decimal] = mapped_column(Money)
    igst_amount: Mapped[Decimal] = mapped_column(Money)
    line_total: Mapped[Decimal] = mapped_column(Money)

    invoice: Mapped[Invoice] = relationship(back_populates="items")

    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("discount_amount >= 0 AND discount_amount <= gross_amount", name="discount_range"),
    )


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = shop_fk()
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id", ondelete="RESTRICT"), index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id", ondelete="RESTRICT"))
    credit_note_id: Mapped[int | None] = mapped_column(ForeignKey("credit_notes.id", ondelete="RESTRICT"))
    kind: Mapped[PaymentKind] = mapped_column(enum_col(PaymentKind, "payment_kind"))
    method: Mapped[PaymentMethod] = mapped_column(enum_col(PaymentMethod, "payment_method"))
    amount: Mapped[Decimal] = mapped_column(Money)
    reference: Mapped[str | None] = mapped_column(String(120))
    paid_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[dt.datetime] = now_col()

    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("method <> 'credit'", name="no_credit_receipts"),
        Index("ix_payments_shop_paid_at", "shop_id", "paid_at"),
    )


class CreditNote(Base):
    __tablename__ = "credit_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = shop_fk()
    number: Mapped[str] = mapped_column(String(32))
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id", ondelete="RESTRICT"), index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id", ondelete="RESTRICT"))
    reason: Mapped[str] = mapped_column(Text)
    restock: Mapped[bool] = mapped_column(Boolean)
    note_date: Mapped[dt.date] = mapped_column(Date)
    issued_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    gross_amount: Mapped[Decimal] = mapped_column(Money)
    discount_total: Mapped[Decimal] = mapped_column(Money)
    taxable_total: Mapped[Decimal] = mapped_column(Money)
    cgst_total: Mapped[Decimal] = mapped_column(Money)
    sgst_total: Mapped[Decimal] = mapped_column(Money)
    igst_total: Mapped[Decimal] = mapped_column(Money)
    total: Mapped[Decimal] = mapped_column(Money)
    refund_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    refund_method: Mapped[PaymentMethod | None] = mapped_column(enum_col(PaymentMethod, "payment_method"))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[dt.datetime] = now_col()

    items: Mapped[list[CreditNoteItem]] = relationship(back_populates="credit_note", cascade="all")

    __table_args__ = (
        UniqueConstraint("shop_id", "number", name="uq_credit_notes_shop_number"),
        Index("ix_credit_notes_shop_issued", "shop_id", "issued_at"),
    )


class CreditNoteItem(Base):
    __tablename__ = "credit_note_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = shop_fk()
    credit_note_id: Mapped[int] = mapped_column(ForeignKey("credit_notes.id", ondelete="CASCADE"), index=True)
    invoice_item_id: Mapped[int] = mapped_column(ForeignKey("invoice_items.id", ondelete="RESTRICT"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    product_name: Mapped[str] = mapped_column(String(200))
    sku: Mapped[str] = mapped_column(String(64))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(Money)
    gst_rate: Mapped[Decimal] = mapped_column(Rate)
    gross_amount: Mapped[Decimal] = mapped_column(Money)
    discount_amount: Mapped[Decimal] = mapped_column(Money)
    taxable_value: Mapped[Decimal] = mapped_column(Money)
    cgst_amount: Mapped[Decimal] = mapped_column(Money)
    sgst_amount: Mapped[Decimal] = mapped_column(Money)
    igst_amount: Mapped[Decimal] = mapped_column(Money)
    line_total: Mapped[Decimal] = mapped_column(Money)

    credit_note: Mapped[CreditNote] = relationship(back_populates="items")

    __table_args__ = (CheckConstraint("quantity > 0", name="quantity_positive"),)


class LedgerEntry(Base):
    """Customer khata ledger. Balance = SUM(debit - credit); positive means the customer owes the shop."""

    __tablename__ = "ledger_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = shop_fk()
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="RESTRICT"))
    entry_type: Mapped[LedgerEntryType] = mapped_column(enum_col(LedgerEntryType, "ledger_entry_type"))
    debit: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    credit: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id", ondelete="RESTRICT"))
    payment_id: Mapped[int | None] = mapped_column(ForeignKey("payments.id", ondelete="RESTRICT"))
    credit_note_id: Mapped[int | None] = mapped_column(ForeignKey("credit_notes.id", ondelete="RESTRICT"))
    description: Mapped[str] = mapped_column(String(255))
    occurred_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[dt.datetime] = now_col()

    __table_args__ = (
        Index("ix_ledger_shop_customer_occurred", "shop_id", "customer_id", "occurred_at"),
        CheckConstraint("debit >= 0 AND credit >= 0 AND (debit > 0) <> (credit > 0)", name="one_sided"),
    )


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = shop_fk()
    number: Mapped[str] = mapped_column(String(32))
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id", ondelete="RESTRICT"), index=True)
    status: Mapped[POStatus] = mapped_column(enum_col(POStatus, "po_status"))
    order_date: Mapped[dt.date] = mapped_column(Date)
    expected_date: Mapped[dt.date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    subtotal: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    tax_total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[dt.datetime] = now_col()
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    items: Mapped[list[PurchaseOrderItem]] = relationship(
        back_populates="purchase_order", order_by="PurchaseOrderItem.id", cascade="all, delete-orphan"
    )
    supplier: Mapped[Supplier] = relationship(lazy="joined")

    __table_args__ = (UniqueConstraint("shop_id", "number", name="uq_purchase_orders_shop_number"),)


class PurchaseOrderItem(Base):
    __tablename__ = "purchase_order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = shop_fk()
    purchase_order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    product_name: Mapped[str] = mapped_column(String(200))
    sku: Mapped[str] = mapped_column(String(64))
    ordered_quantity: Mapped[int] = mapped_column(Integer)
    received_quantity: Mapped[int] = mapped_column(Integer, default=0)
    unit_cost: Mapped[Decimal] = mapped_column(Money)
    gst_rate: Mapped[Decimal] = mapped_column(Rate, default=Decimal("0"))
    line_subtotal: Mapped[Decimal] = mapped_column(Money)
    line_tax: Mapped[Decimal] = mapped_column(Money)
    line_total: Mapped[Decimal] = mapped_column(Money)

    purchase_order: Mapped[PurchaseOrder] = relationship(back_populates="items")

    __table_args__ = (
        CheckConstraint("ordered_quantity > 0", name="ordered_positive"),
        CheckConstraint(
            "received_quantity >= 0 AND received_quantity <= ordered_quantity", name="received_range"
        ),
        CheckConstraint("unit_cost >= 0", name="unit_cost_non_negative"),
    )


class PurchaseReceipt(Base):
    __tablename__ = "purchase_receipts"

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = shop_fk()
    purchase_order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="RESTRICT"), index=True
    )
    received_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    items: Mapped[list[PurchaseReceiptItem]] = relationship(cascade="all")


class PurchaseReceiptItem(Base):
    __tablename__ = "purchase_receipt_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = shop_fk()
    receipt_id: Mapped[int] = mapped_column(ForeignKey("purchase_receipts.id", ondelete="CASCADE"), index=True)
    purchase_order_item_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_order_items.id", ondelete="RESTRICT")
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_cost: Mapped[Decimal] = mapped_column(Money)

    __table_args__ = (CheckConstraint("quantity > 0", name="quantity_positive"),)


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = shop_fk()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    status_code: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict | list | None] = mapped_column(JSONB)
    created_at: Mapped[dt.datetime] = now_col()

    __table_args__ = (UniqueConstraint("shop_id", "user_id", "key", name="uq_idempotency_scope"),)
