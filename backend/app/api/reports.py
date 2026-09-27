import datetime as dt
from typing import Literal

from fastapi import APIRouter, Depends, Query

from app.core.deps import Ctx, require
from app.core.permissions import P
from app.core.timeutil import local_today
from app.services import reports

router = APIRouter()

Start = Query(..., description="Inclusive start date in the shop's timezone (YYYY-MM-DD)")
End = Query(..., description="Inclusive end date in the shop's timezone (YYYY-MM-DD)")
GroupBy = Literal["day", "week", "month", "category", "product", "customer", "payment_method", "staff"]


# ---------------------------------------------------------------- dashboard
@router.get("/dashboard/summary", tags=["dashboard"])
def dashboard_summary(ctx: Ctx = Depends(require(P.dashboard_view))):
    return reports.dashboard_summary(ctx)


@router.get("/dashboard/trend", tags=["dashboard"])
def dashboard_trend(
    period: Literal["daily", "weekly", "monthly"] = "daily",
    periods: int | None = Query(None, ge=1, le=366),
    ctx: Ctx = Depends(require(P.dashboard_view)),
):
    return reports.dashboard_trend(ctx, period, periods)


@router.get("/dashboard/top-products", tags=["dashboard"])
def dashboard_top_products(
    metric: reports.TopMetric = "revenue",
    days: int = Query(30, ge=1, le=366),
    limit: int = Query(5, ge=1, le=50),
    ctx: Ctx = Depends(require(P.dashboard_view)),
):
    end = local_today(ctx.shop.timezone)
    return reports.top_products(ctx, end - dt.timedelta(days=days - 1), end, metric, limit)


# ---------------------------------------------------------------- sales
@router.get("/reports/sales", tags=["reports"])
def sales_report(
    start_date: dt.date = Start,
    end_date: dt.date = End,
    group_by: GroupBy = "day",
    ctx: Ctx = Depends(require(P.reports_view)),
):
    if group_by in ("day", "week", "month"):
        return reports.sales_by_period(ctx, start_date, end_date, group_by)
    fn = {
        "category": reports.sales_by_category,
        "product": reports.sales_by_product,
        "customer": reports.sales_by_customer,
        "payment_method": reports.sales_by_payment_method,
        "staff": reports.sales_by_staff,
    }[group_by]
    return {"group_by": group_by, **fn(ctx, start_date, end_date)}


@router.get("/reports/top-products", tags=["reports"])
def top_products(
    start_date: dt.date = Start,
    end_date: dt.date = End,
    metric: reports.TopMetric = Query(..., description="revenue | quantity | invoice_count"),
    limit: int = Query(10, ge=1, le=100),
    ctx: Ctx = Depends(require(P.reports_view)),
):
    return reports.top_products(ctx, start_date, end_date, metric, limit)


# ---------------------------------------------------------------- inventory
@router.get("/reports/inventory-valuation", tags=["reports"])
def inventory_valuation(ctx: Ctx = Depends(require(P.reports_view))):
    return reports.inventory_valuation(ctx)


@router.get("/reports/stock-movements", tags=["reports"])
def stock_movements(start_date: dt.date = Start, end_date: dt.date = End,
                    ctx: Ctx = Depends(require(P.reports_view))):
    return reports.stock_movement_summary(ctx, start_date, end_date)


@router.get("/reports/low-stock", tags=["reports"])
def low_stock(ctx: Ctx = Depends(require(P.inventory_read))):
    return reports.stock_alerts(ctx, "low")


@router.get("/reports/out-of-stock", tags=["reports"])
def out_of_stock(ctx: Ctx = Depends(require(P.inventory_read))):
    return reports.stock_alerts(ctx, "out")


# ---------------------------------------------------------------- money
@router.get("/reports/invoices", tags=["reports"])
def invoice_report(start_date: dt.date = Start, end_date: dt.date = End,
                   ctx: Ctx = Depends(require(P.reports_view))):
    return reports.invoice_report(ctx, start_date, end_date)


@router.get("/reports/payments", tags=["reports"])
def payment_report(start_date: dt.date = Start, end_date: dt.date = End,
                   ctx: Ctx = Depends(require(P.reports_view))):
    return reports.payment_report(ctx, start_date, end_date)


@router.get("/reports/khata", tags=["reports"])
def khata_report(ctx: Ctx = Depends(require(P.reports_view))):
    return reports.khata_report(ctx)


@router.get("/reports/purchase-orders", tags=["reports"])
def purchase_order_report(start_date: dt.date = Start, end_date: dt.date = End,
                          ctx: Ctx = Depends(require(P.reports_view))):
    return reports.purchase_order_report(ctx, start_date, end_date)


@router.get("/reports/gst", tags=["reports"])
def gst_report(start_date: dt.date = Start, end_date: dt.date = End, ctx: Ctx = Depends(require(P.tax_reports))):
    return reports.gst_report(ctx, start_date, end_date)


@router.get("/reports/profit", tags=["reports"])
def profit_report(start_date: dt.date = Start, end_date: dt.date = End,
                  ctx: Ctx = Depends(require(P.tax_reports))):
    return reports.profit_report(ctx, start_date, end_date)
