from tests.conftest import make_customer, make_product, sell


def test_partial_return_with_restock_then_full_return(owner):
    p = make_product(owner, sku="RET", price="100.00", gst="18", qty=10)
    c = make_customer(owner, "Returner")
    inv = owner.ok(sell(owner, [(p["id"], 3)], customer_id=c["id"]))
    assert inv["grand_total"] == "354.00"
    item_id = inv["items"][0]["id"]

    cn = owner.ok(owner.post(f"/invoices/{inv['id']}/credit-notes", {
        "reason": "damaged pack", "restock": True, "items": [{"invoice_item_id": item_id, "quantity": 1}]}))
    assert cn["number"] == "CN-000001"
    assert (cn["taxable_total"], cn["cgst_total"], cn["sgst_total"], cn["total"]) == (
        "100.00", "9.00", "9.00", "118.00")
    assert owner.ok(owner.get(f"/products/{p['id']}"))["quantity"] == 8
    after = owner.ok(owner.get(f"/invoices/{inv['id']}"))
    assert after["status"] == "posted" and after["credited_total"] == "118.00" and after["balance_due"] == "236.00"
    assert after["items"][0]["returned_quantity"] == 1

    # remaining units, no restock: invoice becomes cancelled via credit note
    owner.ok(owner.post(f"/invoices/{inv['id']}/credit-notes", {
        "reason": "customer changed mind", "restock": False, "items": [{"invoice_item_id": item_id, "quantity": 2}]}))
    assert owner.ok(owner.get(f"/products/{p['id']}"))["quantity"] == 8
    final = owner.ok(owner.get(f"/invoices/{inv['id']}"))
    assert final["status"] == "cancelled" and final["balance_due"] == "0.00"
    led = owner.ok(owner.get(f"/customers/{c['id']}/ledger"))
    assert led["balance"] == "0.00" and led["reconciled"]
    moves = owner.ok(owner.get("/inventory/movements", product_id=p["id"], movement_type="return"))["items"]
    assert [m["quantity_delta"] for m in moves] == [1]

    # nothing left to credit
    r = owner.post(f"/invoices/{inv['id']}/credit-notes", {
        "reason": "again", "items": [{"invoice_item_id": item_id, "quantity": 1}]})
    assert r.status_code == 409


def test_over_credit_rejected(owner):
    p = make_product(owner, sku="OC", price="10.00", gst="0", qty=10)
    c = make_customer(owner, "Over")
    inv = owner.ok(sell(owner, [(p["id"], 2)], customer_id=c["id"]))
    r = owner.post(f"/invoices/{inv['id']}/credit-notes", {
        "reason": "too many", "items": [{"invoice_item_id": inv["items"][0]["id"], "quantity": 3}]})
    assert r.status_code == 422 and r.json()["code"] == "over_credit"


def test_prorated_amounts_never_drift(owner):
    p = make_product(owner, sku="PR", price="33.33", gst="5", qty=10)
    c = make_customer(owner, "Rounding")
    inv = owner.ok(sell(owner, [(p["id"], 3)], customer_id=c["id"]))
    item = inv["items"][0]
    assert (item["taxable_value"], item["cgst_amount"]) == ("99.99", "2.50")
    body = lambda q: {"reason": "return", "restock": True,  # noqa: E731
                      "items": [{"invoice_item_id": item["id"], "quantity": q}]}
    cn1 = owner.ok(owner.post(f"/invoices/{inv['id']}/credit-notes", body(1)))
    cn2 = owner.ok(owner.post(f"/invoices/{inv['id']}/credit-notes", body(2)))
    assert cn1["cgst_total"] == "0.83" and cn2["cgst_total"] == "1.67"
    assert cn1["taxable_total"] == "33.33" and cn2["taxable_total"] == "66.66"
    from decimal import Decimal
    assert Decimal(cn1["total"]) + Decimal(cn2["total"]) == Decimal(inv["grand_total"])
    assert owner.ok(owner.get(f"/invoices/{inv['id']}"))["status"] == "cancelled"


