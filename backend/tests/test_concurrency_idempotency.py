import threading
import uuid

from tests.conftest import make_customer, make_product


def _run_parallel(fns):
    barrier = threading.Barrier(len(fns))
    results = [None] * len(fns)

    def runner(i, fn):
        barrier.wait()
        results[i] = fn()

    threads = [threading.Thread(target=runner, args=(i, fn)) for i, fn in enumerate(fns)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def test_concurrent_posting_never_oversells(owner):
    p = make_product(owner, sku="HOT", price="10.00", gst="0", qty=5)
    drafts = [owner.ok(owner.post("/invoices", {"items": [{"product_id": p["id"], "quantity": 2}]}))
              for _ in range(8)]
    pay = {"payments": [{"method": "cash", "amount": "20.00"}]}
    results = _run_parallel([lambda d=d: owner.post(f"/invoices/{d['id']}/post", pay) for d in drafts])
    codes = sorted(r.status_code for r in results)
    assert codes.count(200) == 2, [r.text for r in results]
    assert codes.count(409) == 6
    assert all(r.json()["code"] == "insufficient_stock" for r in results if r.status_code == 409)
    assert owner.ok(owner.get(f"/products/{p['id']}"))["quantity"] == 1
    moves = owner.ok(owner.get("/inventory/movements", product_id=p["id"]))["items"]
    assert sum(m["quantity_delta"] for m in moves) == 1
    numbers = sorted(r.json()["number"] for r in results if r.status_code == 200)
    assert numbers == ["INV-000001", "INV-000002"]


def test_concurrent_multi_product_posting_no_deadlock(owner):
    a = make_product(owner, sku="X", price="1.00", gst="0", qty=100)
    b = make_product(owner, sku="Y", price="1.00", gst="0", qty=100)
    drafts = []
    for i in range(10):
        order = [a, b] if i % 2 else [b, a]  # opposite line orders would deadlock without ordered locking
        drafts.append(owner.ok(owner.post("/invoices", {"items": [
            {"product_id": order[0]["id"], "quantity": 3}, {"product_id": order[1]["id"], "quantity": 4}]})))
    pay = {"payments": [{"method": "cash", "amount": "7.00"}]}
    results = _run_parallel([lambda d=d: owner.post(f"/invoices/{d['id']}/post", pay) for d in drafts])
    assert all(r.status_code == 200 for r in results), [r.text for r in results]
    # each product got 3 units on half the invoices and 4 units on the other half
    assert owner.ok(owner.get(f"/products/{a['id']}"))["quantity"] == 100 - 5 * 3 - 5 * 4
    assert owner.ok(owner.get(f"/products/{b['id']}"))["quantity"] == 100 - 5 * 3 - 5 * 4


def test_idempotent_retry_replays_without_side_effects(owner):
    p = make_product(owner, sku="IDEM", price="10.00", gst="0", qty=10)
    body = {"product_id": p["id"], "movement_type": "manual_increase", "quantity": 5, "reason": "delivery"}
    first = owner.post("/inventory/adjustments", body, key="adj-1")
    second = owner.post("/inventory/adjustments", body, key="adj-1")
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    assert second.headers.get("Idempotent-Replay") == "true"
    assert owner.ok(owner.get(f"/products/{p['id']}"))["quantity"] == 15

    # same key, different payload -> rejected
    r = owner.post("/inventory/adjustments", {**body, "quantity": 6}, key="adj-1")
    assert r.status_code == 409 and r.json()["code"] == "idempotency_key_reused"


def test_idempotent_invoice_post_and_payment(owner):
    p = make_product(owner, sku="IP", price="10.00", gst="0", qty=10)
    cust = make_customer(owner, "Retry Customer")
    draft = owner.ok(owner.post("/invoices", {"customer_id": cust["id"],
                                              "items": [{"product_id": p["id"], "quantity": 3}]}))
    r1 = owner.post(f"/invoices/{draft['id']}/post", {}, key="post-1")
    r2 = owner.post(f"/invoices/{draft['id']}/post", {}, key="post-1")
    assert r1.status_code == r2.status_code == 200 and r1.json()["number"] == r2.json()["number"]
    assert owner.ok(owner.get(f"/products/{p['id']}"))["quantity"] == 7

    pay = {"method": "cash", "amount": "10.00"}
    owner.ok(owner.post(f"/invoices/{draft['id']}/payments", pay, key="pay-1"))
    owner.ok(owner.post(f"/invoices/{draft['id']}/payments", pay, key="pay-1"))
    inv = owner.ok(owner.get(f"/invoices/{draft['id']}"))
    assert inv["amount_paid"] == "10.00" and len(inv["payments"]) == 1


def test_failed_request_does_not_burn_key(owner):
    p = make_product(owner, sku="FAIL", price="10.00", gst="0", qty=1)
    body = {"product_id": p["id"], "movement_type": "manual_decrease", "quantity": 2, "reason": "shrink"}
    assert owner.post("/inventory/adjustments", body, key="k-fail").status_code == 409
    owner.ok(owner.post("/inventory/adjustments", {"product_id": p["id"], "movement_type": "manual_increase",
                                                    "quantity": 5, "reason": "restock"}))
    # the earlier failure was not stored, so the same key can now succeed
    owner.ok(owner.post("/inventory/adjustments", body, key="k-fail"))
    assert owner.ok(owner.get(f"/products/{p['id']}"))["quantity"] == 4


def test_idempotency_keys_are_scoped_per_user(owner, manager):
    p = make_product(owner, sku="SCOPE", price="10.00", gst="0", qty=0)
    body = {"product_id": p["id"], "movement_type": "manual_increase", "quantity": 1, "reason": "count"}
    owner.ok(owner.post("/inventory/adjustments", body, key="shared"))
    manager.ok(manager.post("/inventory/adjustments", body, key="shared"))
    assert owner.ok(owner.get(f"/products/{p['id']}"))["quantity"] == 2


def test_concurrent_duplicate_requests_execute_once(owner):
    p = make_product(owner, sku="DUP", price="10.00", gst="0", qty=0)
    body = {"product_id": p["id"], "movement_type": "manual_increase", "quantity": 1, "reason": "race"}
    key = str(uuid.uuid4())
    results = _run_parallel([lambda: owner.post("/inventory/adjustments", body, key=key) for _ in range(6)])
    assert all(r.status_code == 201 for r in results), [r.text for r in results]
    assert len({r.json()["id"] for r in results}) == 1
    assert owner.ok(owner.get(f"/products/{p['id']}"))["quantity"] == 1


def test_all_mutations_require_key(owner):
    headers = {"Authorization": f"Bearer {owner.token}"}
    for method, path, body in [
        ("post", "/products", {"name": "x", "sku": "x", "sale_price": "1.00"}),
        ("post", "/customers", {"name": "x"}),
        ("post", "/suppliers", {"name": "x"}),
        ("post", "/categories", {"name": "x"}),
        ("patch", "/shop", {"name": "x"}),
        ("post", "/invoices", {"items": [{"product_id": 1, "quantity": 1}]}),
    ]:
        r = getattr(owner.client, method)(f"/api/v1{path}", json=body, headers=headers)
        assert r.status_code == 422 and r.json().get("code") == "idempotency_required", (path, r.text)
