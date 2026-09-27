from tests.conftest import Api, make_customer, make_product, sell


def test_register_login_me(client, owner):
    me = owner.ok(owner.get("/auth/me"))
    assert me["user"]["role"] == "owner"
    assert me["shop"]["timezone"] == "Asia/Kolkata"
    assert "users.manage" in me["permissions"]

    bad = client.post("/api/v1/auth/login", json={"email": "owner@shopa.example.com", "password": "wrong-pass"})
    assert bad.status_code == 401


def test_requires_token(client):
    assert client.get("/api/v1/products").status_code == 401
    assert client.get("/api/v1/products", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_duplicate_email_rejected(client, owner):
    r = client.post("/api/v1/auth/register", json={
        "shop": {"name": "X", "state_code": "29"}, "owner_name": "X", "email": "OWNER@shopa.example.com",
        "password": "password123"})
    assert r.status_code == 409


def test_tenant_isolation_products_customers_invoices(owner, other_owner):
    p = make_product(owner, sku="A-1")
    c = make_customer(owner, "Alice")
    inv = owner.ok(sell(owner, [(p["id"], 1)], payments=[{"method": "cash", "amount": "118.00"}]))

    # Other shop cannot see or touch shop A's rows: they look like missing rows (404), and lists are empty.
    assert other_owner.get(f"/products/{p['id']}").status_code == 404
    assert other_owner.get(f"/customers/{c['id']}").status_code == 404
    assert other_owner.get(f"/invoices/{inv['id']}").status_code == 404
    assert other_owner.get(f"/customers/{c['id']}/ledger").status_code == 404
    assert other_owner.ok(other_owner.get("/products"))["total"] == 0
    assert other_owner.ok(other_owner.get("/invoices"))["total"] == 0
    assert other_owner.patch(f"/products/{p['id']}", {"name": "hijack"}).status_code == 404
    assert other_owner.post("/inventory/adjustments", {
        "product_id": p["id"], "movement_type": "manual_increase", "quantity": 5, "reason": "steal"}
    ).status_code == 404
    # Cannot reference another shop's product or customer in its own invoice.
    assert other_owner.post("/invoices", {"items": [{"product_id": p["id"], "quantity": 1}]}).status_code == 404
    op = make_product(other_owner, sku="B-1")
    assert other_owner.post("/invoices", {"customer_id": c["id"], "items": [
        {"product_id": op["id"], "quantity": 1}]}).status_code == 404
    # Same SKU is allowed in a different shop.
    make_product(other_owner, sku="A-1")
    assert other_owner.ok(other_owner.get("/inventory/movements"))["total"] == 2


def test_role_permissions(owner, manager, staff):
    p = make_product(owner, sku="R-1")
    # staff: no product writes, no reports, no users, no shop settings, no suppliers write
    assert staff.post("/products", {"name": "x", "sku": "x1", "sale_price": "1.00"}).status_code == 403
    assert staff.patch(f"/products/{p['id']}", {"name": "y"}).status_code == 403
    assert staff.get("/users").status_code == 403
    assert staff.patch("/shop", {"name": "z"}).status_code == 403
    assert staff.post("/suppliers", {"name": "s"}).status_code == 403
    assert staff.get("/dashboard/summary").status_code == 403
    assert staff.get("/reports/sales", start_date="2026-01-01", end_date="2026-01-31").status_code == 403
    assert staff.post("/customers", {"name": "c"}).status_code == 403
    # staff: allowed operations
    assert staff.get("/products").status_code == 200
    assert staff.get("/customers").status_code == 200
    staff.ok(staff.post("/inventory/adjustments", {
        "product_id": p["id"], "movement_type": "damage", "quantity": 1, "reason": "broken in transit"}))
    staff.ok(sell(staff, [(p["id"], 1)], payments=[{"method": "upi", "amount": "118.00"}]))

    # manager: products/reports yes; users, shop settings, GST reports no
    manager.ok(manager.post("/products", {"name": "m", "sku": "M-1", "sale_price": "5.00"}))
    assert manager.get("/reports/sales", start_date="2026-01-01", end_date="2026-01-31").status_code == 200
    assert manager.get("/users").status_code == 403
    assert manager.patch("/shop", {"name": "z"}).status_code == 403
    assert manager.get("/reports/gst", start_date="2026-01-01", end_date="2026-01-31").status_code == 403
    assert owner.get("/reports/gst", start_date="2026-01-01", end_date="2026-01-31").status_code == 200


def test_staff_sees_only_own_invoices(owner, staff):
    p = make_product(owner, sku="S-1", qty=5)
    mine = staff.ok(sell(staff, [(p["id"], 1)], payments=[{"method": "cash", "amount": "118.00"}]))
    theirs = owner.ok(sell(owner, [(p["id"], 1)], payments=[{"method": "cash", "amount": "118.00"}]))
    listed = staff.ok(staff.get("/invoices"))
    assert [i["id"] for i in listed["items"]] == [mine["id"]]
    assert staff.get(f"/invoices/{theirs['id']}").status_code == 404
    assert owner.ok(owner.get("/invoices"))["total"] == 2


def test_deactivated_user_loses_access(owner, staff):
    users = owner.ok(owner.get("/users", q="staff"))["items"]
    owner.ok(owner.patch(f"/users/{users[0]['id']}", {"is_active": False}))
    assert staff.get("/products").status_code == 401


def test_last_owner_cannot_be_demoted(owner):
    me = owner.ok(owner.get("/auth/me"))
    r = owner.patch(f"/users/{me['user']['id']}", {"role": "manager"})
    assert r.status_code == 422 and r.json()["code"] == "last_owner"


def test_api_helper_type():
    assert Api
