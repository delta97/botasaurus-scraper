"""SQLite via SQLAlchemy. WAL mode so agent worker threads can write while
the API serves reads. Schema is managed with create_all plus a tiny
PRAGMA user_version migration hook (no Alembic)."""
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from . import config
from .models import Base, Run, utcnow

SCHEMA_VERSION = 3

engine = None
SessionLocal = None


def _make_engine(db_path):
    eng = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(eng, "connect")
    def _set_pragmas(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return eng


def init_db(db_path=None):
    """Create engine + tables. Safe to call repeatedly (tests use tmp paths)."""
    global engine, SessionLocal
    config.ensure_dirs()
    engine = _make_engine(db_path or config.DB_PATH)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    _migrate()
    return SessionLocal


def _migrate():
    with engine.begin() as conn:
        version = conn.execute(text("PRAGMA user_version")).scalar()
        # create_all (called before this) adds brand-new tables; ALTERs below add
        # columns to existing tables. SQLite has no ADD COLUMN IF NOT EXISTS, so
        # each ALTER is guarded by PRAGMA table_info to stay idempotent.
        if version < 2:
            cols = {row[1] for row in conn.execute(text("PRAGMA table_info(recipes)"))}
            if "self_heal" not in cols:
                conn.execute(text("ALTER TABLE recipes ADD COLUMN self_heal INTEGER DEFAULT 0"))
            if "heal_mode" not in cols:
                conn.execute(text("ALTER TABLE recipes ADD COLUMN heal_mode TEXT DEFAULT 'propose'"))
        if version < 3:
            cols = {row[1] for row in conn.execute(text("PRAGMA table_info(runs)"))}
            if "suite_run_id" not in cols:
                conn.execute(text("ALTER TABLE runs ADD COLUMN suite_run_id INTEGER"))
        if version < SCHEMA_VERSION:
            conn.execute(text(f"PRAGMA user_version = {SCHEMA_VERSION}"))


def fail_orphaned_runs():
    """Runs left 'running'/'queued' by a previous process can never finish."""
    with SessionLocal() as session:
        orphans = (
            session.query(Run).filter(Run.status.in_(["running", "queued"])).all()
        )
        for run in orphans:
            run.status = "failed"
            run.error = "server restarted while run was in progress"
            run.finished_at = utcnow()
        session.commit()
        return len(orphans)


def get_session():
    """FastAPI dependency."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
