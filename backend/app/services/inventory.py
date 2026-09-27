import logging
from collections.abc import Iterable
from decimal import Decimal

from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import Ctx
from app.core.errors import Conflict, InsufficientStock, NotFound, ValidationFailed
from app.enums import MovementType, Role
from app.models import Category, Product, StockMovement, User
from app.schemas.catalog import ProductCreate, ProductUpdate, StockAdjustmentIn
from app.services.common import get_scoped
from app.services.email import send_email

logger = logging.getLogger(__name__)


def lock_products(db: Session, shop_id: int, product_ids: Iterable[int]) -> dict[int, Product]:
    """Row-lock products in ascending id order (a global order prevents deadlocks between writers)."""
    ids = sorted(set(product_ids))
    if not ids:
        return {}
    rows = db.scalars(
        select(Product)
        .where(Product.shop_id == shop_id, Product.id.in_(ids))
        .order_by(Product.id)
        .with_for_update(of=Product)
    ).all()
    found = {p.id: p for p in rows}
    missing = [i for i in ids if i not in found]
    if missing:
        raise NotFound(f"product(s) {missing} not found")
    return found


def _send_stock_alert(db: Session, product: Product, old_qty: int, new_qty: int) -> None:
    """Email owners and managers when a product crosses into low-stock or out-of-stock status."""
    alert_type: str | None = None
    if old_qty > 0 and new_qty == 0:
        alert_type = "Out of Stock"
    elif old_qty > product.low_stock_threshold and 0 < new_qty <= product.low_stock_threshold:
        alert_type = "Low Stock"
    if alert_type is None:
        return

    recipients = db.scalars(
        select(User.email).where(
            User.shop_id == product.shop_id,
            User.role.in_([Role.owner, Role.manager]),
            User.is_active.is_(True),
        )
    ).all()
    if not recipients:
        return

    subject = f"{alert_type} Alert: {product.name}"
    if alert_type == "Out of Stock":
        body = (
            f"Stock Alert\n\nProduct: {product.name}\nSKU: {product.sku}\nCurrent quantity: {new_qty}\n"
            f"Status: Out of Stock\n\nPlease restock this product."
        )
    else:
        body = (
            f"Stock Alert\n\nProduct: {product.name}\nSKU: {product.sku}\nCurrent quantity: {new_qty}\n"
            f"Low-stock threshold: {product.low_stock_threshold}\nStatus: Low Stock\n\n"
            f"Please consider restocking this product."
        )

    # Queued, not sent: the email goes out only once this transaction commits (see _send_queued_alerts).
    db.info.setdefault(_PENDING_ALERTS, []).extend((r, subject, body) for r in recipients)


_PENDING_ALERTS = "pending_stock_alerts"


# ponytail: sent inline after commit (adds provider latency to that one request); move to a job queue if it matters.
@event.listens_for(Session, "after_commit")
def _send_queued_alerts(session: Session) -> None:
    for recipient, subject, body in session.info.pop(_PENDING_ALERTS, []):
        try:
            send_email(recipient=recipient, subject=subject, body=body)
        except Exception:
            # Email failure must not break the stock operation, which is already committed.
            logger.exception("Failed to send stock alert email to %s: %s", recipient, subject)


@event.listens_for(Session, "after_rollback")
def _drop_queued_alerts(session: Session) -> None:
    # The stock change never happened, so neither did the alert.
    session.info.pop(_PENDING_ALERTS, None)


def apply_movement(
    db: Session,
    product: Product,
    movement_type: MovementType,
    delta: int,
    *,
    user_id: int | None,
    reason: str | None = None,
    reference_type: str | None = None,
    reference_id: int | None = None,
    unit_cost: Decimal | None = None,
) -> StockMovement:
    """Change stock of an already-locked product and append the matching immutable movement."""
    if delta == 0:
        raise ValidationFailed("stock movement must change the quantity")
    old_qty = product.quantity
    new_qty = old_qty + delta
    if new_qty < 0:
        raise InsufficientStock(
            f"insufficient stock for {product.sku}: available {product.quantity}, requested {-delta}",
            extra={"product_id": product.id, "sku": product.sku, "available": product.quantity,
                   "requested": -delta},
        )
    product.quantity = new_qty
    movement = StockMovement(
        shop_id=product.shop_id,
        product_id=product.id,
        movement_type=movement_type,
        quantity_delta=delta,
        balance_after=new_qty,
        reason=reason,
        reference_type=reference_type,
        reference_id=reference_id,
        unit_cost=unit_cost,
        created_by=user_id,
    )
    db.add(movement)
    _send_stock_alert(db, product, old_qty, new_qty)
    return movement


