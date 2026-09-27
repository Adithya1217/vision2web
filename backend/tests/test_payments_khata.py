from tests.conftest import make_customer, make_product, sell


def _ledger(api, cid):
    return api.ok(api.get(f"/customers/{cid}/ledger"))


def test_fully_paid_split_payment(owner):
    p = make_product(owner, sku="FP", price="100.00", gst="0", qty=10)
    inv = owner.ok(sell(owner, [(p["id"], 3)], payments=[{"method": "cash", "amount": "100.00"},
                                                         {"method": "upi", "amount": "150.00"},
                                                         {"method": "card", "amount": "50.00"}]))
    assert inv["payment_status"] == "paid" and inv["credit_amount"] == "0.00"
    assert sorted(p["method"] for p in inv["payments"]) == ["card", "cash", "upi"]


def test_partial_payment_creates_khata_and_reconciles(owner):
    p = make_product(owner, sku="PP", price="100.00", gst="0", qty=10)
    c = make_customer(owner, "Suresh", phone="9876543210")
    inv = owner.ok(sell(owner, [(p["id"], 5)], customer_id=c["id"],
                        payments=[{"method": "cash", "amount": "200.00"}]))
    assert inv["payment_status"] == "partial"
    assert inv["credit_amount"] == "300.00" and inv["balance_due"] == "300.00"
    assert inv["due_date"] is not None

    led = _ledger(owner, c["id"])
    assert led["balance"] == "300.00" and led["invoice_outstanding"] == "300.00" and led["reconciled"]
    assert [e["entry_type"] for e in reversed(led["entries"])] == ["invoice", "payment"]
    assert led["entries"][0]["running_balance"] == "300.00"

    # multiple later payments against the same invoice
    owner.ok(owner.post(f"/invoices/{inv['id']}/payments", {"method": "upi", "amount": "100.00"}))
    owner.ok(owner.post(f"/invoices/{inv['id']}/payments", {"method": "bank_transfer", "amount": "150.00",
                                                             "reference": "NEFT123"}))
    r = owner.post(f"/invoices/{inv['id']}/payments", {"method": "cash", "amount": "50.01"})
    assert r.status_code == 422 and r.json()["code"] == "overpayment"
    owner.ok(owner.post(f"/invoices/{inv['id']}/payments", {"method": "cash", "amount": "50.00"}))
    final = owner.ok(owner.get(f"/invoices/{inv['id']}"))
    assert final["payment_status"] == "paid" and final["balance_due"] == "0.00" and len(final["payments"]) == 4
    led = _ledger(owner, c["id"])
    assert led["balance"] == "0.00" and led["reconciled"]


def test_full_credit_invoice(owner):
    p = make_product(owner, sku="FC", price="50.00", gst="0", qty=10)
    c = make_customer(owner, "Credit Only")
    inv = owner.ok(sell(owner, [(p["id"], 2)], customer_id=c["id"]))
    assert inv["payment_status"] == "unpaid" and inv["credit_amount"] == "100.00"
    cust = owner.ok(owner.get(f"/customers/{c['id']}"))
    assert cust["balance"] == "100.00"
    assert owner.ok(owner.get("/customers", has_balance="true"))["total"] == 1


def test_credit_method_is_not_a_receipt(owner):
    p = make_product(owner, sku="CR", price="50.00", gst="0", qty=10)
    c = make_customer(owner, "X")
    r = sell(owner, [(p["id"], 1)], customer_id=c["id"], payments=[{"method": "credit", "amount": "50.00"}])
    assert r.status_code == 422


def test_walk_in_cannot_buy_on_credit(owner):
    p = make_product(owner, sku="WI", price="50.00", gst="0", qty=10)
    r = sell(owner, [(p["id"], 1)])
    assert r.status_code == 422 and r.json()["code"] == "credit_requires_customer"


def test_credit_limit_enforced(owner):
    p = make_product(owner, sku="CL", price="100.00", gst="0", qty=10)
    c = make_customer(owner, "Limited", credit_limit="150.00")
    owner.ok(sell(owner, [(p["id"], 1)], customer_id=c["id"]))
    r = sell(owner, [(p["id"], 1)], customer_id=c["id"])
    assert r.status_code == 409 and r.json()["code"] == "credit_limit_exceeded"


def test_customer_payment_allocates_oldest_first(owner):
    p = make_product(owner, sku="AL", price="100.00", gst="0", qty=10)
    c = make_customer(owner, "Allocator")
    i1 = owner.ok(sell(owner, [(p["id"], 1)], customer_id=c["id"]))
    i2 = owner.ok(sell(owner, [(p["id"], 2)], customer_id=c["id"]))
    pays = owner.ok(owner.post(f"/customers/{c['id']}/payments", {"method": "upi", "amount": "150.00"}))
    assert [(x["invoice_id"], x["amount"]) for x in pays] == [(i1["id"], "100.00"), (i2["id"], "50.00")]
    assert owner.ok(owner.get(f"/invoices/{i1['id']}"))["payment_status"] == "paid"
    assert owner.ok(owner.get(f"/invoices/{i2['id']}"))["balance_due"] == "150.00"
    led = _ledger(owner, c["id"])
    assert led["balance"] == "150.00" and led["reconciled"] and len(led["open_invoices"]) == 1
    r = owner.post(f"/customers/{c['id']}/payments", {"method": "cash", "amount": "150.01"})
    assert r.status_code == 422


def test_overdue_status(owner):
    p = make_product(owner, sku="OD", price="100.00", gst="0", qty=10)
    c = make_customer(owner, "Late Payer")
    draft = owner.ok(owner.post("/invoices", {"customer_id": c["id"], "due_date": "2020-01-01",
                                              "items": [{"product_id": p["id"], "quantity": 1}]}))
    inv = owner.ok(owner.post(f"/invoices/{draft['id']}/post", {}))
    assert inv["is_overdue"] is True
    led = _ledger(owner, c["id"])
    assert led["overdue_amount"] == "100.00" and led["oldest_overdue_date"] == "2020-01-01"
    assert owner.ok(owner.get("/customers", overdue="true"))["items"][0]["overdue_amount"] == "100.00"
    assert owner.ok(owner.get("/invoices", overdue="true"))["total"] == 1


def test_ledger_is_append_only(owner):
    from sqlalchemy import text

    from app.db import engine

    p = make_product(owner, sku="LA", price="100.00", gst="0", qty=10)
    c = make_customer(owner, "Immutable")
    owner.ok(sell(owner, [(p["id"], 1)], customer_id=c["id"]))
    with engine.connect() as conn:
        try:
            conn.execute(text("UPDATE ledger_entries SET debit = 0"))
            raise AssertionError("ledger must be immutable")
        except Exception as exc:  # noqa: BLE001
            assert "immutable" in str(exc)
