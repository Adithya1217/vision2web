from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select

from app.core.deps import Ctx, require
from app.core.idempotency import Idem, idempotent
from app.core.pagination import Page, PageParams, like, paginate
from app.core.permissions import P
from app.enums import POStatus
from app.models import PurchaseOrder, Supplier
from app.schemas.purchasing import (
    PurchaseOrderIn,
    PurchaseOrderOut,
    PurchaseOrderSummaryOut,
    ReceiptIn,
    SupplierIn,
    SupplierOut,
    SupplierUpdate,
)
from app.services import purchasing
from app.services.common import get_scoped

router = APIRouter()


def _po_out(po: PurchaseOrder, cls=PurchaseOrderOut):
    out = cls.model_validate(po)
    out.supplier_name = po.supplier.name if po.supplier else None
    return out


# ---------------------------------------------------------------- suppliers
@router.get("/suppliers", response_model=Page[SupplierOut], tags=["suppliers"])
def list_suppliers(
    params: PageParams = Depends(),
    status: str = Query("active", pattern="^(active|inactive|all)$"),
    ctx: Ctx = Depends(require(P.suppliers_read)),
):
    stmt = select(Supplier).where(Supplier.shop_id == ctx.shop_id)
    if status != "all":
        stmt = stmt.where(Supplier.is_active.is_(status == "active"))
    if params.q:
        term = like(params.q)
        stmt = stmt.where(or_(Supplier.name.ilike(term), Supplier.phone.ilike(term), Supplier.gstin.ilike(term)))
    items, total = paginate(ctx.db, stmt, params, {"name": func.lower(Supplier.name),
                                                     "created_at": Supplier.created_at}, "name", Supplier.id)
    return Page(items=items, total=total, page=params.page, page_size=params.page_size)


@router.post("/suppliers", response_model=SupplierOut, status_code=201, tags=["suppliers"])
def create_supplier(
    data: SupplierIn, ctx: Ctx = Depends(require(P.suppliers_write)), idem: Idem = Depends(idempotent)
):
    supplier = Supplier(shop_id=ctx.shop_id, is_active=True, **data.model_dump())
    ctx.db.add(supplier)
    ctx.db.flush()
    return idem.commit(SupplierOut.model_validate(supplier), 201)


@router.get("/suppliers/{supplier_id}", response_model=SupplierOut, tags=["suppliers"])
def get_supplier(supplier_id: int, ctx: Ctx = Depends(require(P.suppliers_read))):
    return get_scoped(ctx.db, Supplier, supplier_id, ctx.shop_id, label="supplier")


@router.patch("/suppliers/{supplier_id}", response_model=SupplierOut, tags=["suppliers"])
def update_supplier(
    supplier_id: int,
    data: SupplierUpdate,
    ctx: Ctx = Depends(require(P.suppliers_write)),
    idem: Idem = Depends(idempotent),
):
    supplier = get_scoped(ctx.db, Supplier, supplier_id, ctx.shop_id, lock=True, label="supplier")
    for key, value in data.model_dump(exclude_unset=True).items():
        if key in {"name", "is_active"} and value is None:
            continue
        setattr(supplier, key, value)
    ctx.db.flush()
    return idem.commit(SupplierOut.model_validate(supplier))


# ---------------------------------------------------------------- purchase orders
@router.get("/purchase-orders", response_model=Page[PurchaseOrderSummaryOut], tags=["purchase orders"])
def list_purchase_orders(
    params: PageParams = Depends(),
    status: POStatus | None = None,
    supplier_id: int | None = None,
    pending: bool | None = Query(None, description="Only sent or partially received orders"),
    ctx: Ctx = Depends(require(P.suppliers_read)),
):
    stmt = select(PurchaseOrder).join(Supplier).where(PurchaseOrder.shop_id == ctx.shop_id)
    if status:
        stmt = stmt.where(PurchaseOrder.status == status)
    if pending:
        stmt = stmt.where(PurchaseOrder.status.in_([POStatus.sent, POStatus.partial]))
    if supplier_id is not None:
        stmt = stmt.where(PurchaseOrder.supplier_id == supplier_id)
    if params.q:
        term = like(params.q)
        stmt = stmt.where(or_(PurchaseOrder.number.ilike(term), Supplier.name.ilike(term)))
    items, total = paginate(
        ctx.db, stmt, params,
        {"created_at": PurchaseOrder.created_at, "order_date": PurchaseOrder.order_date,
         "total": PurchaseOrder.total, "number": PurchaseOrder.number},
        "-created_at", PurchaseOrder.id,
    )
    return Page(items=[_po_out(p, PurchaseOrderSummaryOut) for p in items], total=total, page=params.page,
                page_size=params.page_size)


@router.post("/purchase-orders", response_model=PurchaseOrderOut, status_code=201, tags=["purchase orders"])
def create_purchase_order(
    data: PurchaseOrderIn, ctx: Ctx = Depends(require(P.po_manage)), idem: Idem = Depends(idempotent)
):
    return idem.commit(_po_out(purchasing.create(ctx, data)), 201)


@router.get("/purchase-orders/{po_id}", response_model=PurchaseOrderOut, tags=["purchase orders"])
def get_purchase_order(po_id: int, ctx: Ctx = Depends(require(P.suppliers_read))):
    return _po_out(get_scoped(ctx.db, PurchaseOrder, po_id, ctx.shop_id, label="purchase order"))


@router.put("/purchase-orders/{po_id}", response_model=PurchaseOrderOut, tags=["purchase orders"])
def update_purchase_order(
    po_id: int, data: PurchaseOrderIn, ctx: Ctx = Depends(require(P.po_manage)), idem: Idem = Depends(idempotent)
):
    return idem.commit(_po_out(purchasing.update(ctx, po_id, data)))


@router.post("/purchase-orders/{po_id}/send", response_model=PurchaseOrderOut, tags=["purchase orders"])
def send_purchase_order(po_id: int, ctx: Ctx = Depends(require(P.po_manage)), idem: Idem = Depends(idempotent)):
    return idem.commit(_po_out(purchasing.send(ctx, po_id)))


@router.post("/purchase-orders/{po_id}/cancel", response_model=PurchaseOrderOut, tags=["purchase orders"])
def cancel_purchase_order(po_id: int, ctx: Ctx = Depends(require(P.po_manage)), idem: Idem = Depends(idempotent)):
    return idem.commit(_po_out(purchasing.cancel(ctx, po_id)))


@router.post("/purchase-orders/{po_id}/receipts", response_model=PurchaseOrderOut, status_code=201,
             tags=["purchase orders"])
def receive_purchase_order(
    po_id: int, data: ReceiptIn, ctx: Ctx = Depends(require(P.po_receive)), idem: Idem = Depends(idempotent)
):
    """Receive some or all outstanding units. Creates purchase-receipt stock movements."""
    purchasing.receive(ctx, po_id, data)
    po = get_scoped(ctx.db, PurchaseOrder, po_id, ctx.shop_id, label="purchase order")
    return idem.commit(_po_out(po), 201)
