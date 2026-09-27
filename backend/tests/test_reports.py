import datetime as dt
from contextlib import contextmanager

import pytest

import app.core.timeutil as timeutil
import app.services.invoicing as invoicing
from tests.conftest import make_customer, make_product, register_shop, sell

UTC = dt.UTC


@pytest.fixture
def clock(monkeypatch):
    """Freeze 'now' for posting/payments and for 'today' calculations."""

    @contextmanager
    def at(ts: dt.datetime):
        monkeypatch.setattr(invoicing, "utcnow", lambda: ts)
        monkeypatch.setattr(timeutil, "utcnow", lambda: ts)
        yield

    return at


def cash(amount):
    return [{"method": "cash", "amount": amount}]


def test_timezone_day_boundaries(owner, clock):
    p = make_product(owner, sku="TZ", price="10.00", gst="0", qty=100)
    # 18:29 UTC = 23:59 IST on Mar 1; 18:31 UTC = 00:01 IST on Mar 2 (both are Mar 1 in UTC)
    with clock(dt.datetime(2026, 3, 1, 18, 29, tzinfo=UTC)):
        late = owner.ok(sell(owner, [(p["id"], 1)], payments=cash("10.00")))
    with clock(dt.datetime(2026, 3, 1, 18, 31, tzinfo=UTC)):
        early = owner.ok(sell(owner, [(p["id"], 2)], payments=cash("20.00")))
    assert late["invoice_date"] == "2026-03-01" and early["invoice_date"] == "2026-03-02"

    rep = owner.ok(owner.get("/reports/sales", start_date="2026-03-01", end_date="2026-03-02"))
    assert [(r["period_start"], r["invoice_count"], r["gross_sales"]) for r in rep["series"]] == [
        ("2026-03-01", 1, "10.00"), ("2026-03-02", 1, "20.00")]
    only_second = owner.ok(owner.get("/reports/sales", start_date="2026-03-02", end_date="2026-03-02"))
    assert only_second["totals"]["gross_sales"] == "20.00" and only_second["totals"]["units_sold"] == 2
    only_first = owner.ok(owner.get("/reports/sales", start_date="2026-03-01", end_date="2026-03-01"))
    assert only_first["totals"]["gross_sales"] == "10.00"


def test_other_timezone_shop(client, clock):
    ny = register_shop(client, name="NY Shop", email="owner@ny.example.com", timezone="America/New_York")
    p = make_product(ny, sku="NY", price="10.00", gst="0", qty=10)
    # 03:00 UTC on Jun 2 is 23:00 on Jun 1 in New York (EDT, UTC-4)
    with clock(dt.datetime(2026, 6, 2, 3, 0, tzinfo=UTC)):
        inv = ny.ok(sell(ny, [(p["id"], 1)], payments=cash("10.00")))
    assert inv["invoice_date"] == "2026-06-01"
    rep = ny.ok(ny.get("/reports/sales", start_date="2026-06-01", end_date="2026-06-02"))
    assert [r["invoice_count"] for r in rep["series"]] == [1, 0]
    assert rep["timezone"] == "America/New_York"


def test_zero_sale_days_and_period_buckets(owner, clock):
    p = make_product(owner, sku="Z", price="10.00", gst="0", qty=100)
    with clock(dt.datetime(2026, 3, 1, 6, 0, tzinfo=UTC)):
        owner.ok(sell(owner, [(p["id"], 1)], payments=cash("10.00")))
    with clock(dt.datetime(2026, 3, 2, 6, 0, tzinfo=UTC)):
        owner.ok(sell(owner, [(p["id"], 3)], payments=cash("30.00")))

    days = owner.ok(owner.get("/reports/sales", start_date="2026-02-27", end_date="2026-03-03"))["series"]
    assert [d["period_start"] for d in days] == ["2026-02-27", "2026-02-28", "2026-03-01", "2026-03-02", "2026-03-03"]
    assert [d["gross_sales"] for d in days] == ["0.00", "0.00", "10.00", "30.00", "0.00"]
    assert [d["invoice_count"] for d in days] == [0, 0, 1, 1, 0]

    weeks = owner.ok(owner.get("/reports/sales", start_date="2026-02-16", end_date="2026-03-08",
                               group_by="week"))["series"]
    # ISO weeks start Monday: Feb 16, Feb 23, Mar 2. Mar 1 (Sunday) belongs to the week of Feb 23.
    assert [(w["period_start"], w["gross_sales"]) for w in weeks] == [
        ("2026-02-16", "0.00"), ("2026-02-23", "10.00"), ("2026-03-02", "30.00")]

    months = owner.ok(owner.get("/reports/sales", start_date="2026-01-15", end_date="2026-03-10",
                                group_by="month"))["series"]
    assert [(m["period_start"], m["period_end"], m["gross_sales"]) for m in months] == [
        ("2026-01-01", "2026-01-31", "0.00"), ("2026-02-01", "2026-02-28", "0.00"),
        ("2026-03-01", "2026-03-10", "40.00")]


