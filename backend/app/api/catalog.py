import datetime as dt

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select

from app.core.deps import Ctx, require
from app.core.errors import Conflict
from app.core.idempotency import Idem, idempotent
from app.core.pagination import Page, PageParams, like, paginate
from app.core.permissions import P
from app.core.timeutil import day_bounds_utc
from app.enums import MovementType
from app.models import Category, Product, StockMovement
from app.schemas.catalog import (
    CategoryIn,
    CategoryOut,
    ProductCreate,
    ProductOut,
    ProductUpdate,
    StockAdjustmentIn,
    StockMovementOut,
    StockStatus,
)
from app.services import inventory
from app.services.common import get_scoped

router = APIRouter()


# ---------------------------------------------------------------- categories
@router.get("/categories", response_model=Page[CategoryOut], tags=["products"])
def list_categories(params: PageParams = Depends(), ctx: Ctx = Depends(require(P.products_read))):
    stmt = select(Category).where(Category.shop_id == ctx.shop_id)
    if params.q:
        stmt = stmt.where(Category.name.ilike(like(params.q)))
    items, total = paginate(ctx.db, stmt, params, {"name": func.lower(Category.name)}, "name", Category.id)
    return Page(items=items, total=total, page=params.page, page_size=params.page_size)


@router.post("/categories", response_model=CategoryOut, status_code=201, tags=["products"])
def create_category(
    data: CategoryIn, ctx: Ctx = Depends(require(P.products_write)), idem: Idem = Depends(idempotent)
):
    exists = ctx.db.scalar(
        select(func.count()).where(Category.shop_id == ctx.shop_id, func.lower(Category.name) == data.name.lower())
    )
    if exists:
        raise Conflict(f"category '{data.name}' already exists", code="category_exists")
    cat = Category(shop_id=ctx.shop_id, name=data.name)
    ctx.db.add(cat)
    ctx.db.flush()
    return idem.commit(CategoryOut.model_validate(cat), 201)


@router.patch("/categories/{category_id}", response_model=CategoryOut, tags=["products"])
def rename_category(
    category_id: int,
    data: CategoryIn,
    ctx: Ctx = Depends(require(P.products_write)),
    idem: Idem = Depends(idempotent),
):
    cat = get_scoped(ctx.db, Category, category_id, ctx.shop_id, lock=True, label="category")
    clash = ctx.db.scalar(
        select(func.count()).where(
            Category.shop_id == ctx.shop_id,
            func.lower(Category.name) == data.name.lower(),
            Category.id != cat.id,
        )
    )
    if clash:
        raise Conflict(f"category '{data.name}' already exists", code="category_exists")
    cat.name = data.name
    ctx.db.flush()
    return idem.commit(CategoryOut.model_validate(cat))


# ---------------------------------------------------------------- products
@router.get("/products", response_model=Page[ProductOut], tags=["products"])
def list_products(
    params: PageParams = Depends(),
    category_id: int | None = None,
    status: str = Query("active", pattern="^(active|archived|all)$"),
    stock_status: StockStatus | None = None,
    ctx: Ctx = Depends(require(P.products_read)),
):
    stmt = select(Product).where(Product.shop_id == ctx.shop_id)
    if params.q:
        term = like(params.q)
        stmt = stmt.where(or_(Product.name.ilike(term), Product.sku.ilike(term)))
    if category_id is not None:
        stmt = stmt.where(Product.category_id == category_id)
    if status != "all":
        stmt = stmt.where(Product.is_active.is_(status == "active"))
    if stock_status == "out":
        stmt = stmt.where(Product.quantity <= 0)
    elif stock_status == "low":
        stmt = stmt.where(Product.quantity > 0, Product.quantity <= Product.low_stock_threshold)
    elif stock_status == "healthy":
        stmt = stmt.where(Product.quantity > Product.low_stock_threshold, Product.quantity > 0)
    items, total = paginate(
        ctx.db,
        stmt,
        params,
        {
            "name": func.lower(Product.name),
            "sku": func.lower(Product.sku),
            "quantity": Product.quantity,
            "sale_price": Product.sale_price,
            "created_at": Product.created_at,
            "updated_at": Product.updated_at,
        },
        "name",
        Product.id,
    )
    return Page(
        items=[ProductOut.model_validate(p) for p in items], total=total, page=params.page, page_size=params.page_size
    )


