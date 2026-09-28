"""Deterministic natural-language parser for shop commands (English + common Hinglish words).

The parser only *extracts* intent and entities. It never touches the database; resolution of SKUs,
customers, totals, stock and permissions happens in ``actions.py`` using the normal services.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, Field

Intent = Literal[
    "product_lookup",
    "stock_receipt",
    "stock_adjustment",
    "invoice_draft",
    "payment_record",
    "khata_lookup",
    "report_summary",
    "unknown",
]
READ_INTENTS = {"product_lookup", "khata_lookup", "report_summary", "unknown"}


class ItemRef(BaseModel):
    query: str
    quantity: int = Field(gt=0)


class Entities(BaseModel):
    items: list[ItemRef] = []
    product_query: str | None = None
    customer_query: str | None = None
    invoice_number: str | None = None
    amount: str | None = Field(None, description="Decimal string, e.g. '500.00'")
    method: Literal["cash", "upi", "card", "bank_transfer"] | None = None
    adjustment: Literal["manual_increase", "manual_decrease", "damage", "correction"] | None = None
    quantity: int | None = None
    counted_quantity: int | None = None
    reason: str | None = None
    report: Literal["sales", "top_products", "low_stock", "out_of_stock", "khata"] | None = None
    period: Literal["today", "yesterday", "this_week", "last_7_days", "this_month", "last_30_days"] | None = None
    metric: Literal["revenue", "quantity", "invoice_count"] | None = None


class ParsedIntent(BaseModel):
    intent: Intent
    entities: Entities = Entities()
    confidence: float = 0.0
    source: Literal["rules", "llm"] = "rules"

    @property
    def kind(self) -> Literal["read", "write"]:
        return "read" if self.intent in READ_INTENTS else "write"


_METHODS = {
    "cash": "cash", "nakad": "cash", "upi": "upi", "gpay": "upi", "google pay": "upi", "phonepe": "upi",
    "paytm": "upi", "card": "card", "debit card": "card", "credit card": "card", "bank": "bank_transfer",
    "neft": "bank_transfer", "imps": "bank_transfer", "rtgs": "bank_transfer", "transfer": "bank_transfer",
    "bank transfer": "bank_transfer",
}
_AMOUNT = re.compile(r"(?:₹|rs\.?|inr|rupees?)?\s*(\d+(?:,\d{3})*(?:\.\d{1,2})?)\s*(?:rs|rupees?|/-)?", re.I)
_INVOICE = re.compile(r"\b([a-z]{1,8}-?\d{3,})\b", re.I)
_QTY_WORDS = r"(?:x|units?|pcs|pieces?|packs?|packets?|nos|boxes|box|bottles?|kg|dozen)?"
_ITEM_LEAD = re.compile(rf"^(\d+)\s*{_QTY_WORDS}\s*(?:of\s+)?(.+)$", re.I)
_ITEM_TRAIL = re.compile(rf"^(.+?)\s*(?:x|×|qty|quantity)?\s*(\d+)\s*{_QTY_WORDS}$", re.I)
_FILLER = re.compile(r"\b(please|pls|kindly|ji|bhai|the|a|an)\b", re.I)


def _clean(text: str) -> str:
    text = _FILLER.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip(" .,!?")


def _amount(text: str) -> str | None:
    for m in _AMOUNT.finditer(text):
        raw = m.group(1).replace(",", "")
        # skip numbers that are clearly invoice numbers (e.g. INV-000012)
        start = m.start(1)
        if start > 0 and text[start - 1] == "-":
            continue
        try:
            return str(Decimal(raw).quantize(Decimal("0.01")))
        except InvalidOperation:
            continue
    return None


def _method(text: str) -> str | None:
    low = text.lower()
    for word in sorted(_METHODS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(word)}\b", low):
            return _METHODS[word]
    return None


# Spoken quantities (Sarvam writes "teen maggi", not "3 maggi"). Only an item's first word is read as a
# number, because "do" is also the verb in "de do", which the sale rules strip before items are parsed.
_NUMBER_WORDS = {
    "ek": 1, "one": 1, "do": 2, "two": 2, "teen": 3, "three": 3, "char": 4, "chaar": 4, "four": 4,
    "paanch": 5, "panch": 5, "five": 5, "chhe": 6, "che": 6, "six": 6, "saat": 7, "seven": 7,
    "aath": 8, "eight": 8, "nau": 9, "nine": 9, "das": 10, "dus": 10, "ten": 10,
}
_NUMBER_WORD = re.compile(
    rf"(?:(?<=^)|(?<=,)|(?<=\band\b)|(?<=\baur\b))(\s*)({'|'.join(_NUMBER_WORDS)})\s+(?=[a-z])", re.I
)


def _digits(fragment: str) -> str:
    return _NUMBER_WORD.sub(lambda m: f"{m.group(1)}{_NUMBER_WORDS[m.group(2).lower()]} ", fragment)


def parse_items(fragment: str) -> list[ItemRef]:
    fragment = _digits(fragment.strip())
    items = []
    chunks = []
    for chunk in re.split(r",|\band\b|\baur\b|&|\+", fragment, flags=re.I):
        chunk = _clean(chunk)
        # "2 soap 1 atta": quantity-first lists often skip "and", so a new number starts a new item.
        chunks.extend(re.split(r"\s+(?=\d+\s+[^\d\s])", chunk) if re.match(r"\d", chunk) else [chunk])
    for chunk in chunks:
        if not chunk:
            continue
        m = _ITEM_LEAD.match(chunk)
        if m:
            items.append(ItemRef(query=_clean(m.group(2)), quantity=int(m.group(1))))
            continue
        m = _ITEM_TRAIL.match(chunk)
        if m:
            items.append(ItemRef(query=_clean(m.group(1)), quantity=int(m.group(2))))
            continue
        items.append(ItemRef(query=chunk, quantity=1))
    return [i for i in items if i.query]


def _strip_credit(text: str) -> str:
    return re.sub(r"\b(?:udhaar|udhar|on credit|khate me|khata me)\b", " ", text)


def _period(low: str) -> str | None:
    table = [
        (r"\byesterday|kal\b", "yesterday"),
        (r"\blast\s*7\s*days|past week\b", "last_7_days"),
        (r"\blast\s*30\s*days|past month\b", "last_30_days"),
        (r"\bthis week|weekly|is hafte\b", "this_week"),
        (r"\bthis month|monthly|is mahine\b", "this_month"),
        (r"\btoday|aaj\b", "today"),
    ]
    for pattern, value in table:
        if re.search(pattern, low):
            return value
    return None


def parse(text: str) -> ParsedIntent:
    raw = text.strip()
    low = raw.lower()
    ents = Entities()

    # "Ramesh ko 2 sabun dedo" / "2 maggi 1 atta ramesh ko": Hinglish sale to a customer, with or without a
    # leading "bill"/"sell" (simple mode's Sell tile adds one).
    ko = re.sub(r"^(?:create |make |new )?(?:bill|invoice|sell|sale|billing)\s+", "", low)
    m = re.match(r"^([a-z][\w .'-]*?)\s+ko\s+(.+?)\s+(?:de ?do|de diya|diya|dena|bech ?do|becho|bech diya)\b", ko) \
        or re.match(r"^([a-z][\w .'-]*?)\s+ko\s+(\d.*)$", ko)
    if m:
        ents.customer_query, ents.items = _clean(m.group(1)), parse_items(_strip_credit(m.group(2)))
        return ParsedIntent(intent="invoice_draft", entities=ents, confidence=0.75 if ents.items else 0.4)
    # ponytail: takes the one word before "ko" as the name; "2 maggi ramesh kumar ko" needs "bill ... for" instead.
    m = re.match(r"^(\d.*)\s+([a-z][a-z.'-]*)\s+ko\b", ko)
    if m:
        ents.customer_query, ents.items = _clean(m.group(2)), parse_items(m.group(1))
        return ParsedIntent(intent="invoice_draft", entities=ents, confidence=0.75 if ents.items else 0.4)

    # ---------------------------------------------------------------- invoice draft
    m = re.match(r"^(?:create |make |new )?(?:bill|invoice|sell|sale|billing)\b(?:\s+(?:for|of))?\s*(.*)$", low)
    if m:
        body = m.group(1)
        cust = re.search(r"\b(?:for|to|customer)\s+([a-z][\w .'-]*)$", body)
        if cust:
            ents.customer_query = _clean(cust.group(1))
            body = body[: cust.start()]
        ents.items = parse_items(body)
        return ParsedIntent(intent="invoice_draft", entities=ents, confidence=0.8 if ents.items else 0.4)

    # ---------------------------------------------------------------- stock adjustment
    m = re.match(r"^(?:set|update|correct)\s+(?:stock|count|quantity)\s+(?:of\s+)?(.+?)\s+(?:to|=)\s*(\d+)$", low)
    if m:
        ents.product_query, ents.adjustment = _clean(m.group(1)), "correction"
        ents.counted_quantity = int(m.group(2))
        ents.reason = "Stock count correction"
        return ParsedIntent(intent="stock_adjustment", entities=ents, confidence=0.85)
    m = re.search(r"\b(damaged|damage|broken|expired|spoiled|kharab|tuta)\b", low)
    if m:
        items = parse_items(re.sub(r"\b(damaged|damage|broken|expired|spoiled|kharab|tuta|mark|as|are|is)\b", " ",
                                   low))
        if items:
            ents.product_query, ents.quantity = items[0].query, items[0].quantity
            ents.adjustment, ents.reason = "damage", f"Marked {m.group(1)}"
            return ParsedIntent(intent="stock_adjustment", entities=ents, confidence=0.75)
    m = re.match(r"^(?:reduce|remove|decrease|minus|less)\s+(?:stock\s+(?:of\s+)?)?(.+?)\s+(?:by\s+)?(\d+)$", low) or \
        re.match(r"^(?:reduce|remove|decrease)\s+(\d+)\s+(?:of\s+)?(.+)$", low)
    if m:
        a, b = m.group(1), m.group(2)
        query, qty = (b, a) if a.isdigit() else (a, b)
        ents.product_query, ents.quantity = _clean(query), int(qty)
        ents.adjustment, ents.reason = "manual_decrease", "Manual decrease (voice)"
        return ParsedIntent(intent="stock_adjustment", entities=ents, confidence=0.7)

    # ---------------------------------------------------------------- stock receipt
    m = re.match(r"^(?:received|receive|got|restock|restocked|stock in|add stock|add|aaya|aaye)\b\s*(?:stock\s+)?(.*)$",
                 low) or re.match(r"^()(\d.*?)\s+(?:aaya|aaye|aa gaya|aa gaye|arrived|came in|came|received)$", low)
    if m and m.lastindex == 2:  # quantity first, arrival verb last: "10 atta aaya"
        ents.items, ents.reason = parse_items(m.group(2)), "Stock received (assistant)"
        return ParsedIntent(intent="stock_receipt", entities=ents, confidence=0.8 if ents.items else 0.4)
    if m and m.group(1) and not re.match(r"^(?:new\s+)?(?:product|item|customer|supplier|staff|user)\b", m.group(1)):
        body = re.sub(r"\bfrom\s+[a-z][\w .'-]*$", "", m.group(1))
        body = re.sub(r"\s+(?:aaya|aaye|aa gaya|aa gaye|arrived|came in|came)$", "", body)
        ents.items = parse_items(body)
        ents.reason = "Stock received (assistant)"
        return ParsedIntent(intent="stock_receipt", entities=ents, confidence=0.8 if ents.items else 0.4)

    # ---------------------------------------------------------------- payment
    if re.search(r"\b(paid|pays|payment|received payment|jama|diya|diye)\b", low) or \
            re.match(r"^(?:record|receive|take)\s+(?:a\s+)?(?:payment|₹|rs)", low):
        ents.amount = _amount(re.sub(_INVOICE, " ", low))
        ents.method = _method(low) or "cash"
        inv = _INVOICE.search(raw)
        if inv and re.search(r"\d{3,}", inv.group(1)):
            ents.invoice_number = inv.group(1).upper()
        cust = re.match(r"^([a-z][\w .'-]*?)\s+(?:has\s+)?(?:paid|pays|ne)\b", low) or \
            re.search(r"\bfrom\s+([a-z][\w .'-]*?)(?:\s+(?:via|by|in|through|for|against)\b|$)", low)
        if cust and not ents.invoice_number:
            name = _clean(cust.group(1))
            if name not in {"payment", "customer", "record"}:
                ents.customer_query = name
        ok = ents.amount is not None and (ents.customer_query or ents.invoice_number)
        return ParsedIntent(intent="payment_record", entities=ents, confidence=0.8 if ok else 0.4)

    # ---------------------------------------------------------------- khata
    if re.search(r"\b(khata|udhar|udhaar|owe|owes|balance|outstanding|dues?|baki|baaki|hisaab|hisab)\b", low):
        cust = (re.match(r"^(.+?)\s+(?:ka|ki|ke)\s+(?:khata|hisaab|hisab|udhar|udhaar|baki|baaki)\b", low)
                or re.search(r"\b(?:khata|balance|dues?|outstanding|udhar|udhaar|baki)\s+(?:of|for)\s+(.+)$", low)
                or re.match(r"^(?:how much does |how much )?(.+?)(?:'s)?\s+(?:owe|owes|khata|balance|dues?|udhar|baki)",
                            low)
                or re.search(r"\b(?:does|do)\s+(.+?)\s+owe", low))
        if cust:
            name = re.sub(r"^(show|what is|what's|check|get)\s+", "", _clean(cust.group(1)))
            ents.customer_query = name or None
        ents.report = None if ents.customer_query else "khata"
        return ParsedIntent(intent="khata_lookup", entities=ents, confidence=0.8 if ents.customer_query else 0.6)

    # ---------------------------------------------------------------- reports
    if re.search(r"\b(low stock|running low|reorder|low on stock|stock low|stock kam|kam hai|what'?s low)\b", low):
        ents.report = "low_stock"
        return ParsedIntent(intent="report_summary", entities=ents, confidence=0.85)
    if re.search(r"\b(out of stock|stock ?out|khatam)\b", low):
        ents.report = "out_of_stock"
        return ParsedIntent(intent="report_summary", entities=ents, confidence=0.85)
    if re.search(r"\b(top|best|best-selling|best selling|most sold|popular)\b", low):
        ents.report, ents.period = "top_products", _period(low) or "last_30_days"
        ents.metric = ("quantity" if re.search(r"\b(units?|quantity|qty|most sold)\b", low)
                       else "invoice_count" if re.search(r"\b(invoices?|bills?|orders?)\b", low) else "revenue")
        return ParsedIntent(intent="report_summary", entities=ents, confidence=0.8)
    if re.search(r"\b(sales|sale|revenue|kamai|bikri|report|summary|how much did we sell)\b", low):
        ents.report, ents.period = "sales", _period(low) or "today"
        return ParsedIntent(intent="report_summary", entities=ents, confidence=0.8)

    # ---------------------------------------------------------------- product lookup
    lookup = r"^(?:find|search|show|lookup|look up|check|get)\s+(?:product\s+|item\s+|stock\s+(?:of\s+)?)?(.+)$"
    m = re.match(lookup, low) \
        or re.match(r"^(?:stock|price|rate|quantity)\s+(?:of|for)\s+(.+)$", low) \
        or re.match(r"^how many\s+(.+?)(?:\s+(?:do we have|left|in stock|are there))?\??$", low) \
        or re.match(r"^do we have\s+(?:any\s+)?(.+?)\??$", low) \
        or re.match(r"^how much\s+(.+?)\s+(?:is\s+)?(?:left|remaining|in stock|bacha|bache)\??$", low) \
        or re.match(r"^(.+?)\s+kitn[aei]\s+(?:hai|bacha|bache|bachi|stock)\??$", low)
    if m:
        ents.product_query = _clean(m.group(1))
        return ParsedIntent(intent="product_lookup", entities=ents, confidence=0.75)

    return ParsedIntent(intent="unknown", entities=ents, confidence=0.0)