def test_returns_reduce_net_sales_on_issue_day(owner, clock):
    p = make_product(owner, sku="RN", price="100.00", gst="0", qty=10)
    c = make_customer(owner, "Net")
    with clock(dt.datetime(2026, 4, 1, 6, 0, tzinfo=UTC)):
        inv = owner.ok(sell(owner, [(p["id"], 2)], customer_id=c["id"]))
    with clock(dt.datetime(2026, 4, 3, 6, 0, tzinfo=UTC)):
        owner.ok(owner.post(f"/invoices/{inv['id']}/credit-notes", {
            "reason": "return", "items": [{"invoice_item_id": inv["items"][0]["id"], "quantity": 1}]}))
    series = owner.ok(owner.get("/reports/sales", start_date="2026-04-01", end_date="2026-04-03"))["series"]
    assert [(s["gross_sales"], s["returns"], s["net_sales"]) for s in series] == [
        ("200.00", "0.00", "200.00"), ("0.00", "0.00", "0.00"), ("0.00", "100.00", "-100.00")]
    by_product = owner.ok(owner.get("/reports/sales", start_date="2026-04-01", end_date="2026-04-03",
                                    group_by="product"))["rows"]
    assert by_product[0]["net_units"] == 1 and by_product[0]["net_sales"] == "100.00"


def test_top_products_metrics_and_ties(owner, clock):
    a = make_product(owner, sku="A", name="Alpha", price="100.00", gst="0", qty=100)
    b = make_product(owner, sku="B", name="Bravo", price="50.00", gst="0", qty=100)
    c = make_product(owner, sku="C", name="Charlie", price="20.00", gst="0", qty=100)
    d = make_product(owner, sku="D", name="Delta", price="5.00", gst="0", qty=100)
    e = make_product(owner, sku="E", name="Echo", price="5.00", gst="0", qty=100)
    with clock(dt.datetime(2026, 5, 10, 6, 0, tzinfo=UTC)):
        owner.ok(sell(owner, [(a["id"], 1)], payments=cash("100.00")))
        owner.ok(sell(owner, [(b["id"], 2)], payments=cash("100.00")))
        for _ in range(3):
            owner.ok(sell(owner, [(c["id"], 1)], payments=cash("20.00")))
        owner.ok(sell(owner, [(e["id"], 1), (d["id"], 1)], payments=cash("10.00")))

    def top(metric):
        rows = owner.ok(owner.get("/reports/top-products", start_date="2026-05-10", end_date="2026-05-10",
                                  metric=metric))["rows"]
        return [(r["sku"], r["rank"], r["metric_value"]) for r in rows]

    assert top("revenue") == [("B", 1, "100.00"), ("A", 1, "100.00"), ("C", 3, "60.00"),
                              ("D", 4, "5.00"), ("E", 4, "5.00")]
    assert top("quantity") == [("C", 1, 3), ("B", 2, 2), ("A", 3, 1), ("D", 3, 1), ("E", 3, 1)]
    assert top("invoice_count") == [("C", 1, 3), ("B", 2, 1), ("A", 2, 1), ("D", 2, 1), ("E", 2, 1)]
    assert owner.get("/reports/top-products", start_date="2026-05-10", end_date="2026-05-10",
                     metric="profit").status_code == 422
    # ranking query is identical on repeat (deterministic)
    assert top("revenue") == top("revenue")


