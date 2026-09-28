"""Wipe a database and reload the demo shop, e.g. after rehearsals and before the real demo.

Usage (from backend/):
    MSME_DATABASE_URL=<external URL of the database> MSME_DEMO_PASSWORD=<demo password> \\
        python -m scripts.reset_demo --yes

Everything in the database is deleted, including shops registered during rehearsal. The demo shop is
reseeded with 60 days of history ending today. Set MSME_DEMO_PASSWORD to the same value the deployed app
uses, or the demo logins will get a different password.
"""

import os
import sys

from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url

from alembic import command
from app.config import get_settings
from app.db import engine
from scripts import seed


def main() -> None:
    target = make_url(get_settings().database_url)
    where = f"{target.host}:{target.port or 5432}/{target.database}"
    if "--yes" not in sys.argv:
        print(f"This deletes ALL data in {where} and reloads the demo shop.")
        print("Run again with --yes to confirm.")
        sys.exit(1)

    remote = target.host not in (None, "localhost", "127.0.0.1")
    if remote and len(os.environ.get("MSME_DEMO_PASSWORD", "").strip()) < 8:
        # Otherwise the seed falls back to its weak development password on a public database.
        print("Set MSME_DEMO_PASSWORD (8+ characters, same as the deployed app) before resetting a remote database.")
        sys.exit(1)

    print(f"Resetting {where} ...")
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()

    command.upgrade(Config("alembic.ini"), "head")
    seed.main()
    print("Done. The demo shop is fresh.")


if __name__ == "__main__":
    main()
