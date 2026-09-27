import datetime as dt
from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from app.enums import MovementType
from app.schemas.common import ORM, MoneyIn, RateIn, Strict

SKU_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._/\-]*$"


class CategoryIn(Strict):
    name: str = Field(min_length=1, max_length=120)


class CategoryOut(ORM):
    id: int
    name: str


class ProductCreate(Strict):
    name: str = Field(min_length=1, max_length=200)
    sku: str = Field(min_length=1, max_length=64, pattern=SKU_PATTERN)
    category_id: int | None = None
    hsn_code: str | None = Field(None, max_length=16)
    unit: str = Field("pcs", min_length=1, max_length=16)
    sale_price: MoneyIn
    cost_price: MoneyIn | None = None
    gst_rate: RateIn = Decimal("0")
    opening_quantity: int = Field(0, ge=0)
    low_stock_threshold: int = Field(0, ge=0)
    reorder_quantity: int = Field(0, ge=0)


class ProductUpdate(Strict):
    """Quantity is intentionally absent: stock only changes through movements."""

    name: str | None = Field(None, min_length=1, max_length=200)
    sku: str | None = Field(None, min_length=1, max_length=64, pattern=SKU_PATTERN)
    category_id: int | None = None
    hsn_code: str | None = Field(None, max_length=16)
    unit: str | None = Field(None, min_length=1, max_length=16)
    sale_price: MoneyIn | None = None
    cost_price: MoneyIn | None = None
    gst_rate: RateIn | None = None
    low_stock_threshold: int | None = Field(None, ge=0)
    reorder_quantity: int | None = Field(None, ge=0)


StockStatus = Literal["healthy", "low", "out"]


class ProductOut(ORM):
    id: int
    name: str
    sku: str
    category_id: int | None
    category: CategoryOut | None
    hsn_code: str | None
    unit: str
    sale_price: Decimal
    cost_price: Decimal | None
    gst_rate: Decimal
    quantity: int
    low_stock_threshold: int
    reorder_quantity: int
    is_active: bool
    stock_status: StockStatus
    created_at: dt.datetime
    updated_at: dt.datetime

    @model_validator(mode="before")
    @classmethod
    def _status(cls, obj):
        if hasattr(obj, "quantity") and not isinstance(obj, dict):
            data = {k: getattr(obj, k) for k in cls.model_fields if k != "stock_status"}
            data["stock_status"] = stock_status(obj.quantity, obj.low_stock_threshold)
            return data
        return obj


def stock_status(quantity: int, threshold: int) -> StockStatus:
    if quantity <= 0:
        return "out"
    if quantity <= threshold:
        return "low"
    return "healthy"


AdjustmentType = Literal["manual_increase", "manual_decrease", "damage", "correction"]


class StockAdjustmentIn(Strict):
    product_id: int
    movement_type: AdjustmentType
    quantity: int | None = Field(None, gt=0, description="Units to add/remove (increase, decrease, damage)")
    counted_quantity: int | None = Field(None, ge=0, description="Physical count (correction only)")
    reason: str = Field(min_length=3, max_length=500)

    @model_validator(mode="after")
    def _shape(self):
        if self.movement_type == "correction":
            if self.counted_quantity is None or self.quantity is not None:
                raise ValueError("correction requires counted_quantity (and no quantity)")
        elif self.quantity is None or self.counted_quantity is not None:
            raise ValueError(f"{self.movement_type} requires quantity (and no counted_quantity)")
        return self


class StockMovementOut(ORM):
    id: int
    product_id: int
    product_name: str
    sku: str
    movement_type: MovementType
    quantity_delta: int
    balance_after: int
    reason: str | None
    reference_type: str | None
    reference_id: int | None
    unit_cost: Decimal | None
    created_by: int | None
    created_at: dt.datetime

    @model_validator(mode="before")
    @classmethod
    def _flatten(cls, obj):
        if not isinstance(obj, dict) and hasattr(obj, "product"):
            data = {k: getattr(obj, k) for k in cls.model_fields if k not in {"product_name", "sku"}}
            data["product_name"] = obj.product.name
            data["sku"] = obj.product.sku
            return data
        return obj
