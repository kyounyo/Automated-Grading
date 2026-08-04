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
    else:
        engine = create_engine(DATABASE_URL)
except Exception as e:
    print(f"[Database Warning] Could not connect to PostgreSQL ({e}). Falling back to local SQLite database.")
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "autograde_dev.db")
    FALLBACK_URL = f"sqlite:///{db_path}"
    engine = create_engine(FALLBACK_URL, connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