def test_group_by_dimensions(owner, staff, clock):
    snacks = owner.ok(owner.post("/categories", {"name": "Snacks"}))
    p = make_product(owner, sku="G1", price="10.00", gst="0", qty=100, category_id=snacks["id"])
    q = make_product(owner, sku="G2", price="20.00", gst="0", qty=100)
    cust = make_customer(owner, "Grouped")
    with clock(dt.datetime(2026, 7, 1, 6, 0, tzinfo=UTC)):
        owner.ok(sell(owner, [(p["id"], 2)], customer_id=cust["id"], payments=cash("5.00")))
        staff.ok(sell(staff, [(q["id"], 1)], payments=[{"method": "upi", "amount": "20.00"}]))
    rng = {"start_date": "2026-07-01", "end_date": "2026-07-01"}
    cats = owner.ok(owner.get("/reports/sales", group_by="category", **rng))["rows"]
    assert {(c["category"], c["gross_sales"]) for c in cats} == {("Snacks", "20.00"), ("Uncategorized", "20.00")}
    custs = owner.ok(owner.get("/reports/sales", group_by="customer", **rng))["rows"]
    assert {(c["customer_name"], c["credit_sales"]) for c in custs} == {("Grouped", "15.00"), ("Walk-in", "0.00")}
    methods = owner.ok(owner.get("/reports/sales", group_by="payment_method", **rng))["rows"]
    assert {(m["method"], m["net"]) for m in methods} == {("upi", "20.00"), ("credit", "15.00"), ("cash", "5.00")}
    people = owner.ok(owner.get("/reports/sales", group_by="staff", **rng))["rows"]
    assert sorted(x["invoice_count"] for x in people) == [1, 1]


def test_gst_report_uses_snapshots(owner, clock):
    p = make_product(owner, sku="GST", price="100.00", gst="18", qty=100)
    local = make_customer(owner, "Local B2B", gstin="29ABCDE1234F1Z5", state_code="29")
    far = make_customer(owner, "Far", state_code="27")
    with clock(dt.datetime(2026, 8, 5, 6, 0, tzinfo=UTC)):
        inv = owner.ok(sell(owner, [(p["id"], 2)], customer_id=local["id"]))
        owner.ok(sell(owner, [(p["id"], 1)], customer_id=far["id"]))
        owner.ok(owner.post(f"/invoices/{inv['id']}/credit-notes", {
            "reason": "return", "items": [{"invoice_item_id": inv["items"][0]["id"], "quantity": 1}]}))
    # changing the product's rate afterwards must not affect the report
    owner.ok(owner.patch(f"/products/{p['id']}", {"gst_rate": "5"}))
    rep = owner.ok(owner.get("/reports/gst", start_date="2026-08-05", end_date="2026-08-05"))
    assert rep["outward_totals"] == {"taxable_value": "300.00", "cgst": "18.00", "sgst": "18.00", "igst": "18.00",
                                     "total_tax": "54.00"}
    assert rep["credit_note_totals"]["cgst"] == "9.00"
    assert rep["net"] == {"taxable_value": "200.00", "cgst": "9.00", "sgst": "9.00", "igst": "18.00",
                          "total_tax": "36.00"}
    assert {(r["supply_type"], r["category"]) for r in rep["outward_supplies"]} == {
        ("intra_state", "B2B"), ("inter_state", "B2C")}
    assert rep["net_by_rate"][0]["gst_rate"] == "18.00"


def test_profit_report_never_estimates(owner, clock):
    known = make_product(owner, sku="K", price="100.00", gst="18", qty=10, cost_price="60.00")
    unknown = make_product(owner, sku="U", price="50.00", gst="0", qty=10)
    with clock(dt.datetime(2026, 8, 6, 6, 0, tzinfo=UTC)):
        owner.ok(sell(owner, [(known["id"], 2), (unknown["id"], 1)], payments=cash("286.00")))
    rep = owner.ok(owner.get("/reports/profit", start_date="2026-08-06", end_date="2026-08-06"))
    assert rep["revenue_with_known_cost"] == "200.00" and rep["cogs"] == "120.00"
    assert rep["gross_profit"] == "80.00" and rep["margin_percent"] == "40.00"
    assert rep["revenue_without_cost"] == "50.00" and rep["lines_without_cost"] == 1