def test_return_on_paid_invoice_requires_refund(owner):
    p = make_product(owner, sku="PAID", price="100.00", gst="0", qty=10)
    c = make_customer(owner, "Paid Up")
    inv = owner.ok(sell(owner, [(p["id"], 2)], customer_id=c["id"],
                        payments=[{"method": "cash", "amount": "200.00"}]))
    body = {"reason": "defective", "restock": False,
            "items": [{"invoice_item_id": inv["items"][0]["id"], "quantity": 1}]}
    r = owner.post(f"/invoices/{inv['id']}/credit-notes", body)
    assert r.status_code == 422 and r.json()["code"] == "refund_required"
    cn = owner.ok(owner.post(f"/invoices/{inv['id']}/credit-notes", {**body, "refund_method": "cash"}))
    assert cn["refund_amount"] == "100.00" and cn["refund_method"] == "cash"
    after = owner.ok(owner.get(f"/invoices/{inv['id']}"))
    assert after["amount_paid"] == "100.00" and after["balance_due"] == "0.00"
    assert [x["kind"] for x in after["payments"]] == ["receipt", "refund"]
    led = owner.ok(owner.get(f"/customers/{c['id']}/ledger"))
    assert led["balance"] == "0.00" and led["reconciled"]
    assert owner.ok(owner.get(f"/products/{p['id']}"))["quantity"] == 8


def test_partially_paid_return_refunds_only_the_excess(owner):
    p = make_product(owner, sku="PX", price="100.00", gst="0", qty=10)
    c = make_customer(owner, "Partial")
    inv = owner.ok(sell(owner, [(p["id"], 3)], customer_id=c["id"],
                        payments=[{"method": "upi", "amount": "250.00"}]))
    # unpaid 50; crediting 100 leaves 50 excess to refund
    cn = owner.ok(owner.post(f"/invoices/{inv['id']}/credit-notes", {
        "reason": "return", "items": [{"invoice_item_id": inv["items"][0]["id"], "quantity": 1}],
        "refund_method": "upi"}))
    assert cn["refund_amount"] == "50.00"
    after = owner.ok(owner.get(f"/invoices/{inv['id']}"))
    assert after["balance_due"] == "0.00" and after["amount_paid"] == "200.00"


def test_walk_in_return_with_refund(owner):
    p = make_product(owner, sku="WR", price="10.00", gst="0", qty=10)
    inv = owner.ok(sell(owner, [(p["id"], 1)], payments=[{"method": "cash", "amount": "10.00"}]))
    cn = owner.ok(owner.post(f"/invoices/{inv['id']}/credit-notes", {
        "reason": "return", "items": [{"invoice_item_id": inv["items"][0]["id"], "quantity": 1}],
        "refund_method": "cash"}))
    assert cn["refund_amount"] == "10.00"
    assert owner.ok(owner.get(f"/invoices/{inv['id']}"))["status"] == "cancelled"


def test_staff_cannot_issue_credit_notes_and_drafts_cannot_be_credited(owner, staff):
    p = make_product(owner, sku="SC", price="10.00", gst="0", qty=10)
    inv = owner.ok(sell(owner, [(p["id"], 1)], payments=[{"method": "cash", "amount": "10.00"}]))
    body = {"reason": "return", "items": [{"invoice_item_id": inv["items"][0]["id"], "quantity": 1}],
            "refund_method": "cash"}
    assert staff.post(f"/invoices/{inv['id']}/credit-notes", body).status_code == 403
    draft = owner.ok(owner.post("/invoices", {"items": [{"product_id": p["id"], "quantity": 1}]}))
    r = owner.post(f"/invoices/{draft['id']}/credit-notes",
                   {**body, "items": [{"invoice_item_id": draft["items"][0]["id"], "quantity": 1}]})
    assert r.status_code == 409