def _check_category(ctx: Ctx, category_id: int | None) -> None:
    if category_id is not None:
        get_scoped(ctx.db, Category, category_id, ctx.shop_id, label="category")


def _sku_taken(ctx: Ctx, sku: str, exclude_id: int | None = None) -> bool:
    stmt = select(func.count()).where(Product.shop_id == ctx.shop_id, func.lower(Product.sku) == sku.lower())
    if exclude_id is not None:
        stmt = stmt.where(Product.id != exclude_id)
    return ctx.db.scalar(stmt) > 0


def _flush_unique(ctx: Ctx, sku: str) -> None:
    try:
        with ctx.db.begin_nested():
            ctx.db.flush()
    except IntegrityError as exc:
        if "uq_products_shop_sku" in str(exc.orig):
            raise Conflict(f"SKU '{sku}' already exists in this shop", code="sku_taken") from exc
        raise


def create_product(ctx: Ctx, data: ProductCreate) -> Product:
    _check_category(ctx, data.category_id)
    if _sku_taken(ctx, data.sku):
        raise Conflict(f"SKU '{data.sku}' already exists in this shop", code="sku_taken")
    fields = data.model_dump(exclude={"opening_quantity"})
    product = Product(shop_id=ctx.shop_id, quantity=0, is_active=True, **fields)
    ctx.db.add(product)
    _flush_unique(ctx, data.sku)
    if data.opening_quantity:
        apply_movement(
            ctx.db,
            product,
            MovementType.opening,
            data.opening_quantity,
            user_id=ctx.user.id,
            reason="Opening balance",
            unit_cost=data.cost_price,
        )
    ctx.db.flush()
    return product


def update_product(ctx: Ctx, product_id: int, data: ProductUpdate) -> Product:
    product = get_scoped(ctx.db, Product, product_id, ctx.shop_id, lock=True, label="product")
    changes = data.model_dump(exclude_unset=True)
    if "category_id" in changes:
        _check_category(ctx, changes["category_id"])
    if changes.get("sku") and _sku_taken(ctx, changes["sku"], exclude_id=product.id):
        raise Conflict(f"SKU '{changes['sku']}' already exists in this shop", code="sku_taken")
    for key in ("name", "sku", "unit", "sale_price", "gst_rate", "low_stock_threshold", "reorder_quantity"):
        if key in changes and changes[key] is None:
            raise ValidationFailed(f"{key} cannot be null")
    for key, value in changes.items():
        setattr(product, key, value)
    _flush_unique(ctx, product.sku)
    return product


def set_active(ctx: Ctx, product_id: int, active: bool) -> Product:
    product = get_scoped(ctx.db, Product, product_id, ctx.shop_id, lock=True, label="product")
    product.is_active = active
    ctx.db.flush()
    return product


def adjust_stock(ctx: Ctx, data: StockAdjustmentIn) -> StockMovement:
    product = lock_products(ctx.db, ctx.shop_id, [data.product_id])[data.product_id]
    if not product.is_active:
        raise ValidationFailed("cannot adjust stock of an archived product", code="product_archived")
    mtype = MovementType(data.movement_type)
    if mtype == MovementType.correction:
        delta = data.counted_quantity - product.quantity  # type: ignore[operator]
        if delta == 0:
            raise ValidationFailed("counted quantity equals current stock; nothing to correct", code="no_change")
    elif mtype == MovementType.manual_increase:
        delta = data.quantity  # type: ignore[assignment]
    else:
        delta = -data.quantity  # type: ignore[operator]
    movement = apply_movement(
        ctx.db, product, mtype, delta, user_id=ctx.user.id, reason=data.reason, reference_type="adjustment"
    )
    ctx.db.flush()
    return movement