def test_inventory_khata_po_and_payment_reports(owner, clock):
    p = make_product(owner, sku="INV", price="10.00", gst="0", qty=5, cost_price="6.00", low_stock_threshold=10)
    make_product(owner, sku="NOCOST", price="10.00", gst="0", qty=2, low_stock_threshold=5)
    make_product(owner, sku="EMPTY", price="10.00", gst="0", qty=0)
    val = owner.ok(owner.get("/reports/inventory-valuation"))
    assert val["total_value_at_cost"] == "30.00" and val["total_value_at_sale_price"] == "70.00"
    assert val["products_missing_cost"] == 1
    assert [r["sku"] for r in owner.ok(owner.get("/reports/out-of-stock"))["rows"]] == ["EMPTY"]
    low = owner.ok(owner.get("/reports/low-stock"))["rows"]
    assert {r["sku"] for r in low} == {"INV", "NOCOST"}

    s = owner.ok(owner.post("/suppliers", {"name": "Sup"}))
    po = owner.ok(owner.post("/purchase-orders", {"supplier_id": s["id"], "items": [
        {"product_id": p["id"], "quantity": 10, "unit_cost": "5.00"}]}))
    cancelled = owner.ok(owner.post("/purchase-orders", {"supplier_id": s["id"], "items": [
        {"product_id": p["id"], "quantity": 99, "unit_cost": "5.00"}]}))
    owner.ok(owner.post(f"/purchase-orders/{po['id']}/send"))
    owner.ok(owner.post(f"/purchase-orders/{cancelled['id']}/cancel"))
    owner.ok(owner.post(f"/purchase-orders/{po['id']}/receipts", {
        "items": [{"purchase_order_item_id": po["items"][0]["id"], "quantity": 4}]}))
    today = timeutil.local_today("Asia/Kolkata").isoformat()
    por = owner.ok(owner.get("/reports/purchase-orders", start_date=today, end_date=today))
    assert por["ordered_value_excluding_cancelled"] == "50.00"
    assert por["received_value"] == "20.00" and por["received_units"] == 4
    assert por["pending_orders"] == 1 and por["pending_value"] == "30.00"
    low = {r["sku"]: r for r in owner.ok(owner.get("/reports/low-stock"))["rows"]}
    assert low["INV"]["incoming_quantity"] == 6

    c = make_customer(owner, "Khata")
    with clock(dt.datetime(2026, 1, 1, 6, 0, tzinfo=UTC)):
        owner.ok(sell(owner, [(p["id"], 3)], customer_id=c["id"], payments=cash("10.00")))
    kr = owner.ok(owner.get("/reports/khata"))
    assert kr["total_outstanding"] == "20.00" and kr["rows"][0]["name"] == "Khata"
    pay = owner.ok(owner.get("/reports/payments", start_date="2026-01-01", end_date="2026-01-02"))
    assert pay["total_received"] == "10.00" and [d["net_received"] for d in pay["daily"]] == ["10.00", "0.00"]
    ir = owner.ok(owner.get("/reports/invoices", start_date="2026-01-01", end_date="2026-01-01"))
    assert ir["totals"]["balance_due"] == "20.00"
    sm = owner.ok(owner.get("/reports/stock-movements", start_date=today, end_date=today))
    assert {m["movement_type"] for m in sm["by_type"]} >= {"opening", "purchase_receipt"}


def test_dashboard(owner, clock):
    now = dt.datetime(2026, 9, 10, 8, 0, tzinfo=UTC)
    p = make_product(owner, sku="DB", price="100.00", gst="0", qty=12, low_stock_threshold=10)
    make_product(owner, sku="OUT", price="1.00", gst="0", qty=0)
    c = make_customer(owner, "Dash")
    with clock(now - dt.timedelta(days=1)):
        owner.ok(sell(owner, [(p["id"], 1)], payments=cash("100.00")))
    with clock(now):
        owner.ok(sell(owner, [(p["id"], 2)], customer_id=c["id"], payments=cash("50.00")))
        summary = owner.ok(owner.get("/dashboard/summary"))
        assert summary["date"] == "2026-09-10"
        assert summary["today"] == {"revenue": "200.00", "gross_sales": "200.00", "returns": "0.00",
                                    "invoice_count": 1, "units_sold": 2}
        assert summary["stock"]["low_stock"] == 1 and summary["stock"]["out_of_stock"] == 1
        assert summary["khata"]["outstanding"] == "150.00"
        assert summary["invoices"]["unpaid_total"] == "150.00"
        trend = owner.ok(owner.get("/dashboard/trend", period="daily", periods=7))
        assert len(trend["series"]) == 7 and trend["series"][-1]["period_start"] == "2026-09-10"
        assert [s["gross_sales"] for s in trend["series"][-2:]] == ["100.00", "200.00"]
        weekly = owner.ok(owner.get("/dashboard/trend", period="weekly"))
        assert len(weekly["series"]) == 12
        monthly = owner.ok(owner.get("/dashboard/trend", period="monthly"))
        assert len(monthly["series"]) == 12 and monthly["series"][0]["period_start"] == "2025-10-01"
        top = owner.ok(owner.get("/dashboard/top-products", metric="quantity"))
        assert top["rows"][0]["metric_value"] == 3


def test_report_range_validation(owner):
    assert owner.get("/reports/sales", start_date="2026-02-02", end_date="2026-02-01").status_code == 422
    assert owner.get("/reports/sales", start_date="2026-02-02").status_code == 422
    assert owner.get("/reports/sales", start_date="2020-01-01", end_date="2026-01-01").status_code == 422
