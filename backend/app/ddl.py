"""Database-level guards that complement service-layer rules.

These run in the initial Alembic migration and when tests build the schema with ``create_all``.
"""

from sqlalchemy import DDL, event

from app.db import Base

APPEND_ONLY_FN = """
CREATE OR REPLACE FUNCTION forbid_mutation() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION '% rows are immutable', TG_TABLE_NAME USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;
"""

POSTED_INVOICE_ITEMS_FN = """
CREATE OR REPLACE FUNCTION forbid_posted_invoice_item_change() RETURNS trigger AS $$
DECLARE inv_status text;
BEGIN
  SELECT status INTO inv_status FROM invoices WHERE id = COALESCE(OLD.invoice_id, NEW.invoice_id);
  IF inv_status IS NOT NULL AND inv_status <> 'draft' THEN
    RAISE EXCEPTION 'items of a posted invoice are immutable' USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

APPEND_ONLY_TABLES = ("stock_movements", "ledger_entries", "payments", "credit_notes", "credit_note_items")


def trigger_statements() -> list[str]:
    stmts = [APPEND_ONLY_FN, POSTED_INVOICE_ITEMS_FN]
    for table in APPEND_ONLY_TABLES:
        stmts.append(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION forbid_mutation();"
        )
    stmts.append(
        "CREATE TRIGGER invoice_items_posted_immutable BEFORE UPDATE OR DELETE ON invoice_items "
        "FOR EACH ROW EXECUTE FUNCTION forbid_posted_invoice_item_change();"
    )
    return stmts


def drop_statements() -> list[str]:
    stmts = [f"DROP TRIGGER IF EXISTS {t}_append_only ON {t};" for t in APPEND_ONLY_TABLES]
    stmts.append("DROP TRIGGER IF EXISTS invoice_items_posted_immutable ON invoice_items;")
    stmts.append("DROP FUNCTION IF EXISTS forbid_mutation();")
    stmts.append("DROP FUNCTION IF EXISTS forbid_posted_invoice_item_change();")
    return stmts


def install_create_all_hooks() -> None:
    """Attach trigger DDL to ``metadata.create_all`` (used by tests and local bootstrap)."""
    for stmt in trigger_statements():
        event.listen(Base.metadata, "after_create", DDL(stmt.replace("%", "%%")))
