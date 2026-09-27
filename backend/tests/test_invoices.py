from decimal import Decimal

from tests.conftest import make_customer, make_product, sell


def _mixed_cart(owner):
    a = make_product(owner, sku="A", price="100.00", gst="18", qty=10)
    b = make_product(owner, sku="B", price="33.33", gst="5", qty=10)
    c = make_product(owner, sku="C", price="250.00", gst="0", qty=10)
    return [
        {"product_id": a["id"], "quantity": 2, "discount_percent": "10"},
        {"product_id": b["id"], "quantity": 3, "discount_amount": "0.99"},
        {"product_id": c["id"], "quantity": 1},
    ]


def test_multi_item_intra_state_cgst_sgst(owner):
    lines = _mixed_cart(owner)
    draft = owner.ok(owner.post("/invoices", {"items": lines}))
    assert draft["status"] == "draft" and draft["number"] is None
    assert draft["supply_type"] == "intra_state"
    a, b, c = draft["items"]
    assert (a["gross_amount"], a["discount_amount"], a["taxable_value"]) == ("200.00", "20.00", "180.00")
    assert (a["cgst_amount"], a["sgst_amount"], a["igst_amount"], a["line_total"]) == ("16.20", "16.20", "0.00",
                                                                                      "212.40")
    assert (b["gross_amount"], b["taxable_value"], b["cgst_amount"], b["line_total"]) == ("99.99", "99.00", "2.48",
                                                                                         "103.96")
    assert c["line_total"] == "250.00"
    assert draft["subtotal"] == "549.99"
    assert draft["discount_total"] == "20.99"
    assert draft["taxable_total"] == "529.00"
    assert draft["cgst_total"] == "18.68" and draft["sgst_total"] == "18.68" and draft["igst_total"] == "0.00"
    assert draft["grand_total"] == "566.36"

    posted = owner.ok(owner.post(f"/invoices/{draft['id']}/post",
                                 {"payments": [{"method": "cash", "amount": "566.36"}]}))
    assert posted["status"] == "posted" and posted["number"] == "INV-000001"
    assert posted["grand_total"] == "566.36" and posted["payment_status"] == "paid"
    assert posted["balance_due"] == "0.00"


def test_inter_state_igst(owner):
    lines = _mixed_cart(owner)
    cust = make_customer(owner, "Mumbai Traders", state_code="27")
    draft = owner.ok(owner.post("/invoices", {"items": lines, "customer_id": cust["id"]}))
    assert draft["supply_type"] == "inter_state" and draft["place_of_supply"] == "27"
    assert [i["igst_amount"] for i in draft["items"]] == ["32.40", "4.95", "0.00"]
    assert all(i["cgst_amount"] == "0.00" and i["sgst_amount"] == "0.00" for i in draft["items"])
    assert draft["igst_total"] == "37.35" and draft["grand_total"] == "566.35"
    # explicit place of supply overrides the customer state
    d2 = owner.ok(owner.post("/invoices", {"items": lines, "customer_id": cust["id"], "place_of_supply": "29"}))
    assert d2["supply_type"] == "intra_state"


def test_posting_reduces_stock_and_creates_movements(owner):
    p = make_product(owner, sku="P", price="10.00", gst="0", qty=10)
    inv = owner.ok(sell(owner, [(p["id"], 3), (p["id"], 2)], payments=[{"method": "upi", "amount": "50.00"}]))
    assert owner.ok(owner.get(f"/products/{p['id']}"))["quantity"] == 5
    moves = owner.ok(owner.get("/inventory/movements", product_id=p["id"], movement_type="sale"))["items"]
    assert sorted(m["quantity_delta"] for m in moves) == [-3, -2]
    assert all(m["reference_type"] == "invoice" and m["reference_id"] == inv["id"] for m in moves)


def test_invoice_numbers_are_sequential_per_shop(owner, other_owner):
    p = make_product(owner, sku="N", price="1.00", gst="0", qty=10)
    q = make_product(other_owner, sku="N", price="1.00", gst="0", qty=10)
    pay = [{"method": "cash", "amount": "1.00"}]
    n1 = owner.ok(sell(owner, [(p["id"], 1)], payments=pay))["number"]
    n2 = owner.ok(sell(owner, [(p["id"], 1)], payments=pay))["number"]
    m1 = other_owner.ok(sell(other_owner, [(q["id"], 1)], payments=pay))["number"]
    assert (n1, n2, m1) == ("INV-000001", "INV-000002", "INV-000001")


def test_insufficient_stock_rolls_back_everything(owner):
    ok = make_product(owner, sku="OK", price="10.00", gst="0", qty=10)
    low = make_product(owner, sku="LOW", price="10.00", gst="0", qty=1)
    draft = owner.ok(owner.post("/invoices", {"items": [
        {"product_id": ok["id"], "quantity": 4}, {"product_id": low["id"], "quantity": 2}]}))
    r = owner.post(f"/invoices/{draft['id']}/post", {"payments": [{"method": "cash", "amount": "60.00"}]})
    assert r.status_code == 409 and r.json()["code"] == "insufficient_stock"
    assert r.json()["extra"]["shortages"][0]["sku"] == "LOW"
    assert owner.ok(owner.get(f"/products/{ok['id']}"))["quantity"] == 10
    assert owner.ok(owner.get(f"/products/{low['id']}"))["quantity"] == 1
    assert owner.ok(owner.get("/inventory/movements", movement_type="sale"))["total"] == 0
    assert owner.ok(owner.get(f"/invoices/{draft['id']}"))["status"] == "draft"
    assert owner.ok(owner.get("/payments"))["total"] == 0


