import pytest

from app.services.ai.parser import parse
from tests.conftest import make_customer, make_product, sell


@pytest.mark.parametrize("text,intent,check", [
    ("stock of parle-g", "product_lookup", lambda e: e.product_query == "parle-g"),
    ("how many soap left", "product_lookup", lambda e: e.product_query == "soap"),
    ("received 10 parle-g and 5 x maggi", "stock_receipt",
     lambda e: [(i.query, i.quantity) for i in e.items] == [("parle-g", 10), ("maggi", 5)]),
    ("3 surf excel damaged", "stock_adjustment",
     lambda e: (e.adjustment, e.product_query, e.quantity) == ("damage", "surf excel", 3)),
    ("set stock of rice to 12", "stock_adjustment",
     lambda e: (e.adjustment, e.product_query, e.counted_quantity) == ("correction", "rice", 12)),
    ("reduce sugar by 2", "stock_adjustment", lambda e: (e.adjustment, e.quantity) == ("manual_decrease", 2)),
    ("bill 2 soap and 1 rice for Ramesh", "invoice_draft",
     lambda e: e.customer_query == "ramesh" and [(i.query, i.quantity) for i in e.items] == [("soap", 2),
                                                                                         ("rice", 1)]),
    ("bill 2 soap 1 atta for ramesh", "invoice_draft",
     lambda e: [(i.query, i.quantity) for i in e.items] == [("soap", 2), ("atta", 1)]),
    ("received 20 atta 10 sugar", "stock_receipt",
     lambda e: [(i.query, i.quantity) for i in e.items] == [("atta", 20), ("sugar", 10)]),
    ("Ramesh paid 500 upi", "payment_record",
     lambda e: (e.customer_query, e.amount, e.method) == ("ramesh", "500.00", "upi")),
    ("record payment of rs 1,250.50 for INV-000012 by card", "payment_record",
     lambda e: (e.invoice_number, e.amount, e.method) == ("INV-000012", "1250.50", "card")),
    ("khata of Suresh", "khata_lookup", lambda e: e.customer_query == "suresh"),
    ("how much does Suresh owe", "khata_lookup", lambda e: e.customer_query == "suresh"),
    ("sales this week", "report_summary", lambda e: (e.report, e.period) == ("sales", "this_week")),
    ("top products by units this month", "report_summary",
     lambda e: (e.report, e.metric, e.period) == ("top_products", "quantity", "this_month")),
    ("what is low stock", "report_summary", lambda e: e.report == "low_stock"),
    # Hinglish and everyday phrasings a shopkeeper actually uses.
    ("2 maggi 1 atta ramesh ko", "invoice_draft",
     lambda e: e.customer_query == "ramesh"
     and [(i.query, i.quantity) for i in e.items] == [("maggi", 2), ("atta", 1)]),
    ("Ramesh ko 2 sabun dedo, udhaar", "invoice_draft",
     lambda e: e.customer_query == "ramesh" and [(i.query, i.quantity) for i in e.items] == [("sabun", 2)]),
    ("ramesh ka hisaab", "khata_lookup", lambda e: e.customer_query == "ramesh"),
    ("how much maggi left", "product_lookup", lambda e: e.product_query == "maggi"),
    ("maggi kitna bacha", "product_lookup", lambda e: e.product_query == "maggi"),
    ("10 atta aaya", "stock_receipt", lambda e: [(i.query, i.quantity) for i in e.items] == [("atta", 10)]),
    ("what's low on stock", "report_summary", lambda e: e.report == "low_stock"),
    ("ramesh ne 500 diye", "payment_record", lambda e: (e.customer_query, e.amount) == ("ramesh", "500.00")),
    ("add new product biscuit 10 rupees", "unknown", lambda e: True),
    # Simple mode's tiles prepend "bill"/"received"; Hinglish phrasing must survive that.
    ("bill ramesh ko 2 sabun dedo", "invoice_draft",
     lambda e: e.customer_query == "ramesh" and [(i.query, i.quantity) for i in e.items] == [("sabun", 2)]),
    ("received 10 atta aaya", "stock_receipt", lambda e: [(i.query, i.quantity) for i in e.items] == [("atta", 10)]),
    ("sing me a song", "unknown", lambda e: True),
])
def test_rule_parser(text, intent, check):
    parsed = parse(text)
    assert parsed.intent == intent, parsed
    assert check(parsed.entities), parsed.entities


