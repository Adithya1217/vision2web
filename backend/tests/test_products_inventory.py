from sqlalchemy import text

from app.db import engine
from tests.conftest import make_product


def test_create_product_with_opening_stock_creates_movement(owner):
    p = make_product(owner, sku="OPEN-1", qty=25, cost_price="60.00", low_stock_threshold=5)
    assert p["quantity"] == 25 and p["stock_status"] == "healthy"
    moves = owner.ok(owner.get("/inventory/movements", product_id=p["id"]))["items"]
    assert len(moves) == 1
    assert moves[0]["movement_type"] == "opening" and moves[0]["quantity_delta"] == 25
    assert moves[0]["balance_after"] == 25


def test_sku_unique_per_shop_case_insensitive(owner):
    make_product(owner, sku="ABC-1")
    r = owner.post("/products", {"name": "dup", "sku": "abc-1", "sale_price": "1.00"})
    assert r.status_code == 409 and r.json()["code"] == "sku_taken"
    other = make_product(owner, sku="ABC-2")
    r = owner.patch(f"/products/{other['id']}", {"sku": "ABC-1"})
    assert r.status_code == 409


def test_product_validation(owner):
    bad = [
        {"name": "x", "sku": "bad sku", "sale_price": "1.00"},
        {"name": "x", "sku": "X1", "sale_price": "-1.00"},
        {"name": "x", "sku": "X1", "sale_price": "1.001"},
        {"name": "x", "sku": "X1", "sale_price": 1.5},  # floats are rejected for money
        {"name": "x", "sku": "X1", "sale_price": "1.00", "gst_rate": "101"},
        {"name": "", "sku": "X1", "sale_price": "1.00"},
        {"name": "x", "sku": "X1", "sale_price": "1.00", "opening_quantity": -1},
        {"name": "x", "sku": "X1", "sale_price": "1.00", "quantity": 5},  # unknown field
    ]
    for body in bad:
        assert owner.post("/products", body).status_code == 422, body
    # quantity cannot be edited directly
    p = make_product(owner, sku="Q-1")
    assert owner.patch(f"/products/{p['id']}", {"quantity": 999}).status_code == 422


def test_money_serialised_as_decimal_strings(owner):
    p = make_product(owner, sku="M-1", price="19.90", gst="12")
    assert p["sale_price"] == "19.90" and p["gst_rate"] == "12.00"


def test_archive_and_restore(owner):
    p = make_product(owner, sku="ARC-1", qty=3)
    archived = owner.ok(owner.post(f"/products/{p['id']}/archive"))
    assert archived["is_active"] is False
    assert owner.ok(owner.get("/products"))["total"] == 0
    assert owner.ok(owner.get("/products", status="archived"))["total"] == 1
    assert owner.ok(owner.get("/products", status="all"))["total"] == 1
    # archived products cannot be sold or adjusted
    r = owner.post("/invoices", {"items": [{"product_id": p["id"], "quantity": 1}]})
    assert r.status_code == 422 and r.json()["code"] == "product_archived"
    r = owner.post("/inventory/adjustments", {"product_id": p["id"], "movement_type": "manual_increase",
                                               "quantity": 1, "reason": "found more"})
    assert r.status_code == 422
    owner.ok(owner.post(f"/products/{p['id']}/restore"))
    assert owner.ok(owner.get("/products"))["total"] == 1


