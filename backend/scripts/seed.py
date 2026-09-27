"""Seed a demo shop with realistic data (60 days of sales, khata, POs).

Usage:  python -m scripts.seed            (from backend/, after `alembic upgrade head`)
Logins: owner@demo.example.com / manager@demo.example.com / staff@demo.example.com.
Password: $MSME_DEMO_PASSWORD, or "password123" outside production.
"""

import datetime as dt
import os
import random
from decimal import Decimal

import app.services.invoicing as invoicing
from app.core.deps import Ctx
from app.db import SessionLocal
from app.enums import PaymentMethod, Role
from app.models import Category, Supplier, User
from app.schemas.auth import RegisterIn, ShopIn, UserCreate
from app.schemas.catalog import ProductCreate
from app.schemas.purchasing import POItemIn, PurchaseOrderIn, ReceiptIn, ReceiptLineIn, SupplierIn
from app.schemas.sales import (
    CreditNoteIn,
    CreditNoteItemIn,
    CustomerIn,
    InvoiceDraftIn,
    InvoiceItemIn,
    InvoicePostIn,
    PaymentIn,
)
from app.services import accounts, inventory, purchasing
from app.services import customers as customer_svc

CATALOG = [
    ("Staples", [("Basmati Rice 5kg", "RICE-5KG", "649.00", "520.00", "5", 40), ("Toor Dal 1kg", "DAL-TOOR-1", "165.00",
     "132.00", "5", 60), ("Sunflower Oil 1L", "OIL-SUN-1L", "155.00", "128.00", "5", 45),
     ("Atta 10kg", "ATTA-10KG", "480.00", "400.00", "5", 25), ("Sugar 1kg", "SUGAR-1KG", "48.00", "41.00", "5", 80)]),
    ("Snacks", [("Parle-G 800g", "PARLE-G-800", "90.00", "76.00", "18", 70), ("Maggi 12-pack", "MAGGI-12",
     "168.00", "140.00", "12", 35), ("Haldiram Bhujia 400g", "BHUJIA-400", "110.00", "88.00", "12", 6)]),
    ("Personal Care", [("Lux Soap 4x100g", "LUX-4PK", "180.00", "150.00", "18", 30), ("Colgate 200g", "COLGATE-200",
     "115.00", "95.00", "18", 3), ("Dove Shampoo 340ml", "DOVE-SH-340", "345.00", None, "18", 0)]),
    ("Beverages", [("Tata Tea 1kg", "TATA-TEA-1KG", "560.00", "470.00", "5", 18), ("Nescafe 100g", "NESCAFE-100",
     "340.00", "285.00", "18", 12)]),
]
CUSTOMERS = [("Ramesh Kumar", "9876543210", None, "29", "5000.00"), ("Sunita Traders", "9812345678",
             "29ABCDE1234F1Z5", "29", "25000.00"), ("Anil Stores (Mumbai)", "9820012345", "27PQRSX9876L1Z2", "27",
             None), ("Priya Sharma", "9900112233", None, "29", "2000.00")]


PASSWORD = os.environ.get("MSME_DEMO_PASSWORD", "").strip()


