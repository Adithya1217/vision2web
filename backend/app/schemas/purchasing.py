import datetime as dt
from decimal import Decimal

from pydantic import Field

from app.enums import POStatus
from app.schemas.common import ORM, MoneyIn, RateIn, StateCode, Strict


class SupplierIn(Strict):
    name: str = Field(min_length=1, max_length=200)
    contact_person: str | None = Field(None, max_length=200)
    phone: str | None = Field(None, max_length=20)
    email: str | None = Field(None, max_length=254)
    gstin: str | None = Field(None, pattern=r"^[0-9A-Z]{15}$")
    state_code: StateCode | None = None
    address: str | None = None


class SupplierUpdate(Strict):
    name: str | None = Field(None, min_length=1, max_length=200)
    contact_person: str | None = Field(None, max_length=200)
    phone: str | None = Field(None, max_length=20)
    email: str | None = Field(None, max_length=254)
    gstin: str | None = Field(None, pattern=r"^[0-9A-Z]{15}$")
    state_code: StateCode | None = None
    address: str | None = None
    is_active: bool | None = None


class SupplierOut(ORM):
    id: int
    name: str
    contact_person: str | None
    phone: str | None
    email: str | None
    gstin: str | None
    state_code: str | None
    address: str | None
    is_active: bool
    created_at: dt.datetime


class POItemIn(Strict):
    product_id: int
    quantity: int = Field(gt=0, le=1_000_000)
    unit_cost: MoneyIn
    gst_rate: RateIn | None = Field(None, description="Defaults to the product's GST rate")


class PurchaseOrderIn(Strict):
    supplier_id: int
    expected_date: dt.date | None = None
    notes: str | None = Field(None, max_length=2000)
    items: list[POItemIn] = Field(min_length=1, max_length=200)


class POItemOut(ORM):
    id: int
    product_id: int
    product_name: str
    sku: str
    ordered_quantity: int
    received_quantity: int
    unit_cost: Decimal
    gst_rate: Decimal
    line_subtotal: Decimal
    line_tax: Decimal
    line_total: Decimal


class PurchaseOrderSummaryOut(ORM):
    id: int
    number: str
    supplier_id: int
    supplier_name: str | None = None
    status: POStatus
    order_date: dt.date
    expected_date: dt.date | None
    subtotal: Decimal
    tax_total: Decimal
    total: Decimal
    created_at: dt.datetime


class PurchaseOrderOut(PurchaseOrderSummaryOut):
    notes: str | None
    sent_at: dt.datetime | None
    cancelled_at: dt.datetime | None
    items: list[POItemOut]


class ReceiptLineIn(Strict):
    purchase_order_item_id: int
    quantity: int = Field(gt=0)


class ReceiptIn(Strict):
    items: list[ReceiptLineIn] = Field(min_length=1, max_length=200)
    note: str | None = Field(None, max_length=500)
    update_cost_price: bool = Field(True, description="Set each product's cost price to the received unit cost")
