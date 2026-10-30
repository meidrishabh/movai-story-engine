"""Apply the SQL files in backend/db in order and remember which ones ran.

    python -m app.migrate              apply every file not yet recorded
    python -m app.migrate --baseline   record every file as applied without running it (for a database that
                                       was migrated by hand before this tracking existed)
    python -m app.migrate --status     list applied and pending files
"""
import sys
from pathlib import Path

from sqlalchemy import text

from app.db import SessionLocal

MIGRATIONS = Path(__file__).resolve().parents[1] / "db"


def _files() -> list[Path]:
    return sorted(p for p in MIGRATIONS.glob("*.sql") if p.stem[:3].isdigit())


def main(argv: list[str]) -> int:
    db = SessionLocal()
    db.execute(text("CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"))
    db.commit()
    applied = {row[0] for row in db.execute(text("SELECT name FROM schema_migrations"))}
    pending = [p for p in _files() if p.name not in applied]

    if "--status" in argv:
        print("applied:", ", ".join(sorted(applied)) or "none")
        print("pending:", ", ".join(p.name for p in pending) or "none")
        return 0
    for path in pending:
        if "--baseline" not in argv:
            db.execute(text(path.read_text(encoding="utf-8")))
        db.execute(text("INSERT INTO schema_migrations (name) VALUES (:n)"), {"n": path.name})
        db.commit()
        print(("recorded " if "--baseline" in argv else "applied ") + path.name)
    if not pending:
        print("nothing to apply")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