def main():
    global PASSWORD
    if not PASSWORD:
        if os.environ.get("MSME_ENVIRONMENT") == "production":
            print("MSME_DEMO_PASSWORD is not set; skipping demo data in production.")
            return
        PASSWORD = "password123"
    if len(PASSWORD) < 8:
        print("MSME_DEMO_PASSWORD must be at least 8 characters; skipping demo data.")
        return
    db = SessionLocal()
    rnd = random.Random(42)
    if db.query(User).filter(User.email == "owner@demo.example.com").first():
        print("Demo data already present.")
        return
    owner, _, _ = accounts.register(db, RegisterIn(
        shop=ShopIn(name="Sharma General Store", legal_name="Sharma General Store Pvt Ltd", gstin="29AAACS1234A1Z5",
                    state_code="29", address="12 MG Road, Bengaluru", phone="080-4000-1234"),
        owner_name="Vikram Sharma", email="owner@demo.example.com", password=PASSWORD))
    ctx = Ctx(db=db, user=owner, shop=owner.shop)
    staff_users = [accounts.create_user(ctx, UserCreate(email=f"{r.value}@demo.example.com", full_name=n,
                                                        password=PASSWORD, role=r))
                   for r, n in ((Role.manager, "Meera Iyer"), (Role.staff, "Ravi Das"))]
    db.commit()

    products = []
    for cat_name, items in CATALOG:
        cat = Category(shop_id=ctx.shop_id, name=cat_name)
        db.add(cat)
        db.flush()
        for name, sku, price, cost, gst, qty in items:
            products.append(inventory.create_product(ctx, ProductCreate(
                name=name, sku=sku, category_id=cat.id, sale_price=Decimal(price),
                cost_price=Decimal(cost) if cost else None, gst_rate=Decimal(gst), opening_quantity=qty + 60,
                low_stock_threshold=10, reorder_quantity=40)))
    customers = [customer_svc.create(ctx, CustomerIn(name=n, phone=ph, gstin=g, state_code=s,
                                                     credit_limit=Decimal(lim) if lim else None))
                 for n, ph, g, s, lim in CUSTOMERS]
    suppliers = []
    for name, state in (("Metro Wholesale", "29"), ("FMCG Distributors", "29")):
        s = Supplier(shop_id=ctx.shop_id, is_active=True, **SupplierIn(name=name, state_code=state).model_dump())
        db.add(s)
        suppliers.append(s)
    db.commit()

    now = dt.datetime.now(dt.UTC)
    sellers = [owner, *staff_users]
    for day in range(60, -1, -1):
        for _ in range(rnd.randint(0, 5) if day % 7 else rnd.randint(0, 2)):
            ts = now - dt.timedelta(days=day, hours=rnd.randint(0, 8), minutes=rnd.randint(0, 59))
            invoicing.utcnow = lambda ts=ts: ts
            seller = rnd.choice(sellers)
            sctx = Ctx(db=db, user=seller, shop=ctx.shop)
            picks = rnd.sample([p for p in products if p.quantity > 3], k=rnd.randint(1, 3))
            customer = rnd.choice([None, None, *customers])
            try:
                inv = invoicing.create_draft(sctx, InvoiceDraftIn(
                    customer_id=customer.id if customer else None,
                    items=[InvoiceItemIn(product_id=p.id, quantity=rnd.randint(1, 3),
                                         discount_percent=Decimal("5") if rnd.random() < 0.2 else None)
                           for p in picks]))
                total = inv.grand_total
                if customer is None or rnd.random() < 0.6:
                    pays = [PaymentIn(method=rnd.choice([PaymentMethod.cash, PaymentMethod.upi, PaymentMethod.card]),
                                      amount=total)]
                elif rnd.random() < 0.5:
                    pays = [PaymentIn(method=PaymentMethod.upi, amount=(total / 2).quantize(Decimal("0.01")))]
                else:
                    pays = []
                invoicing.post_invoice(sctx, inv.id, InvoicePostIn(payments=pays))
                db.commit()
            except Exception as exc:  # noqa: BLE001 - credit limits etc. just skip that sale
                db.rollback()
                print("skipped sale:", exc)
    invoicing.utcnow = lambda: dt.datetime.now(dt.UTC)

    # a return with restock on a recent credit invoice
    from sqlalchemy import select

    from app.models import Invoice
    recent = db.scalars(select(Invoice).where(Invoice.shop_id == ctx.shop_id, Invoice.customer_id.is_not(None),
                                              Invoice.balance_due > 0).order_by(Invoice.id.desc())).first()
    if recent:
        invoicing.create_credit_note(ctx, recent.id, CreditNoteIn(
            reason="Damaged pack returned", restock=True,
            items=[CreditNoteItemIn(invoice_item_id=recent.items[0].id, quantity=1)],
            refund_method=PaymentMethod.cash))
        db.commit()

    po = purchasing.create(ctx, PurchaseOrderIn(supplier_id=suppliers[0].id, items=[
        POItemIn(product_id=products[9].id, quantity=48, unit_cost=Decimal("95.00")),
        POItemIn(product_id=products[10].id, quantity=24, unit_cost=Decimal("290.00"))]))
    purchasing.send(ctx, po.id)
    purchasing.receive(ctx, po.id, ReceiptIn(items=[ReceiptLineIn(purchase_order_item_id=po.items[0].id,
                                                                    quantity=24)]))
    po2 = purchasing.create(ctx, PurchaseOrderIn(supplier_id=suppliers[1].id, items=[
        POItemIn(product_id=products[5].id, quantity=100, unit_cost=Decimal("74.00"))]))
    purchasing.send(ctx, po2.id)
    purchasing.create(ctx, PurchaseOrderIn(supplier_id=suppliers[1].id, items=[
        POItemIn(product_id=products[7].id, quantity=30, unit_cost=Decimal("86.00"))]))
    db.commit()
    print("Seeded demo shop. Log in as owner@demo.example.com with the demo password.")


if __name__ == "__main__":
    main()
