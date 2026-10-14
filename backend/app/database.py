import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/autograde").strip()

# Render & Heroku provide URLs starting with postgres://, which SQLAlchemy 1.4+ rejects
# Normalize postgres dialect to explicitly use psycopg2 (psycopg2-binary) or psycopg (v3)
normalized_url = DATABASE_URL
if DATABASE_URL.startswith("postgres://"):
    normalized_url = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1)
elif DATABASE_URL.startswith("postgresql://") and not DATABASE_URL.startswith("postgresql+"):
    normalized_url = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

# Create engine with graceful fallback if PostgreSQL server isn't running
try:
    if normalized_url.startswith("postgresql"):
        engine = create_engine(normalized_url, pool_pre_ping=True, pool_recycle=300)
        # Test connection
        with engine.connect() as conn:
            pass
    elif normalized_url.startswith("sqlite"):
        engine = create_engine(normalized_url, connect_args={"check_same_thread": False, "timeout": 30})
    else:
        engine = create_engine(normalized_url)
except Exception as e:
    # If psycopg2 driver fails, try standard postgresql:// in case psycopg v3 is present
    fallback_success = False
    if "psycopg2" in normalized_url:
        try:
            alt_url = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1) if DATABASE_URL.startswith("postgres://") else DATABASE_URL
            engine = create_engine(alt_url, pool_pre_ping=True, pool_recycle=300)
            with engine.connect() as conn:
                fallback_success = True
        except Exception:
            pass

    if not fallback_success:
        print(f"[Database Warning] Could not connect to PostgreSQL ({e}). Falling back to local SQLite database.")
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "autograde_dev.db")
        FALLBACK_URL = f"sqlite:///{db_path}"
        engine = create_engine(FALLBACK_URL, connect_args={"check_same_thread": False, "timeout": 30})

from sqlalchemy import event

# Only apply SQLite PRAGMAs if running on SQLite
if engine.dialect.name == "sqlite":
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()
        except Exception:
            pass

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
