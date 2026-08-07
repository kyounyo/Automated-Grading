import os
import sys
import shutil

# Ensure backend directory is in Python path for Windows/Mac cross-platform execution
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import engine, Base, SessionLocal
from app.models import Assignment, Submission, AuditLog, EvaluationLog

print("[Resetting Database] Clearing all assignments, submissions, and ChromaDB vector stores...")

db = SessionLocal()
try:
    db.query(AuditLog).delete()
    db.query(EvaluationLog).delete()
    db.query(Submission).delete()
    db.query(Assignment).delete()
    db.commit()
    print("✓ All database table records deleted!")
finally:
    db.close()

# Drop and recreate all tables for schema migrations (e.g. new columns)
try:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    print("✓ Database table schemas updated successfully!")
except Exception as e:
    print(f"[Schema Migration Warning] {e}")

# Clear ChromaDB vector stores gracefully via API without breaking active file locks
try:
    from app.services.embedding import embedding_service
    client = embedding_service._get_client()
    collections = client.list_collections()
    for col in collections:
        col_name = col.name if hasattr(col, 'name') else str(col)
        client.delete_collection(col_name)
    print("✓ All ChromaDB vector collections cleared!")
except Exception as e:
    chroma_dir = os.path.join(os.path.dirname(__file__), "chroma_db")
    if os.path.exists(chroma_dir):
        try:
            shutil.rmtree(chroma_dir)
            os.makedirs(chroma_dir, exist_ok=True)
            print("✓ All ChromaDB vector collections cleared!")
        except Exception as err:
            print(f"Warning clearing ChromaDB: {err}")

print("[Reset Complete] Database is now 100% empty!")
