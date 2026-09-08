"""scripts/bootstrap_db.py — run at container start (Dockerfile CMD), before
`uvicorn`, so the deployed API's schema is always current.

`alembic upgrade head` is normally a safe no-op once the database is
current. It is NOT safe here on a first boot against the pre-existing
production database: that database was provisioned before the T1.2
architecture rebuild (documents-not-facts corpus) and both its
`alembic_version` table and its tables themselves belong to the OLD
migration chain (`migrations/versions/` history that predates this rebuild
and was deleted, not merely superseded — see docs/TASKS.md's T1.2 entry).
Two of the old table names collide with current ones (`sources` happens to
be schema-compatible; `models` and `service_centres` are not — the old
`models` table has `brand_id`/`body_type` columns this repo's `Model` never
had), so even resetting just `alembic_version` and replaying this repo's one
migration fails with "relation already exists".

T1.2 already made the call that the old schema is abandoned, not migrated
forward — this script just applies that same call to the database:
`alembic upgrade head` is tried first (a no-op on every boot after the
first), and only on failure does it drop and recreate the `public` schema
entirely before retrying. This is safe specifically because the old data
behind that schema is pre-pivot demo content with no ongoing value, not
because dropping a schema is generally a safe recovery step — do not copy
this pattern onto a database that holds anything worth keeping.
"""

from __future__ import annotations

import subprocess
import sys

from sqlalchemy import create_engine, text

from api.settings import settings


def _alembic_upgrade() -> int:
    return subprocess.run(["alembic", "upgrade", "head"]).returncode


def main() -> None:
    if _alembic_upgrade() == 0:
        return

    print(
        "bootstrap_db: alembic upgrade head failed — assuming this is the "
        "pre-T1.2 architecture's orphaned schema and resetting it rather "
        "than trying to migrate through it (see this script's module "
        "docstring).",
        file=sys.stderr,
    )
    engine = create_engine(settings.database_url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))

    sys.exit(_alembic_upgrade())


if __name__ == "__main__":
    main()