def _interpret(api, text):
    return api.ok(api.client.post("/api/v1/ai/interpret", json={"text": text, "use_llm": False},
                                  headers={"Authorization": f"Bearer {api.token}"}))


def test_read_intents_execute(owner):
    make_product(owner, sku="PARLE-G", name="Parle-G Biscuit", price="10.00", gst="5", qty=40)
    c = make_customer(owner, "Ramesh Kumar", phone="9876500000")
    p = make_product(owner, sku="SOAP", name="Lux Soap", price="30.00", gst="18", qty=10)
    owner.ok(sell(owner, [(p["id"], 1)], customer_id=c["id"]))

    out = _interpret(owner, "stock of parle-g")
    assert out["kind"] == "read" and out["proposal"] is None
    assert out["result"][0]["quantity"] == 40 and "40 in stock" in out["message"]
    out = _interpret(owner, "khata of ramesh")
    assert out["result"]["balance"] == "35.40" and "owes ₹35.40" in out["message"]
    out = _interpret(owner, "sales today")
    assert out["result"]["totals"]["gross_sales"] == "35.40"


def test_write_intents_only_propose(owner):
    p = make_product(owner, sku="PARLE-G", name="Parle-G Biscuit", price="10.00", gst="5", qty=40)
    c = make_customer(owner, "Ramesh")
    before = owner.ok(owner.get("/inventory/movements"))["total"]

    out = _interpret(owner, "bill 3 parle-g for ramesh")
    prop = out["proposal"]
    assert out["kind"] == "write" and prop["ready"] and prop["permitted"]
    assert prop["actions"] == [{"method": "POST", "path": "/invoices", "label": "Create draft invoice",
                                "body": {"customer_id": c["id"], "items": [{"product_id": p["id"], "quantity": 3}]}}]
    assert prop["preview"]["grand_total"] == "31.50"
    # nothing was created
    assert owner.ok(owner.get("/invoices"))["total"] == 0
    assert owner.ok(owner.get("/inventory/movements"))["total"] == before

    # confirming = calling the normal endpoint with an idempotency key; the server recomputes everything
    action = prop["actions"][0]
    draft = owner.ok(owner.post(action["path"], action["body"]))
    assert draft["grand_total"] == "31.50"

    out = _interpret(owner, "received 12 parle-g")
    assert out["proposal"]["actions"][0]["body"]["movement_type"] == "manual_increase"
    assert owner.ok(owner.get(f"/products/{p['id']}"))["quantity"] == 40


def test_proposal_flags_problems(owner, staff):
    make_product(owner, sku="SOAP-L", name="Lux Soap", price="30.00", gst="18", qty=1)
    make_product(owner, sku="SOAP-D", name="Dove Soap", price="50.00", gst="18", qty=1)
    out = _interpret(owner, "bill 2 soap")
    assert out["proposal"]["ready"] is False and len(out["candidates"]["item_0"]) == 2
    out = _interpret(owner, "reduce SOAP-L by 5")
    assert out["proposal"]["ready"] is False
    assert any("cannot go below zero" in w for w in out["proposal"]["warnings"])
    out = _interpret(owner, "Nobody paid 100 cash")
    assert out["proposal"]["ready"] is False
    # role checks happen in the proposal and again on the real endpoint
    c = make_customer(owner, "Credit Cust")
    p = make_product(owner, sku="X1", price="10.00", gst="0", qty=5)
    inv = owner.ok(sell(owner, [(p["id"], 1)], customer_id=c["id"]))
    out = _interpret(staff, f"record payment 5 cash for {inv['number']}")
    assert out["proposal"]["ready"] is False  # staff can't see an invoice created by someone else
    out = _interpret(owner, f"record payment 5 cash for {inv['number']}")
    assert out["proposal"]["ready"] is True
    assert out["proposal"]["actions"][0]["path"] == f"/invoices/{inv['id']}/payments"


def test_staff_cannot_read_sales_via_assistant(staff):
    out = _interpret(staff, "sales today")
    assert out["result"] is None and "don't have access" in out["message"]
