"""Turn a parsed intent into either an executed *read* or a confirmation-safe *write proposal*.

Reads use the normal read services and run immediately. Writes are never executed here: the response
describes the exact REST call(s) the client will make after the user confirms. Those calls go through the
regular endpoints, so the backend re-checks SKUs, totals, tax, stock, permissions and idempotency.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import func, or_, select

from app.core.deps import Ctx
from app.core.money import ZERO, q
from app.core.pagination import like
from app.core.permissions import P
from app.core.timeutil import local_today
from app.enums import InvoiceStatus
from app.models import Customer, Invoice, Product
from app.schemas.ai import Candidate, InterpretOut, Proposal, ProposedAction
from app.schemas.catalog import stock_status
from app.services import customers as customer_svc
from app.services import reports, tax
from app.services.ai.llm import parse_with_llm
from app.services.ai.parser import ParsedIntent, parse

# ------------------------------------------------------------------ resolution
# Spoken Hindi for everyday stock; tried only when the words as said match nothing ("sabun" -> "Lux Soap").
# ponytail: a fixed word list; per-shop aliases on products would be the upgrade.
HINDI_PRODUCT_WORDS = {
    "sabun": "soap", "sabu": "soap", "chawal": "rice", "chaawal": "rice", "cheeni": "sugar", "chini": "sugar",
    "shakkar": "sugar", "tel": "oil", "dal": "dal", "daal": "dal", "chai": "tea", "chai patti": "tea",
    "chaipatti": "tea", "namak": "salt", "doodh": "milk", "biskut": "biscuit", "manjan": "toothpaste",
    "shampu": "shampoo", "namkeen": "bhujia", "kaafi": "coffee", "kofi": "coffee", "atta": "atta", "aata": "atta",
}


def find_products(ctx: Ctx, query: str, limit: int = 5) -> list[Product]:
    found = _find_products(ctx, query, limit)
    if not found:
        english = HINDI_PRODUCT_WORDS.get(query.lower()) or " ".join(
            HINDI_PRODUCT_WORDS.get(w, w) for w in query.lower().split()
        )
        if english != query.lower():
            found = _find_products(ctx, english, limit)
    return found


def _find_products(ctx: Ctx, query: str, limit: int) -> list[Product]:
    base = select(Product).where(Product.shop_id == ctx.shop_id, Product.is_active.is_(True))
    exact = ctx.db.scalars(base.where(or_(func.lower(Product.sku) == query.lower(),
                                          func.lower(Product.name) == query.lower()))).all()
    if exact:
        return list(exact)
    words = [w for w in query.split() if len(w) > 1] or [query]
    stmt = base
    for w in words:
        stmt = stmt.where(or_(Product.name.ilike(like(w)), Product.sku.ilike(like(w))))
    return list(ctx.db.scalars(stmt.order_by(func.length(Product.name), Product.id).limit(limit)).all())


def find_customers(ctx: Ctx, query: str, limit: int = 5) -> list[Customer]:
    base = select(Customer).where(Customer.shop_id == ctx.shop_id, Customer.is_active.is_(True))
    digits = "".join(ch for ch in query if ch.isdigit())
    if len(digits) >= 6:
        by_phone = ctx.db.scalars(base.where(Customer.phone.ilike(like(digits)))).all()
        if by_phone:
            return list(by_phone)
    exact = ctx.db.scalars(base.where(func.lower(Customer.name) == query.lower())).all()
    if exact:
        return list(exact)
    return list(ctx.db.scalars(base.where(Customer.name.ilike(like(query))).order_by(Customer.name, Customer.id)
                               .limit(limit)).all())


def _product_candidate(p: Product) -> Candidate:
    return Candidate(id=p.id, label=f"{p.name} ({p.sku})", detail=f"stock {p.quantity}, ₹{p.sale_price}")


def _customer_candidate(c: Customer) -> Candidate:
    return Candidate(id=c.id, label=c.name, detail=c.phone)


class _Resolver:
    def __init__(self, ctx: Ctx):
        self.ctx = ctx
        self.warnings: list[str] = []
        self.candidates: dict[str, list[Candidate]] = {}
        self.ready = True

    def product(self, query: str, key: str) -> Product | None:
        found = find_products(self.ctx, query)
        if len(found) == 1:
            return found[0]
        self.ready = False
        if not found:
            self.warnings.append(f"No active product matches '{query}'.")
        else:
            self.warnings.append(f"'{query}' matches {len(found)} products; say the SKU to pick one.")
            self.candidates[key] = [_product_candidate(p) for p in found]
        return None

    def customer(self, query: str) -> Customer | None:
        found = find_customers(self.ctx, query)
        if len(found) == 1:
            return found[0]
        self.ready = False
        if not found:
            self.warnings.append(f"No customer matches '{query}'.")
        else:
            self.warnings.append(f"'{query}' matches {len(found)} customers; be more specific.")
            self.candidates["customer"] = [_customer_candidate(c) for c in found]
        return None


def _period_range(ctx: Ctx, period: str | None) -> tuple[dt.date, dt.date]:
    today = local_today(ctx.shop.timezone)
    match period:
        case "yesterday":
            return today - dt.timedelta(days=1), today - dt.timedelta(days=1)
        case "this_week":
            return today - dt.timedelta(days=today.weekday()), today
        case "last_7_days":
            return today - dt.timedelta(days=6), today
        case "this_month":
            return today.replace(day=1), today
        case "last_30_days":
            return today - dt.timedelta(days=29), today
        case _:
            return today, today


# ------------------------------------------------------------------ reads
def _read(ctx: Ctx, parsed: ParsedIntent) -> tuple[str, object, dict]:
    e = parsed.entities
    if parsed.intent == "product_lookup":
        if not ctx.can(P.products_read):
            return "You don't have access to products.", None, {}
        products = find_products(ctx, e.product_query or "", limit=10)
        rows = [{"id": p.id, "name": p.name, "sku": p.sku, "quantity": p.quantity, "sale_price": p.sale_price,
                 "stock_status": stock_status(p.quantity, p.low_stock_threshold)} for p in products]
        if not rows:
            return f"No products match '{e.product_query}'.", [], {}
        if len(rows) == 1:
            r = rows[0]
            return f"{r['name']} ({r['sku']}): {r['quantity']} in stock at ₹{r['sale_price']}.", rows, {}
        return f"Found {len(rows)} products matching '{e.product_query}'.", rows, {}

    if parsed.intent == "khata_lookup":
        if not ctx.can(P.khata_read):
            return "You don't have access to khata.", None, {}
        if not e.customer_query:
            if not ctx.can(P.reports_view):
                return "Tell me which customer's khata to show.", None, {}
            rep = reports.khata_report(ctx)
            return (f"Total outstanding ₹{rep['total_outstanding']} across {len(rep['rows'])} customers "
                    f"(₹{rep['total_overdue']} overdue).", rep["rows"][:10], {})
        found = find_customers(ctx, e.customer_query)
        if not found:
            return f"No customer matches '{e.customer_query}'.", None, {}
        if len(found) > 1:
            outs = [customer_svc.get_with_balance(ctx, c.id) for c in found]
            return (f"'{e.customer_query}' matches {len(found)} customers.", [o.model_dump() for o in outs],
                    {"customer": [_customer_candidate(c) for c in found]})
        out = customer_svc.get_with_balance(ctx, found[0].id)
        msg = f"{out.name} owes ₹{out.balance}."
        if out.overdue_amount > 0:
            msg += f" ₹{out.overdue_amount} is overdue."
        return msg, out.model_dump(), {}

    if parsed.intent == "report_summary":
        if e.report in ("low_stock", "out_of_stock"):
            if not ctx.can(P.inventory_read):
                return "You don't have access to inventory reports.", None, {}
            rows = reports.stock_alerts(ctx, "low" if e.report == "low_stock" else "out")["rows"]
            label = "low on stock" if e.report == "low_stock" else "out of stock"
            names = ", ".join(r["name"] for r in rows[:5])
            return (f"{len(rows)} product(s) {label}" + (f": {names}" if names else "") + ".", rows, {})
        if not ctx.can(P.reports_view):
            return "You don't have access to sales reports.", None, {}
        start, end = _period_range(ctx, e.period)
        if e.report == "top_products":
            rep = reports.top_products(ctx, start, end, e.metric or "revenue", 5)
            if not rep["rows"]:
                return "No sales in that period.", rep, {}
            best = rep["rows"][0]
            return (f"Top product by {rep['metric'].replace('_', ' ')}: {best['product_name']} "
                    f"({best['metric_value']}).", rep, {})
        rep = reports.sales_by_period(ctx, start, end, "day")
        t = rep["totals"]
        span = start.isoformat() if start == end else f"{start.isoformat()} to {end.isoformat()}"
        return (f"Sales {span}: ₹{t['net_sales']} net from {t['invoice_count']} invoice(s), "
                f"{t['units_sold']} unit(s).", rep, {})

    return ("Sorry, I didn't understand. Try 'stock of parle-g', 'bill 2 soap for Ramesh', "
            "'Ramesh paid 500 upi', 'khata of Ramesh' or 'sales this week'.", None, {})


# ------------------------------------------------------------------ writes
def _propose(ctx: Ctx, parsed: ParsedIntent) -> tuple[str, Proposal, dict]:
    e = parsed.entities
    res = _Resolver(ctx)
    actions: list[ProposedAction] = []
    summary: list[str] = []
    preview: dict | None = None
    perm: P

    if parsed.intent == "stock_receipt":
        perm = P.inventory_adjust
        title = "Receive stock"
        if not e.items:
            res.ready = False
            res.warnings.append("Which products and how many? e.g. 'received 10 parle-g'.")
        for idx, item in enumerate(e.items):
            p = res.product(item.query, f"item_{idx}")
            if p:
                actions.append(ProposedAction(
                    method="POST", path="/inventory/adjustments", label=f"+{item.quantity} {p.name}",
                    body={"product_id": p.id, "movement_type": "manual_increase", "quantity": item.quantity,
                          "reason": e.reason or "Stock received (assistant)"}))
                summary.append(f"{p.name} ({p.sku}): {p.quantity} → {p.quantity + item.quantity}")

    elif parsed.intent == "stock_adjustment":
        perm = P.inventory_adjust
        title = "Adjust stock"
        p = res.product(e.product_query, "product") if e.product_query else None
        if not e.product_query:
            res.ready = False
            res.warnings.append("Which product?")
        if p:
            if e.adjustment == "correction":
                new_qty = e.counted_quantity or 0
                body = {"product_id": p.id, "movement_type": "correction", "counted_quantity": new_qty,
                        "reason": e.reason or "Stock count correction"}
                if new_qty == p.quantity:
                    res.ready = False
                    res.warnings.append("Counted quantity equals current stock; nothing to change.")
            else:
                qty = e.quantity or 0
                delta = qty if e.adjustment == "manual_increase" else -qty
                new_qty = p.quantity + delta
                body = {"product_id": p.id, "movement_type": e.adjustment or "manual_decrease", "quantity": qty,
                        "reason": e.reason or "Adjustment (assistant)"}
                if new_qty < 0:
                    res.ready = False
                    res.warnings.append(f"Only {p.quantity} in stock; stock cannot go below zero.")
            actions.append(ProposedAction(method="POST", path="/inventory/adjustments", body=body,
                                          label=f"{body['movement_type'].replace('_', ' ')}: {p.name}"))
            summary.append(f"{p.name} ({p.sku}): {p.quantity} → {new_qty}")
            summary.append(f"Reason: {body['reason']}")

    elif parsed.intent == "invoice_draft":
        perm = P.invoices_create
        title = "Create invoice draft"
        customer = res.customer(e.customer_query) if e.customer_query else None
        if not e.items:
            res.ready = False
            res.warnings.append("Which products? e.g. 'bill 2 soap and 1 rice for Ramesh'.")
        place = (customer.state_code if customer and customer.state_code else None) or ctx.shop.state_code
        supply = tax.supply_type_for(ctx.shop.state_code, place)
        totals = tax.Totals()
        lines = []
        for idx, item in enumerate(e.items):
            p = res.product(item.query, f"item_{idx}")
            if not p:
                continue
            line = tax.compute_line(item.quantity, p.sale_price, p.gst_rate, ZERO, supply)
            totals.add(line)
            lines.append({"product_id": p.id, "quantity": item.quantity})
            summary.append(f"{item.quantity} × {p.name} @ ₹{p.sale_price} + {p.gst_rate}% GST = ₹{line.total}")
            if p.quantity < item.quantity:
                res.warnings.append(f"Only {p.quantity} {p.name} in stock; posting will fail unless restocked.")
        summary.insert(0, f"Customer: {customer.name if customer else 'Walk-in'}")
        if lines:
            actions.append(ProposedAction(method="POST", path="/invoices", label="Create draft invoice",
                                          body={"customer_id": customer.id if customer else None, "items": lines}))
            preview = {"supply_type": supply.value, "taxable_total": totals.taxable_total,
                       "tax_total": totals.cgst_total + totals.sgst_total + totals.igst_total,
                       "grand_total": totals.grand_total,
                       "note": "Estimate only. The server recalculates prices, tax and stock when saving and posting."}
            summary.append(f"Estimated total: ₹{totals.grand_total}")

    elif parsed.intent == "payment_record":
        perm = P.payments_record
        title = "Record payment"
        amount = Decimal(e.amount) if e.amount else None
        if amount is None or amount <= 0:
            res.ready = False
            res.warnings.append("How much was paid?")
        method = e.method or "cash"
        if e.invoice_number:
            inv = ctx.db.scalar(select(Invoice).where(Invoice.shop_id == ctx.shop_id,
                                                      func.upper(Invoice.number) == e.invoice_number.upper()))
            if inv is None or (not ctx.can(P.invoices_read_all) and ctx.user.id not in (inv.created_by,
                                                                                         inv.posted_by)):
                res.ready = False
                res.warnings.append(f"Invoice {e.invoice_number} not found.")
            elif inv.status == InvoiceStatus.draft:
                res.ready = False
                res.warnings.append(f"Invoice {e.invoice_number} is still a draft.")
            else:
                summary.append(f"Invoice {inv.number}: balance due ₹{inv.balance_due}")
                if amount is not None and amount > inv.balance_due:
                    res.ready = False
                    res.warnings.append(f"Amount exceeds the balance due (₹{inv.balance_due}).")
                if amount:
                    actions.append(ProposedAction(method="POST", path=f"/invoices/{inv.id}/payments",
                                                  label=f"₹{q(amount)} {method}",
                                                  body={"method": method, "amount": str(q(amount))}))
        elif e.customer_query:
            c = res.customer(e.customer_query)
            if c:
                out = customer_svc.get_with_balance(ctx, c.id)
                summary.append(f"{c.name}: khata balance ₹{out.balance}")
                if amount is not None and amount > out.balance:
                    res.ready = False
                    res.warnings.append(f"Amount exceeds the outstanding balance (₹{out.balance}).")
                if amount:
                    actions.append(ProposedAction(method="POST", path=f"/customers/{c.id}/payments",
                                                  label=f"₹{q(amount)} {method} from {c.name}",
                                                  body={"method": method, "amount": str(q(amount))}))
                    summary.append("Allocated to the oldest open invoices first.")
        else:
            res.ready = False
            res.warnings.append("Which customer or invoice is this payment for?")
        if amount:
            summary.insert(0, f"Amount: ₹{q(amount)} via {method.replace('_', ' ')}")
    else:  # pragma: no cover - guarded by caller
        raise ValueError(parsed.intent)

    permitted = ctx.can(perm)
    if not permitted:
        res.warnings.insert(0, f"Your role ({ctx.role.value}) is not allowed to do this.")
    ready = res.ready and permitted and bool(actions)
    proposal = Proposal(title=title, summary=summary, actions=actions, warnings=res.warnings,
                        permitted=permitted, ready=ready, preview=preview)
    message = "Please review and confirm." if ready else "I need a bit more information before this can run."
    return message, proposal, res.candidates


def interpret(ctx: Ctx, text: str, use_llm: bool = True) -> InterpretOut:
    parsed = (parse_with_llm(text) if use_llm else None) or parse(text)
    base = dict(text=text, intent=parsed.intent, kind=parsed.kind, source=parsed.source,
                confidence=parsed.confidence, entities=parsed.entities)
    if parsed.kind == "read":
        message, result, candidates = _read(ctx, parsed)
        return InterpretOut(**base, message=message, result=result, candidates=candidates)
    message, proposal, candidates = _propose(ctx, parsed)
    return InterpretOut(**base, message=message, proposal=proposal, candidates=candidates)