def test_failed_payment_validation_rolls_back_stock_and_number(owner):
    p = make_product(owner, sku="RB", price="10.00", gst="0", qty=5)
    draft = owner.ok(owner.post("/invoices", {"items": [{"product_id": p["id"], "quantity": 2}]}))
    # walk-in customer cannot leave a balance: failure happens *after* stock was deducted inside the txn
    r = owner.post(f"/invoices/{draft['id']}/post", {"payments": [{"method": "cash", "amount": "5.00"}]})
    assert r.status_code == 422 and r.json()["code"] == "credit_requires_customer"
    assert owner.ok(owner.get(f"/products/{p['id']}"))["quantity"] == 5
    assert owner.ok(owner.get("/inventory/movements", movement_type="sale"))["total"] == 0
    # overpayment also fails cleanly
    r = owner.post(f"/invoices/{draft['id']}/post", {"payments": [{"method": "cash", "amount": "25.00"}]})
    assert r.status_code == 422 and r.json()["code"] == "overpayment"
    # the invoice number was not consumed by the failed attempts
    ok = owner.ok(owner.post(f"/invoices/{draft['id']}/post", {"payments": [{"method": "cash", "amount": "20.00"}]}))
    assert ok["number"] == "INV-000001"


def test_posted_invoice_is_immutable(owner):
    p = make_product(owner, sku="IM", price="10.00", gst="0", qty=5)
    inv = owner.ok(sell(owner, [(p["id"], 1)], payments=[{"method": "cash", "amount": "10.00"}]))
    body = {"items": [{"product_id": p["id"], "quantity": 2}]}
    assert owner.put(f"/invoices/{inv['id']}", body).status_code == 409
    assert owner.delete(f"/invoices/{inv['id']}").status_code == 409
    r = owner.post(f"/invoices/{inv['id']}/post", {})
    assert r.status_code == 409 and r.json()["code"] == "invoice_not_draft"
    assert owner.ok(owner.get(f"/products/{p['id']}"))["quantity"] == 4


def test_snapshots_survive_product_changes(owner):
    p = make_product(owner, sku="SNAP", price="10.00", gst="5", qty=5, name="Old Name")
    inv = owner.ok(sell(owner, [(p["id"], 1)], payments=[{"method": "cash", "amount": "10.50"}]))
    owner.ok(owner.patch(f"/products/{p['id']}", {"name": "New Name", "sale_price": "99.00", "gst_rate": "28",
                                                   "sku": "SNAP-2"}))
    item = owner.ok(owner.get(f"/invoices/{inv['id']}"))["items"][0]
    assert (item["product_name"], item["sku"], item["unit_price"], item["gst_rate"]) == (
        "Old Name", "SNAP", "10.00", "5.00")


def test_draft_edit_and_delete(owner):
    p = make_product(owner, sku="D", price="10.00", gst="0", qty=5)
    draft = owner.ok(owner.post("/invoices", {"items": [{"product_id": p["id"], "quantity": 1}]}))
    upd = owner.ok(owner.put(f"/invoices/{draft['id']}", {"items": [{"product_id": p["id"], "quantity": 3}]}))
    assert upd["grand_total"] == "30.00"
    owner.ok(owner.delete(f"/invoices/{draft['id']}"))
    assert owner.get(f"/invoices/{draft['id']}").status_code == 404
    assert owner.ok(owner.get(f"/products/{p['id']}"))["quantity"] == 5


def test_price_override_requires_manager(owner, staff):
    p = make_product(owner, sku="OV", price="10.00", gst="0", qty=5)
    body = {"items": [{"product_id": p["id"], "quantity": 1, "unit_price": "8.00"}]}
    assert staff.post("/invoices", body).status_code == 403
    assert owner.ok(owner.post("/invoices", body))["grand_total"] == "8.00"


def test_discount_cannot_exceed_line(owner):
    p = make_product(owner, sku="DX", price="10.00", gst="0", qty=5)
    r = owner.post("/invoices", {"items": [{"product_id": p["id"], "quantity": 1, "discount_amount": "11.00"}]})
    assert r.status_code == 422
    r = owner.post("/invoices", {"items": [{"product_id": p["id"], "quantity": 1, "discount_amount": "1.00",
                                            "discount_percent": "5"}]})
    assert r.status_code == 422


def test_totals_equal_sum_of_lines(owner):
    p = make_product(owner, sku="T1", price="0.33", gst="18", qty=1000)
    q = make_product(owner, sku="T2", price="7.77", gst="12", qty=1000)
    d = owner.ok(owner.post("/invoices", {"items": [{"product_id": p["id"], "quantity": 7},
                                                    {"product_id": q["id"], "quantity": 13,
                                                     "discount_percent": "3.5"}]}))
    assert Decimal(d["grand_total"]) == sum(Decimal(i["line_total"]) for i in d["items"])
    assert Decimal(d["cgst_total"]) == sum(Decimal(i["cgst_amount"]) for i in d["items"])
