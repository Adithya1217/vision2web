"""Reporting queries.

Rules:
* every report takes an explicit, inclusive local date range and converts it to UTC using the shop timezone;
* trend series include zero-activity buckets;
* sales = posted invoices (including ones later cancelled by credit note) by posting time; returns are credit
  notes by issue time, so a period's net sales = gross sales - returns issued in that period;
* GST and profit come only from persisted invoice/credit-note line snapshots; nothing is estimated.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from decimal import Decimal
from typing import Literal

from sqlalchemy import Date, case, cast, distinct, func, select

from app.core.deps import Ctx
from app.core.errors import ValidationFailed
from app.core.money import ZERO, q
from app.core.timeutil import day_bounds_utc, local_today
from app.enums import InvoiceStatus, PaymentKind, POStatus
from app.models import (
    CreditNote,
    CreditNoteItem,
    Customer,
    Invoice,
    InvoiceItem,
    LedgerEntry,
    Payment,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseReceipt,
    PurchaseReceiptItem,
    StockMovement,
    Supplier,
    User,
)
from app.schemas.catalog import stock_status

SALE_STATUSES = (InvoiceStatus.posted, InvoiceStatus.cancelled)
Period = Literal["day", "week", "month"]
TopMetric = Literal["revenue", "quantity", "invoice_count"]
MAX_RANGE_DAYS = 1100


class Range:
    def __init__(self, ctx: Ctx, start: dt.date, end: dt.date):
        if end < start:
            raise ValidationFailed("end_date must be on or after start_date", code="invalid_range")
        if (end - start).days > MAX_RANGE_DAYS:
            raise ValidationFailed(f"date range may span at most {MAX_RANGE_DAYS} days", code="invalid_range")
        self.start, self.end, self.tz = start, end, ctx.shop.timezone
        self.lo, self.hi = day_bounds_utc(start, end, self.tz)

    def within(self, col):
        return (col >= self.lo) & (col < self.hi)

    def bucket(self, col, period: Period):
        local = func.timezone(self.tz, col)
        if period == "day":
            return cast(local, Date)
        return cast(func.date_trunc(period, local), Date)

    def as_dict(self):
        return {"start_date": self.start, "end_date": self.end, "timezone": self.tz}


def _m(v) -> Decimal:
    return q(v or ZERO)


def bucket_start(d: dt.date, period: Period) -> dt.date:
    if period == "week":
        return d - dt.timedelta(days=d.weekday())
    if period == "month":
        return d.replace(day=1)
    return d


def next_bucket(d: dt.date, period: Period) -> dt.date:
    if period == "day":
        return d + dt.timedelta(days=1)
    if period == "week":
        return d + dt.timedelta(days=7)
    return (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)


def buckets(start: dt.date, end: dt.date, period: Period) -> list[dt.date]:
    out, cur = [], bucket_start(start, period)
    while cur <= end:
        out.append(cur)
        cur = next_bucket(cur, period)
    return out


# ====================================================================== sales
def sales_by_period(ctx: Ctx, start: dt.date, end: dt.date, period: Period) -> dict:
    r = Range(ctx, start, end)
    db = ctx.db
    b = r.bucket(Invoice.posted_at, period)
    inv_rows = db.execute(
        select(
            b.label("bucket"),
            func.count(Invoice.id),
            func.sum(Invoice.grand_total),
            func.sum(Invoice.taxable_total),
            func.sum(Invoice.cgst_total + Invoice.sgst_total + Invoice.igst_total),
        )
        .where(Invoice.shop_id == ctx.shop_id, Invoice.status.in_(SALE_STATUSES), r.within(Invoice.posted_at))
        .group_by(b)
    ).all()
    unit_rows = db.execute(
        select(b.label("bucket"), func.sum(InvoiceItem.quantity))
        .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
        .where(Invoice.shop_id == ctx.shop_id, Invoice.status.in_(SALE_STATUSES), r.within(Invoice.posted_at))
        .group_by(b)
    ).all()
    cb = r.bucket(CreditNote.issued_at, period)
    ret_rows = db.execute(
        select(cb.label("bucket"), func.sum(CreditNote.total), func.sum(CreditNote.taxable_total))
        .where(CreditNote.shop_id == ctx.shop_id, r.within(CreditNote.issued_at))
        .group_by(cb)
    ).all()
    inv = {row[0]: row for row in inv_rows}
    units = {row[0]: int(row[1] or 0) for row in unit_rows}
    rets = {row[0]: row for row in ret_rows}
    series = []
    totals: dict = {"invoice_count": 0, "units_sold": 0, "gross_sales": ZERO, "returns": ZERO, "net_sales": ZERO,
                    "taxable_value": ZERO, "tax": ZERO}
    for start_d in buckets(start, end, period):
        i = inv.get(start_d)
        ret = rets.get(start_d)
        gross = _m(i[2] if i else 0)
        returns = _m(ret[1] if ret else 0)
        row = {
            "period_start": start_d,
            "period_end": min(next_bucket(start_d, period) - dt.timedelta(days=1), end),
            "invoice_count": int(i[1]) if i else 0,
            "units_sold": units.get(start_d, 0),
            "gross_sales": gross,
            "returns": returns,
            "net_sales": gross - returns,
            "taxable_value": _m(i[3] if i else 0) - _m(ret[2] if ret else 0),
            "tax": _m(i[4] if i else 0),
        }
        series.append(row)
        for k in ("invoice_count", "units_sold", "gross_sales", "returns", "net_sales", "taxable_value", "tax"):
            totals[k] += row[k]
    return {**r.as_dict(), "period": period, "series": series, "totals": totals}


def _returns_by(ctx: Ctx, r: Range, key_col):
    rows = ctx.db.execute(
        select(key_col, func.sum(CreditNoteItem.quantity), func.sum(CreditNoteItem.line_total))
        .join(CreditNote, CreditNoteItem.credit_note_id == CreditNote.id)
        .join(InvoiceItem, CreditNoteItem.invoice_item_id == InvoiceItem.id)
        .where(CreditNote.shop_id == ctx.shop_id, r.within(CreditNote.issued_at))
        .group_by(key_col)
    ).all()
    return {row[0]: (int(row[1] or 0), _m(row[2])) for row in rows}


def sales_by_product(ctx: Ctx, start: dt.date, end: dt.date) -> dict:
    r = Range(ctx, start, end)
    rows = ctx.db.execute(
        select(
            InvoiceItem.product_id,
            func.max(InvoiceItem.sku),
            func.max(InvoiceItem.product_name),
            func.sum(InvoiceItem.quantity),
            func.sum(InvoiceItem.taxable_value),
            func.sum(InvoiceItem.line_total),
            func.count(distinct(InvoiceItem.invoice_id)),
        )
        .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
        .where(Invoice.shop_id == ctx.shop_id, Invoice.status.in_(SALE_STATUSES), r.within(Invoice.posted_at))
        .group_by(InvoiceItem.product_id)
    ).all()
    returns = _returns_by(ctx, r, CreditNoteItem.product_id)
    out = []
    for pid, sku, name, qty, taxable, total, count in rows:
        rq, ramt = returns.get(pid, (0, ZERO))
        out.append({
            "product_id": pid, "sku": sku, "product_name": name, "units_sold": int(qty), "returned_units": rq,
            "net_units": int(qty) - rq, "invoice_count": int(count), "taxable_value": _m(taxable),
            "gross_sales": _m(total), "returns": ramt, "net_sales": _m(total) - ramt,
        })
    out.sort(key=lambda x: (-x["net_sales"], x["product_name"], x["product_id"]))
    return {**r.as_dict(), "rows": out}


def sales_by_category(ctx: Ctx, start: dt.date, end: dt.date) -> dict:
    r = Range(ctx, start, end)
    key = func.coalesce(InvoiceItem.category_name, "Uncategorized")
    rows = ctx.db.execute(
        select(key, func.sum(InvoiceItem.quantity), func.sum(InvoiceItem.line_total),
               func.count(distinct(InvoiceItem.invoice_id)))
        .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
        .where(Invoice.shop_id == ctx.shop_id, Invoice.status.in_(SALE_STATUSES), r.within(Invoice.posted_at))
        .group_by(key)
    ).all()
    returns = _returns_by(ctx, r, key)
    out = []
    for cat, qty, total, count in rows:
        rq, ramt = returns.get(cat, (0, ZERO))
        out.append({"category": cat, "units_sold": int(qty), "returned_units": rq, "invoice_count": int(count),
                    "gross_sales": _m(total), "returns": ramt, "net_sales": _m(total) - ramt})
    out.sort(key=lambda x: (-x["net_sales"], x["category"]))
    return {**r.as_dict(), "rows": out}


def sales_by_customer(ctx: Ctx, start: dt.date, end: dt.date) -> dict:
    r = Range(ctx, start, end)
    rows = ctx.db.execute(
        select(Invoice.customer_id, func.max(Customer.name), func.count(Invoice.id), func.sum(Invoice.grand_total),
               func.sum(Invoice.credit_amount))
        .outerjoin(Customer, Invoice.customer_id == Customer.id)
        .where(Invoice.shop_id == ctx.shop_id, Invoice.status.in_(SALE_STATUSES), r.within(Invoice.posted_at))
        .group_by(Invoice.customer_id)
    ).all()
    ret_rows = ctx.db.execute(
        select(CreditNote.customer_id, func.sum(CreditNote.total))
        .where(CreditNote.shop_id == ctx.shop_id, r.within(CreditNote.issued_at))
        .group_by(CreditNote.customer_id)
    ).all()
    returns = {k: _m(v) for k, v in ret_rows}
    out = [{
        "customer_id": cid, "customer_name": name or "Walk-in", "invoice_count": int(n), "gross_sales": _m(total),
        "credit_sales": _m(credit), "returns": returns.get(cid, ZERO), "net_sales": _m(total) - returns.get(cid, ZERO),
    } for cid, name, n, total, credit in rows]
    out.sort(key=lambda x: (-x["net_sales"], x["customer_name"], x["customer_id"] or 0))
    return {**r.as_dict(), "rows": out}


def sales_by_payment_method(ctx: Ctx, start: dt.date, end: dt.date) -> dict:
    """Money received per method (receipts minus refunds, by payment time) plus sales deferred to khata."""
    r = Range(ctx, start, end)
    rows = ctx.db.execute(
        select(Payment.method, Payment.kind, func.count(Payment.id), func.sum(Payment.amount))
        .where(Payment.shop_id == ctx.shop_id, r.within(Payment.paid_at))
        .group_by(Payment.method, Payment.kind)
    ).all()
    agg: dict[str, dict] = {}
    for method, kind, n, amount in rows:
        row = agg.setdefault(method.value, {"method": method.value, "receipts": ZERO, "refunds": ZERO,
                                            "transactions": 0})
        row["transactions"] += int(n)
        row["receipts" if kind == PaymentKind.receipt else "refunds"] += _m(amount)
    credit = ctx.db.execute(
        select(func.count(Invoice.id), func.sum(Invoice.credit_amount))
        .where(Invoice.shop_id == ctx.shop_id, Invoice.status.in_(SALE_STATUSES), r.within(Invoice.posted_at),
               Invoice.credit_amount > 0)
    ).one()
    if credit[0]:
        agg["credit"] = {"method": "credit", "receipts": _m(credit[1]), "refunds": ZERO,
                         "transactions": int(credit[0])}
    out = [{**v, "net": v["receipts"] - v["refunds"]} for v in agg.values()]
    out.sort(key=lambda x: (-x["net"], x["method"]))
    return {**r.as_dict(), "rows": out, "note": "'credit' is the amount sold on khata, not money received"}


def sales_by_staff(ctx: Ctx, start: dt.date, end: dt.date) -> dict:
    r = Range(ctx, start, end)
    rows = ctx.db.execute(
        select(Invoice.posted_by, func.max(User.full_name), func.count(Invoice.id), func.sum(Invoice.grand_total))
        .outerjoin(User, Invoice.posted_by == User.id)
        .where(Invoice.shop_id == ctx.shop_id, Invoice.status.in_(SALE_STATUSES), r.within(Invoice.posted_at))
        .group_by(Invoice.posted_by)
    ).all()
    out = [{"user_id": uid, "name": name or "Unknown", "invoice_count": int(n), "gross_sales": _m(total)}
           for uid, name, n, total in rows]
    out.sort(key=lambda x: (-x["gross_sales"], x["name"], x["user_id"] or 0))
    return {**r.as_dict(), "rows": out}


def top_products(ctx: Ctx, start: dt.date, end: dt.date, metric: TopMetric, limit: int = 10) -> dict:
    """Rank products by net revenue, net units, or number of invoices.

    Ties share a rank (competition ranking: 1, 1, 3) and are ordered deterministically by the other metrics,
    then product name, then product id."""
    rows = sales_by_product(ctx, start, end)["rows"]
    key_of = {"revenue": "net_sales", "quantity": "net_units", "invoice_count": "invoice_count"}
    primary = key_of[metric]
    others = [v for k, v in key_of.items() if k != metric]
    rows.sort(key=lambda x: (-x[primary], -x[others[0]], -x[others[1]], x["product_name"].lower(), x["product_id"]))
    ranked, prev, rank = [], None, 0
    for idx, row in enumerate(rows, start=1):
        if row[primary] != prev:
            rank, prev = idx, row[primary]
        ranked.append({"rank": rank, "metric_value": row[primary], **row})
    return {"start_date": start, "end_date": end, "timezone": ctx.shop.timezone, "metric": metric,
            "rows": ranked[:limit]}


# ====================================================================== inventory
def inventory_valuation(ctx: Ctx) -> dict:
    products = ctx.db.scalars(
        select(Product).where(Product.shop_id == ctx.shop_id, Product.is_active.is_(True)).order_by(Product.name)
    ).all()
    rows, at_cost, at_price, missing = [], ZERO, ZERO, 0
    for p in products:
        cost_value = q(p.cost_price * p.quantity) if p.cost_price is not None else None
        price_value = q(p.sale_price * p.quantity)
        if cost_value is None and p.quantity > 0:
            missing += 1
        at_cost += cost_value or ZERO
        at_price += price_value
        rows.append({"product_id": p.id, "sku": p.sku, "name": p.name, "quantity": p.quantity,
                     "cost_price": p.cost_price, "sale_price": p.sale_price, "value_at_cost": cost_value,
                     "value_at_sale_price": price_value})
    return {"as_of": dt.datetime.now(dt.UTC), "rows": rows, "total_value_at_cost": at_cost,
            "total_value_at_sale_price": at_price, "products_missing_cost": missing,
            "note": "Products without a cost price are excluded from value_at_cost (no estimates are used)."}


def _incoming_by_product(ctx: Ctx) -> dict[int, int]:
    rows = ctx.db.execute(
        select(PurchaseOrderItem.product_id,
               func.sum(PurchaseOrderItem.ordered_quantity - PurchaseOrderItem.received_quantity))
        .join(PurchaseOrder, PurchaseOrderItem.purchase_order_id == PurchaseOrder.id)
        .where(PurchaseOrder.shop_id == ctx.shop_id, PurchaseOrder.status.in_([POStatus.sent, POStatus.partial]))
        .group_by(PurchaseOrderItem.product_id)
    ).all()
    return {pid: int(n) for pid, n in rows}


def stock_alerts(ctx: Ctx, kind: Literal["low", "out"]) -> dict:
    stmt = select(Product).where(Product.shop_id == ctx.shop_id, Product.is_active.is_(True))
    if kind == "out":
        stmt = stmt.where(Product.quantity <= 0)
    else:
        stmt = stmt.where(Product.quantity > 0, Product.quantity <= Product.low_stock_threshold)
    products = ctx.db.scalars(stmt.order_by(Product.quantity, Product.name, Product.id)).all()
    incoming = _incoming_by_product(ctx)
    return {"rows": [{
        "product_id": p.id, "sku": p.sku, "name": p.name, "quantity": p.quantity,
        "low_stock_threshold": p.low_stock_threshold, "reorder_quantity": p.reorder_quantity,
        "incoming_quantity": incoming.get(p.id, 0), "stock_status": stock_status(p.quantity, p.low_stock_threshold),
    } for p in products]}


def stock_movement_summary(ctx: Ctx, start: dt.date, end: dt.date) -> dict:
    r = Range(ctx, start, end)
    by_type = ctx.db.execute(
        select(StockMovement.movement_type, func.count(StockMovement.id), func.sum(StockMovement.quantity_delta))
        .where(StockMovement.shop_id == ctx.shop_id, r.within(StockMovement.created_at))
        .group_by(StockMovement.movement_type)
    ).all()
    inflow = func.sum(case((StockMovement.quantity_delta > 0, StockMovement.quantity_delta), else_=0))
    outflow = func.sum(case((StockMovement.quantity_delta < 0, -StockMovement.quantity_delta), else_=0))
    by_product = ctx.db.execute(
        select(Product.id, Product.sku, Product.name, inflow, outflow, func.sum(StockMovement.quantity_delta))
        .join(Product, StockMovement.product_id == Product.id)
        .where(StockMovement.shop_id == ctx.shop_id, r.within(StockMovement.created_at))
        .group_by(Product.id, Product.sku, Product.name)
        .order_by(Product.name, Product.id)
    ).all()
    return {
        **r.as_dict(),
        "by_type": [{"movement_type": t.value, "movements": int(n), "net_quantity": int(s)} for t, n, s in by_type],
        "by_product": [{"product_id": pid, "sku": sku, "name": name, "quantity_in": int(i), "quantity_out": int(o),
                        "net_change": int(n)} for pid, sku, name, i, o, n in by_product],
    }


# ====================================================================== invoices / payments / khata
def invoice_report(ctx: Ctx, start: dt.date, end: dt.date) -> dict:
    r = Range(ctx, start, end)
    rows = ctx.db.execute(
        select(Invoice.status, Invoice.payment_status, func.count(Invoice.id), func.sum(Invoice.grand_total),
               func.sum(Invoice.balance_due), func.sum(Invoice.credited_total))
        .where(Invoice.shop_id == ctx.shop_id, Invoice.status.in_(SALE_STATUSES), r.within(Invoice.posted_at))
        .group_by(Invoice.status, Invoice.payment_status)
    ).all()
    out = [{"status": s.value, "payment_status": ps.value, "count": int(n), "grand_total": _m(t),
            "balance_due": _m(b), "credited": _m(c)} for s, ps, n, t, b, c in rows]
    out.sort(key=lambda x: (x["status"], x["payment_status"]))
    return {**r.as_dict(), "rows": out,
            "totals": {"count": sum(x["count"] for x in out), "grand_total": sum((x["grand_total"] for x in out), ZERO),
                       "balance_due": sum((x["balance_due"] for x in out), ZERO),
                       "credited": sum((x["credited"] for x in out), ZERO)}}


def payment_report(ctx: Ctx, start: dt.date, end: dt.date) -> dict:
    by_method = sales_by_payment_method(ctx, start, end)
    r = Range(ctx, start, end)
    b = r.bucket(Payment.paid_at, "day")
    signed = case((Payment.kind == PaymentKind.refund, -Payment.amount), else_=Payment.amount)
    daily = dict(ctx.db.execute(
        select(b, func.sum(signed)).where(Payment.shop_id == ctx.shop_id, r.within(Payment.paid_at)).group_by(b)
    ).all())
    series = [{"date": d, "net_received": _m(daily.get(d))} for d in buckets(start, end, "day")]
    rows = [x for x in by_method["rows"] if x["method"] != "credit"]
    return {**r.as_dict(), "by_method": rows, "daily": series,
            "total_received": sum((x["net"] for x in rows), ZERO)}


def khata_report(ctx: Ctx) -> dict:
    today = local_today(ctx.shop.timezone)
    bal_rows = ctx.db.execute(
        select(Customer.id, Customer.name, Customer.phone, func.sum(LedgerEntry.debit - LedgerEntry.credit))
        .join(LedgerEntry, LedgerEntry.customer_id == Customer.id)
        .where(Customer.shop_id == ctx.shop_id)
        .group_by(Customer.id, Customer.name, Customer.phone)
        .having(func.sum(LedgerEntry.debit - LedgerEntry.credit) != 0)
    ).all()
    invoices = ctx.db.scalars(
        select(Invoice).where(Invoice.shop_id == ctx.shop_id, Invoice.status != InvoiceStatus.draft,
                              Invoice.balance_due > 0, Invoice.customer_id.is_not(None))
    ).all()
    aging: dict[int, dict] = defaultdict(lambda: {"current": ZERO, "1_30": ZERO, "31_60": ZERO, "61_90": ZERO,
                                                  "90_plus": ZERO, "oldest_due_date": None})
    for inv in invoices:
        a = aging[inv.customer_id]
        late = (today - inv.due_date).days if inv.due_date else 0
        bucket = ("current" if late <= 0 else "1_30" if late <= 30 else "31_60" if late <= 60
                  else "61_90" if late <= 90 else "90_plus")
        a[bucket] += inv.balance_due
        if late > 0 and (a["oldest_due_date"] is None or inv.due_date < a["oldest_due_date"]):
            a["oldest_due_date"] = inv.due_date
    rows = []
    for cid, name, phone, balance in bal_rows:
        a = aging[cid]
        overdue = a["1_30"] + a["31_60"] + a["61_90"] + a["90_plus"]
        rows.append({"customer_id": cid, "name": name, "phone": phone, "balance": _m(balance),
                     "overdue": overdue, **a})
    rows.sort(key=lambda x: (-x["balance"], x["name"], x["customer_id"]))
    return {"as_of": today, "rows": rows, "total_outstanding": sum((x["balance"] for x in rows), ZERO),
            "total_overdue": sum((x["overdue"] for x in rows), ZERO)}


def purchase_order_report(ctx: Ctx, start: dt.date, end: dt.date) -> dict:
    r = Range(ctx, start, end)
    by_status = ctx.db.execute(
        select(PurchaseOrder.status, func.count(PurchaseOrder.id), func.sum(PurchaseOrder.total))
        .where(PurchaseOrder.shop_id == ctx.shop_id, PurchaseOrder.order_date >= start,
               PurchaseOrder.order_date <= end)
        .group_by(PurchaseOrder.status)
    ).all()
    received = ctx.db.execute(
        select(func.sum(PurchaseReceiptItem.quantity * PurchaseReceiptItem.unit_cost),
               func.sum(PurchaseReceiptItem.quantity))
        .join(PurchaseReceipt, PurchaseReceiptItem.receipt_id == PurchaseReceipt.id)
        .where(PurchaseReceipt.shop_id == ctx.shop_id, r.within(PurchaseReceipt.received_at))
    ).one()
    by_supplier = ctx.db.execute(
        select(Supplier.id, Supplier.name, func.sum(PurchaseReceiptItem.quantity * PurchaseReceiptItem.unit_cost))
        .select_from(PurchaseReceiptItem)
        .join(PurchaseReceipt, PurchaseReceiptItem.receipt_id == PurchaseReceipt.id)
        .join(PurchaseOrder, PurchaseReceipt.purchase_order_id == PurchaseOrder.id)
        .join(Supplier, PurchaseOrder.supplier_id == Supplier.id)
        .where(PurchaseReceipt.shop_id == ctx.shop_id, r.within(PurchaseReceipt.received_at))
        .group_by(Supplier.id, Supplier.name)
    ).all()
    pending = ctx.db.execute(
        select(func.count(distinct(PurchaseOrder.id)),
               func.sum((PurchaseOrderItem.ordered_quantity - PurchaseOrderItem.received_quantity)
                        * PurchaseOrderItem.unit_cost))
        .join(PurchaseOrderItem, PurchaseOrderItem.purchase_order_id == PurchaseOrder.id)
        .where(PurchaseOrder.shop_id == ctx.shop_id, PurchaseOrder.status.in_([POStatus.sent, POStatus.partial]))
    ).one()
    statuses = [{"status": s.value, "count": int(n), "total": _m(t)} for s, n, t in by_status]
    return {
        **r.as_dict(),
        "by_status": sorted(statuses, key=lambda x: x["status"]),
        "ordered_value_excluding_cancelled": sum(
            (x["total"] for x in statuses if x["status"] != POStatus.cancelled.value), ZERO),
        "received_value": _m(received[0]),
        "received_units": int(received[1] or 0),
        "received_by_supplier": [{"supplier_id": sid, "name": n, "received_value": _m(v)}
                                 for sid, n, v in sorted(by_supplier, key=lambda x: (-(x[2] or 0), x[1]))],
        "pending_orders": int(pending[0] or 0),
        "pending_value": _m(pending[1]),
        "note": "Received value is ex-GST (unit cost x received units). Cancelled orders are excluded.",
    }


# ====================================================================== tax & profit (owner)
def gst_report(ctx: Ctx, start: dt.date, end: dt.date) -> dict:
    r = Range(ctx, start, end)
    b2b = case((Customer.gstin.is_not(None), "B2B"), else_="B2C")

    sales = ctx.db.execute(
        select(InvoiceItem.gst_rate, Invoice.supply_type, b2b, func.sum(InvoiceItem.taxable_value),
               func.sum(InvoiceItem.cgst_amount), func.sum(InvoiceItem.sgst_amount), func.sum(InvoiceItem.igst_amount))
        .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
        .outerjoin(Customer, Invoice.customer_id == Customer.id)
        .where(Invoice.shop_id == ctx.shop_id, Invoice.status.in_(SALE_STATUSES), r.within(Invoice.posted_at))
        .group_by(InvoiceItem.gst_rate, Invoice.supply_type, b2b)
    ).all()
    notes = ctx.db.execute(
        select(CreditNoteItem.gst_rate, Invoice.supply_type, b2b, func.sum(CreditNoteItem.taxable_value),
               func.sum(CreditNoteItem.cgst_amount), func.sum(CreditNoteItem.sgst_amount),
               func.sum(CreditNoteItem.igst_amount))
        .join(CreditNote, CreditNoteItem.credit_note_id == CreditNote.id)
        .join(Invoice, CreditNote.invoice_id == Invoice.id)
        .outerjoin(Customer, Invoice.customer_id == Customer.id)
        .where(CreditNote.shop_id == ctx.shop_id, r.within(CreditNote.issued_at))
        .group_by(CreditNoteItem.gst_rate, Invoice.supply_type, b2b)
    ).all()

    def rows(data):
        out = [{"gst_rate": rate, "supply_type": st.value, "category": cat, "taxable_value": _m(t),
                "cgst": _m(c), "sgst": _m(s), "igst": _m(i)} for rate, st, cat, t, c, s, i in data]
        out.sort(key=lambda x: (x["gst_rate"], x["supply_type"], x["category"]))
        return out

    def total(rs):
        keys = ("taxable_value", "cgst", "sgst", "igst")
        t = {k: sum((x[k] for x in rs), ZERO) for k in keys}
        t["total_tax"] = t["cgst"] + t["sgst"] + t["igst"]
        return t

    s_rows, n_rows = rows(sales), rows(notes)
    s_tot, n_tot = total(s_rows), total(n_rows)
    net = {k: s_tot[k] - n_tot[k] for k in s_tot}
    by_rate: dict[Decimal, dict] = {}
    for sign, rs in ((1, s_rows), (-1, n_rows)):
        for x in rs:
            agg = by_rate.setdefault(x["gst_rate"], {"gst_rate": x["gst_rate"], "taxable_value": ZERO, "cgst": ZERO,
                                                     "sgst": ZERO, "igst": ZERO})
            for k in ("taxable_value", "cgst", "sgst", "igst"):
                agg[k] += sign * x[k]
    return {**r.as_dict(), "outward_supplies": s_rows, "credit_notes": n_rows, "outward_totals": s_tot,
            "credit_note_totals": n_tot, "net": net,
            "net_by_rate": sorted(by_rate.values(), key=lambda x: x["gst_rate"]),
            "source": "persisted invoice and credit-note line snapshots"}


def profit_report(ctx: Ctx, start: dt.date, end: dt.date) -> dict:
    """Gross profit on lines whose cost price was captured at sale time. Lines without cost are reported
    separately instead of being estimated."""
    r = Range(ctx, start, end)
    known = InvoiceItem.cost_price.is_not(None)
    sales = ctx.db.execute(
        select(
            func.sum(case((known, InvoiceItem.taxable_value), else_=0)),
            func.sum(case((known, InvoiceItem.cost_price * InvoiceItem.quantity), else_=0)),
            func.sum(case((known, 0), else_=InvoiceItem.taxable_value)),
            func.sum(case((known, 0), else_=1)),
            func.count(InvoiceItem.id),
        )
        .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
        .where(Invoice.shop_id == ctx.shop_id, Invoice.status.in_(SALE_STATUSES), r.within(Invoice.posted_at))
    ).one()
    returns = ctx.db.execute(
        select(
            func.sum(case((known, CreditNoteItem.taxable_value), else_=0)),
            func.sum(case((known, InvoiceItem.cost_price * CreditNoteItem.quantity), else_=0)),
            func.sum(case((known, 0), else_=CreditNoteItem.taxable_value)),
        )
        .join(CreditNote, CreditNoteItem.credit_note_id == CreditNote.id)
        .join(InvoiceItem, CreditNoteItem.invoice_item_id == InvoiceItem.id)
        .where(CreditNote.shop_id == ctx.shop_id, r.within(CreditNote.issued_at))
    ).one()
    revenue = _m(sales[0]) - _m(returns[0])
    cogs = _m(sales[1]) - _m(returns[1])
    return {
        **r.as_dict(),
        "revenue_with_known_cost": revenue,
        "cogs": cogs,
        "gross_profit": revenue - cogs,
        "margin_percent": (q(((revenue - cogs) / revenue) * 100) if revenue else None),
        "revenue_without_cost": _m(sales[2]) - _m(returns[2]),
        "lines_without_cost": int(sales[3] or 0),
        "total_lines": int(sales[4] or 0),
        "note": "Revenue is ex-GST. Lines sold without a cost price are excluded from COGS and profit.",
    }


# ====================================================================== dashboard
def dashboard_summary(ctx: Ctx) -> dict:
    today = local_today(ctx.shop.timezone)
    day = sales_by_period(ctx, today, today, "day")["totals"]
    counts = ctx.db.execute(
        select(
            func.count().filter(Product.quantity <= 0),
            func.count().filter(Product.quantity > 0, Product.quantity <= Product.low_stock_threshold),
            func.count(),
        ).where(Product.shop_id == ctx.shop_id, Product.is_active.is_(True))
    ).one()
    pending = ctx.db.execute(
        select(func.count(PurchaseOrder.id), func.sum(PurchaseOrder.total))
        .where(PurchaseOrder.shop_id == ctx.shop_id, PurchaseOrder.status.in_([POStatus.sent, POStatus.partial]))
    ).one()
    balances = (
        select(func.sum(LedgerEntry.debit - LedgerEntry.credit).label("b"))
        .where(LedgerEntry.shop_id == ctx.shop_id)
        .group_by(LedgerEntry.customer_id)
        .subquery()
    )
    khata = ctx.db.execute(
        select(func.coalesce(func.sum(balances.c.b).filter(balances.c.b > 0), 0), func.count().filter(balances.c.b > 0))
    ).one()
    unpaid = ctx.db.execute(
        select(func.sum(Invoice.balance_due), func.count(Invoice.id),
               func.sum(Invoice.balance_due).filter(Invoice.due_date < today),
               func.count(Invoice.id).filter(Invoice.due_date < today))
        .where(Invoice.shop_id == ctx.shop_id, Invoice.status != InvoiceStatus.draft, Invoice.balance_due > 0)
    ).one()
    return {
        "date": today,
        "timezone": ctx.shop.timezone,
        "today": {"revenue": day["net_sales"], "gross_sales": day["gross_sales"], "returns": day["returns"],
                  "invoice_count": day["invoice_count"], "units_sold": day["units_sold"]},
        "stock": {"out_of_stock": int(counts[0]), "low_stock": int(counts[1]), "active_products": int(counts[2])},
        "purchase_orders": {"pending_count": int(pending[0] or 0), "pending_value": _m(pending[1])},
        "khata": {"outstanding": _m(khata[0]), "customers_with_balance": int(khata[1] or 0)},
        "invoices": {"unpaid_total": _m(unpaid[0]), "unpaid_count": int(unpaid[1] or 0),
                     "overdue_total": _m(unpaid[2]), "overdue_count": int(unpaid[3] or 0)},
    }


TREND_DEFAULTS = {"daily": ("day", 30), "weekly": ("week", 12), "monthly": ("month", 12)}


def dashboard_trend(ctx: Ctx, period: Literal["daily", "weekly", "monthly"], periods: int | None = None) -> dict:
    unit, default_n = TREND_DEFAULTS[period]
    n = periods or default_n
    today = local_today(ctx.shop.timezone)
    start = bucket_start(today, unit)
    for _ in range(n - 1):
        start = bucket_start(start - dt.timedelta(days=1), unit)
    return sales_by_period(ctx, start, today, unit)
