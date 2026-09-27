import enum


class Role(enum.StrEnum):
    owner = "owner"
    manager = "manager"
    staff = "staff"


class MovementType(enum.StrEnum):
    opening = "opening"
    purchase_receipt = "purchase_receipt"
    sale = "sale"
    return_ = "return"
    manual_increase = "manual_increase"
    manual_decrease = "manual_decrease"
    damage = "damage"
    correction = "correction"


class InvoiceStatus(enum.StrEnum):
    draft = "draft"
    posted = "posted"
    cancelled = "cancelled"


class PaymentStatus(enum.StrEnum):
    unpaid = "unpaid"
    partial = "partial"
    paid = "paid"


class PaymentMethod(enum.StrEnum):
    cash = "cash"
    upi = "upi"
    card = "card"
    bank_transfer = "bank_transfer"
    # "credit" is never a money receipt: it is the portion of an invoice deferred to the customer's khata.
    credit = "credit"


class PaymentKind(enum.StrEnum):
    receipt = "receipt"
    refund = "refund"


class LedgerEntryType(enum.StrEnum):
    invoice = "invoice"
    payment = "payment"
    credit_note = "credit_note"
    refund = "refund"


class POStatus(enum.StrEnum):
    draft = "draft"
    sent = "sent"
    partial = "partial"
    received = "received"
    cancelled = "cancelled"


class SupplyType(enum.StrEnum):
    intra_state = "intra_state"
    inter_state = "inter_state"
