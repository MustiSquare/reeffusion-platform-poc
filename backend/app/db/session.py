from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.core.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

class Base(DeclarativeBase):
    pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    try:
        from alembic import command
        from alembic.config import Config

        backend_root = Path(__file__).resolve().parents[2]
        alembic_cfg = Config(str(backend_root / "alembic.ini"))
        alembic_cfg.set_main_option("script_location", str(backend_root / "alembic"))
        alembic_cfg.set_main_option("sqlalchemy.url", settings.database_url)
        command.upgrade(alembic_cfg, "head")
    except ImportError:
        from app.models import tables  # noqa
        Base.metadata.create_all(bind=engine)
