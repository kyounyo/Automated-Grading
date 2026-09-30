import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/autograde")

# Create engine with graceful fallback if PostgreSQL local server isn't running
try:
    if DATABASE_URL.startswith("postgresql"):
        engine = create_engine(DATABASE_URL, pool_pre_ping=True)
        # Test connection
        with engine.connect() as conn:
            pass
    elif DATABASE_URL.startswith("sqlite"):
        engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False, "timeout": 30})
    else:
        engine = create_engine(DATABASE_URL)
except Exception as e:
    print(f"[Database Warning] Could not connect to PostgreSQL ({e}). Falling back to local SQLite database.")
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "autograde_dev.db")
    FALLBACK_URL = f"sqlite:///{db_path}"
    engine = create_engine(FALLBACK_URL, connect_args={"check_same_thread": False, "timeout": 30})

from sqlalchemy import event

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