@router.post("/products", response_model=ProductOut, status_code=201, tags=["products"])
def create_product(
    data: ProductCreate, ctx: Ctx = Depends(require(P.products_write)), idem: Idem = Depends(idempotent)
):
    return idem.commit(ProductOut.model_validate(inventory.create_product(ctx, data)), 201)


@router.get("/products/{product_id}", response_model=ProductOut, tags=["products"])
def get_product(product_id: int, ctx: Ctx = Depends(require(P.products_read))):
    return ProductOut.model_validate(get_scoped(ctx.db, Product, product_id, ctx.shop_id, label="product"))


@router.patch("/products/{product_id}", response_model=ProductOut, tags=["products"])
def update_product(
    product_id: int,
    data: ProductUpdate,
    ctx: Ctx = Depends(require(P.products_write)),
    idem: Idem = Depends(idempotent),
):
    return idem.commit(ProductOut.model_validate(inventory.update_product(ctx, product_id, data)))


@router.post("/products/{product_id}/archive", response_model=ProductOut, tags=["products"])
def archive_product(
    product_id: int, ctx: Ctx = Depends(require(P.products_write)), idem: Idem = Depends(idempotent)
):
    return idem.commit(ProductOut.model_validate(inventory.set_active(ctx, product_id, False)))


@router.post("/products/{product_id}/restore", response_model=ProductOut, tags=["products"])
def restore_product(
    product_id: int, ctx: Ctx = Depends(require(P.products_write)), idem: Idem = Depends(idempotent)
):
    return idem.commit(ProductOut.model_validate(inventory.set_active(ctx, product_id, True)))


# ---------------------------------------------------------------- inventory
@router.get("/inventory/movements", response_model=Page[StockMovementOut], tags=["inventory"])
def list_movements(
    params: PageParams = Depends(),
    product_id: int | None = None,
    movement_type: MovementType | None = None,
    start_date: dt.date | None = None,
    end_date: dt.date | None = None,
    ctx: Ctx = Depends(require(P.inventory_read)),
):
    stmt = select(StockMovement).join(Product).where(StockMovement.shop_id == ctx.shop_id)
    if product_id is not None:
        stmt = stmt.where(StockMovement.product_id == product_id)
    if movement_type is not None:
        stmt = stmt.where(StockMovement.movement_type == movement_type)
    if start_date or end_date:
        lo, hi = day_bounds_utc(start_date or dt.date(1970, 1, 1), end_date or dt.date(9998, 12, 30),
                                ctx.shop.timezone)
        stmt = stmt.where(StockMovement.created_at >= lo, StockMovement.created_at < hi)
    if params.q:
        term = like(params.q)
        stmt = stmt.where(or_(Product.name.ilike(term), Product.sku.ilike(term), StockMovement.reason.ilike(term)))
    items, total = paginate(
        ctx.db,
        stmt,
        params,
        {"created_at": StockMovement.created_at, "quantity_delta": StockMovement.quantity_delta},
        "-created_at",
        StockMovement.id,
    )
    return Page(
        items=[StockMovementOut.model_validate(m) for m in items],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.post("/inventory/adjustments", response_model=StockMovementOut, status_code=201, tags=["inventory"])
def adjust_stock(
    data: StockAdjustmentIn, ctx: Ctx = Depends(require(P.inventory_adjust)), idem: Idem = Depends(idempotent)
):
    """Manual stock change. Requires a reason and an Idempotency-Key; stock can never go below zero."""
    return idem.commit(StockMovementOut.model_validate(inventory.adjust_stock(ctx, data)), 201)
