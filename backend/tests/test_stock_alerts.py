from app.services import inventory
from tests.conftest import make_product


def test_alert_emails_only_when_crossing_a_threshold(owner, manager, staff, monkeypatch):
    sent = []
    monkeypatch.setattr(inventory, "send_email", lambda recipient, subject, body: sent.append((recipient, subject)))

    def adjust(pid, kind, qty):
        owner.ok(owner.post("/inventory/adjustments",
                            {"product_id": pid, "movement_type": kind, "quantity": qty, "reason": "test"}))

    p = make_product(owner, sku="ALERT-1", qty=10, low_stock_threshold=5)

    adjust(p["id"], "manual_decrease", 4)  # 10 -> 6: still healthy
    assert sent == []

    adjust(p["id"], "manual_decrease", 2)  # 6 -> 4: crosses into low stock
    assert {s for _, s in sent} == {"Low Stock Alert: Product ALERT-1"}
    assert len(sent) == 2  # owner + manager; staff are not emailed

    sent.clear()
    adjust(p["id"], "manual_decrease", 1)  # 4 -> 3: already low, no repeat
    assert sent == []

    adjust(p["id"], "damage", 3)  # 3 -> 0: out of stock
    assert {s for _, s in sent} == {"Out of Stock Alert: Product ALERT-1"}


def test_email_failure_does_not_block_stock_change(owner, monkeypatch):
    def boom(**_):
        raise RuntimeError("mail provider down")

    monkeypatch.setattr(inventory, "send_email", boom)
    p = make_product(owner, sku="ALERT-2", qty=1)
    owner.ok(owner.post("/inventory/adjustments",
                        {"product_id": p["id"], "movement_type": "manual_decrease", "quantity": 1, "reason": "test"}))
    assert owner.ok(owner.get(f"/products/{p['id']}"))["quantity"] == 0
