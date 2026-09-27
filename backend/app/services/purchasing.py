from collections import defaultdict

from sqlalchemy import select

from app.core.deps import Ctx
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.money import ZERO, pct, q
from app.core.timeutil import local_today, utcnow
from app.enums import MovementType, POStatus
from app.models import Product, PurchaseOrder, PurchaseOrderItem, PurchaseReceipt, PurchaseReceiptItem, Supplier
from app.schemas.purchasing import PurchaseOrderIn, ReceiptIn
from app.services.common import get_scoped, next_counter
from app.services.inventory import apply_movement, lock_products


def _build_items(ctx: Ctx, po: PurchaseOrder, data: PurchaseOrderIn) -> None:
    ids = {i.product_id for i in data.items}
    products = {
        p.id: p for p in ctx.db.scalars(select(Product).where(Product.shop_id == ctx.shop_id, Product.id.in_(ids)))
    }
    missing = sorted(ids - products.keys())
    if missing:
        raise NotFound(f"product(s) {missing} not found")
    subtotal = tax_total = ZERO
    items = []
    for line in data.items:
        product = products[line.product_id]
        if not product.is_active:
            raise ValidationFailed(f"product {product.sku} is archived", code="product_archived")
        rate = line.gst_rate if line.gst_rate is not None else product.gst_rate
        line_sub = q(line.unit_cost * line.quantity)
        line_tax = pct(line_sub, rate)
        subtotal += line_sub
        tax_total += line_tax
        items.append(
            PurchaseOrderItem(
                shop_id=ctx.shop_id,
                product_id=product.id,
                product_name=product.name,
                sku=product.sku,
                ordered_quantity=line.quantity,
                received_quantity=0,
                unit_cost=line.unit_cost,
                gst_rate=rate,
                line_subtotal=line_sub,
                line_tax=line_tax,
                line_total=line_sub + line_tax,
            )
        )
    po.items = items
    po.subtotal = subtotal
    po.tax_total = tax_total
    po.total = subtotal + tax_total


def _supplier(ctx: Ctx, supplier_id: int) -> Supplier:
    supplier = get_scoped(ctx.db, Supplier, supplier_id, ctx.shop_id, label="supplier")
    if not supplier.is_active:
        raise ValidationFailed("supplier is inactive")
    return supplier


def create(ctx: Ctx, data: PurchaseOrderIn) -> PurchaseOrder:
    _supplier(ctx, data.supplier_id)
    seq = next_counter(ctx.db, ctx.shop_id, "purchase_order")
    po = PurchaseOrder(
        shop_id=ctx.shop_id,
        number=f"{ctx.shop.po_prefix}{seq:06d}",
        supplier_id=data.supplier_id,
        status=POStatus.draft,
        order_date=local_today(ctx.shop.timezone),
        expected_date=data.expected_date,
        notes=data.notes,
        created_by=ctx.user.id,
    )
    _build_items(ctx, po, data)
    ctx.db.add(po)
    ctx.db.flush()
    return po


def update(ctx: Ctx, po_id: int, data: PurchaseOrderIn) -> PurchaseOrder:
    po = get_scoped(ctx.db, PurchaseOrder, po_id, ctx.shop_id, lock=True, label="purchase order")
    if po.status != POStatus.draft:
        raise Conflict("only draft purchase orders can be edited", code="po_not_draft")
    _supplier(ctx, data.supplier_id)
    po.supplier_id = data.supplier_id
    po.expected_date = data.expected_date
    po.notes = data.notes
    po.items.clear()
    ctx.db.flush()
    _build_items(ctx, po, data)
    ctx.db.flush()
    return po


def send(ctx: Ctx, po_id: int) -> PurchaseOrder:
    po = get_scoped(ctx.db, PurchaseOrder, po_id, ctx.shop_id, lock=True, label="purchase order")
    if po.status != POStatus.draft:
        raise Conflict(f"cannot send a {po.status.value} purchase order", code="invalid_transition")
    po.status = POStatus.sent
    po.sent_at = utcnow()
    ctx.db.flush()
    return po


def cancel(ctx: Ctx, po_id: int) -> PurchaseOrder:
    po = get_scoped(ctx.db, PurchaseOrder, po_id, ctx.shop_id, lock=True, label="purchase order")
    if po.status not in (POStatus.draft, POStatus.sent):
        raise Conflict(
            f"cannot cancel a {po.status.value} purchase order (stock was already received)",
            code="invalid_transition",
        )
    po.status = POStatus.cancelled
    po.cancelled_at = utcnow()
    ctx.db.flush()
    return po


def receive(ctx: Ctx, po_id: int, data: ReceiptIn) -> PurchaseReceipt:
    po = get_scoped(ctx.db, PurchaseOrder, po_id, ctx.shop_id, lock=True, label="purchase order")
    if po.status not in (POStatus.sent, POStatus.partial):
        raise Conflict(f"cannot receive against a {po.status.value} purchase order", code="invalid_transition")
    by_id = {i.id: i for i in po.items}
    qty: dict[int, int] = defaultdict(int)
    for line in data.items:
        if line.purchase_order_item_id not in by_id:
            raise NotFound(f"item {line.purchase_order_item_id} is not on {po.number}")
        qty[line.purchase_order_item_id] += line.quantity
    for item_id, n in qty.items():
        item = by_id[item_id]
        if item.received_quantity + n > item.ordered_quantity:
            raise ValidationFailed(
                f"{item.sku}: only {item.ordered_quantity - item.received_quantity} unit(s) outstanding",
                code="over_receipt",
            )

    products = lock_products(ctx.db, ctx.shop_id, [by_id[i].product_id for i in qty])
    receipt = PurchaseReceipt(shop_id=ctx.shop_id, purchase_order_id=po.id, received_at=utcnow(), note=data.note,
                              created_by=ctx.user.id)
    ctx.db.add(receipt)
    ctx.db.flush()
    for item_id, n in qty.items():
        item = by_id[item_id]
        product = products[item.product_id]
        item.received_quantity += n
        receipt.items.append(
            PurchaseReceiptItem(shop_id=ctx.shop_id, purchase_order_item_id=item.id, product_id=product.id,
                                quantity=n, unit_cost=item.unit_cost)
        )
        apply_movement(ctx.db, product, MovementType.purchase_receipt, n, user_id=ctx.user.id,
                       reason=f"Received against {po.number}", reference_type="purchase_order",
                       reference_id=po.id, unit_cost=item.unit_cost)
        if data.update_cost_price:
            product.cost_price = item.unit_cost
    po.status = (
        POStatus.received if all(i.received_quantity == i.ordered_quantity for i in po.items) else POStatus.partial
    )
    ctx.db.flush()
    return receipt