def test_search_filters_sorting_pagination(owner):
    cat = owner.ok(owner.post("/categories", {"name": "Snacks"}))
    make_product(owner, sku="CHIPS-1", name="Potato Chips", qty=0, category_id=cat["id"])
    make_product(owner, sku="BISC-1", name="Biscuits", qty=3, low_stock_threshold=5, category_id=cat["id"])
    make_product(owner, sku="SOAP-1", name="Soap", qty=50, low_stock_threshold=5)

    assert [p["sku"] for p in owner.ok(owner.get("/products", q="chip"))["items"]] == ["CHIPS-1"]
    assert [p["sku"] for p in owner.ok(owner.get("/products", q="soap-1"))["items"]] == ["SOAP-1"]
    assert [p["sku"] for p in owner.ok(owner.get("/products", stock_status="out"))["items"]] == ["CHIPS-1"]
    assert [p["sku"] for p in owner.ok(owner.get("/products", stock_status="low"))["items"]] == ["BISC-1"]
    assert [p["sku"] for p in owner.ok(owner.get("/products", stock_status="healthy"))["items"]] == ["SOAP-1"]
    assert owner.ok(owner.get("/products", category_id=cat["id"]))["total"] == 2

    page1 = owner.ok(owner.get("/products", sort="-quantity", page_size=2, page=1))
    page2 = owner.ok(owner.get("/products", sort="-quantity", page_size=2, page=2))
    assert page1["total"] == 3
    assert [p["sku"] for p in page1["items"] + page2["items"]] == ["SOAP-1", "BISC-1", "CHIPS-1"]
    assert owner.get("/products", sort="password").status_code == 422


def test_stable_sort_with_ties(owner):
    for i in range(7):
        make_product(owner, sku=f"TIE-{i}", name="Same Name", qty=1)
    seen = []
    for page in (1, 2, 3):
        seen += [p["sku"] for p in owner.ok(owner.get("/products", sort="name", page_size=3, page=page))["items"]]
    assert seen == [f"TIE-{i}" for i in range(7)]


def test_stock_adjustments_and_non_negative_stock(owner):
    p = make_product(owner, sku="ADJ-1", qty=5)
    pid = p["id"]
    owner.ok(owner.post("/inventory/adjustments", {"product_id": pid, "movement_type": "manual_increase",
                                                    "quantity": 3, "reason": "extra delivery"}))
    owner.ok(owner.post("/inventory/adjustments", {"product_id": pid, "movement_type": "damage",
                                                    "quantity": 2, "reason": "water damage"}))
    r = owner.post("/inventory/adjustments", {"product_id": pid, "movement_type": "manual_decrease",
                                               "quantity": 7, "reason": "too many"})
    assert r.status_code == 409 and r.json()["code"] == "insufficient_stock"
    corr = owner.ok(owner.post("/inventory/adjustments", {"product_id": pid, "movement_type": "correction",
                                                           "counted_quantity": 4, "reason": "cycle count"}))
    assert corr["quantity_delta"] == -2 and corr["balance_after"] == 4
    assert owner.ok(owner.get(f"/products/{pid}"))["quantity"] == 4

    # reason and idempotency key are mandatory
    assert owner.post("/inventory/adjustments", {"product_id": pid, "movement_type": "manual_increase",
                                                  "quantity": 1}).status_code == 422
    r = owner.client.post("/api/v1/inventory/adjustments", json={
        "product_id": pid, "movement_type": "manual_increase", "quantity": 1, "reason": "no key"},
        headers={"Authorization": f"Bearer {owner.token}"})
    assert r.status_code == 422 and r.json()["code"] == "idempotency_required"

    moves = owner.ok(owner.get("/inventory/movements", product_id=pid, sort="created_at"))["items"]
    assert [m["movement_type"] for m in moves] == ["opening", "manual_increase", "damage", "correction"]
    assert sum(m["quantity_delta"] for m in moves) == 4


def test_movements_are_immutable_in_database(owner):
    make_product(owner, sku="IMM-1", qty=5)
    with engine.connect() as conn:
        for stmt in ("UPDATE stock_movements SET quantity_delta = 100", "DELETE FROM stock_movements"):
            try:
                conn.execute(text(stmt))
                raise AssertionError("mutation should have failed")
            except Exception as exc:  # noqa: BLE001
                assert "immutable" in str(exc)
                conn.rollback()
    with engine.connect() as conn:
        try:
            conn.execute(text("UPDATE products SET quantity = -1"))
            raise AssertionError("negative stock should violate the check constraint")
        except Exception as exc:  # noqa: BLE001
            assert "quantity_non_negative" in str(exc)
