from tests.conftest import make_product


def _po(owner, supplier_id, lines):
    return owner.ok(owner.post("/purchase-orders", {"supplier_id": supplier_id, "items": lines}))


def test_partial_then_full_receipt_updates_stock(owner, staff):
    p = make_product(owner, sku="RAW", price="20.00", gst="12", qty=2)
    s = owner.ok(owner.post("/suppliers", {"name": "Acme Wholesale", "state_code": "29"}))
    po = _po(owner, s["id"], [{"product_id": p["id"], "quantity": 10, "unit_cost": "12.50"}])
    assert po["number"] == "PO-000001" and po["status"] == "draft"
    assert (po["subtotal"], po["tax_total"], po["total"]) == ("125.00", "15.00", "140.00")
    line = po["items"][0]["id"]

    # cannot receive a draft
    r = owner.post(f"/purchase-orders/{po['id']}/receipts", {"items": [{"purchase_order_item_id": line,
                                                                         "quantity": 1}]})
    assert r.status_code == 409
    owner.ok(owner.post(f"/purchase-orders/{po['id']}/send"))

    # staff may receive stock (inventory operation)
    after = staff.ok(staff.post(f"/purchase-orders/{po['id']}/receipts", {
        "items": [{"purchase_order_item_id": line, "quantity": 4}]}))
    assert after["status"] == "partial" and after["items"][0]["received_quantity"] == 4
    prod = owner.ok(owner.get(f"/products/{p['id']}"))
    assert prod["quantity"] == 6 and prod["cost_price"] == "12.50"

    r = owner.post(f"/purchase-orders/{po['id']}/receipts", {"items": [{"purchase_order_item_id": line,
                                                                         "quantity": 7}]})
    assert r.status_code == 422 and r.json()["code"] == "over_receipt"
    # partially received orders can't be cancelled
    assert owner.post(f"/purchase-orders/{po['id']}/cancel").status_code == 409

    done = owner.ok(owner.post(f"/purchase-orders/{po['id']}/receipts", {
        "items": [{"purchase_order_item_id": line, "quantity": 6}]}))
    assert done["status"] == "received"
    assert owner.ok(owner.get(f"/products/{p['id']}"))["quantity"] == 12
    moves = owner.ok(owner.get("/inventory/movements", product_id=p["id"], movement_type="purchase_receipt"))
    assert sorted(m["quantity_delta"] for m in moves["items"]) == [4, 6]
    assert all(m["reference_type"] == "purchase_order" for m in moves["items"])


def test_cancelled_po_not_pending(owner):
    p = make_product(owner, sku="C1", price="20.00", gst="0", qty=0)
    s = owner.ok(owner.post("/suppliers", {"name": "Supplier"}))
    keep = _po(owner, s["id"], [{"product_id": p["id"], "quantity": 5, "unit_cost": "10.00"}])
    drop = _po(owner, s["id"], [{"product_id": p["id"], "quantity": 5, "unit_cost": "10.00"}])
    owner.ok(owner.post(f"/purchase-orders/{keep['id']}/send"))
    owner.ok(owner.post(f"/purchase-orders/{drop['id']}/send"))
    owner.ok(owner.post(f"/purchase-orders/{drop['id']}/cancel"))
    pending = owner.ok(owner.get("/purchase-orders", pending="true"))
    assert [x["id"] for x in pending["items"]] == [keep["id"]]
    r = owner.post(f"/purchase-orders/{drop['id']}/receipts", {
        "items": [{"purchase_order_item_id": drop["items"][0]["id"], "quantity": 1}]})
    assert r.status_code == 409


def test_draft_po_editable_then_locked(owner, staff):
    p = make_product(owner, sku="E1", price="20.00", gst="5", qty=0)
    s = owner.ok(owner.post("/suppliers", {"name": "Supplier"}))
    po = _po(owner, s["id"], [{"product_id": p["id"], "quantity": 5, "unit_cost": "10.00"}])
    upd = owner.ok(owner.put(f"/purchase-orders/{po['id']}", {
        "supplier_id": s["id"], "items": [{"product_id": p["id"], "quantity": 8, "unit_cost": "9.00"}]}))
    assert upd["total"] == "75.60"
    owner.ok(owner.post(f"/purchase-orders/{po['id']}/send"))
    assert owner.put(f"/purchase-orders/{po['id']}", {
        "supplier_id": s["id"], "items": [{"product_id": p["id"], "quantity": 1, "unit_cost": "9.00"}]}
    ).status_code == 409
    assert staff.post("/purchase-orders", {"supplier_id": s["id"], "items": [
        {"product_id": p["id"], "quantity": 1, "unit_cost": "1.00"}]}).status_code == 403
