"""Role -> permission map. The backend is the only authority; the frontend mirrors it for navigation."""

from enum import StrEnum

from app.enums import Role


class P(StrEnum):
    shop_settings = "shop.settings"
    users_manage = "users.manage"
    tax_reports = "reports.tax"  # GST, profit/COGS, inventory valuation at cost
    reports_view = "reports.view"
    dashboard_view = "dashboard.view"
    products_read = "products.read"
    products_write = "products.write"
    inventory_read = "inventory.read"
    inventory_adjust = "inventory.adjust"
    invoices_create = "invoices.create"
    invoices_read_all = "invoices.read_all"
    credit_notes_create = "credit_notes.create"
    payments_record = "payments.record"
    customers_read = "customers.read"
    customers_write = "customers.write"
    khata_read = "khata.read"
    suppliers_read = "suppliers.read"
    suppliers_write = "suppliers.write"
    po_manage = "purchase_orders.manage"
    po_receive = "purchase_orders.receive"
    ai_use = "ai.use"


_STAFF = {
    P.products_read,
    P.inventory_read,
    P.inventory_adjust,
    P.invoices_create,
    P.payments_record,
    P.customers_read,
    P.khata_read,
    P.po_receive,
    P.suppliers_read,
    P.ai_use,
}

_MANAGER = _STAFF | {
    P.dashboard_view,
    P.reports_view,
    P.products_write,
    P.invoices_read_all,
    P.credit_notes_create,
    P.customers_write,
    P.suppliers_write,
    P.po_manage,
}

ROLE_PERMISSIONS: dict[Role, frozenset[P]] = {
    Role.owner: frozenset(P),
    Role.manager: frozenset(_MANAGER),
    Role.staff: frozenset(_STAFF),
}


def has_permission(role: Role, perm: P) -> bool:
    return perm in ROLE_PERMISSIONS[role]
