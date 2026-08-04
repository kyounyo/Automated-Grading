#!/usr/bin/env python3
import os
import shutil
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

# Wipe ChromaDB vector store directory
chroma_dir = os.path.join(os.path.dirname(__file__), "chroma_db")
if os.path.exists(chroma_dir):
    try:
        shutil.rmtree(chroma_dir)
        os.makedirs(chroma_dir, exist_ok=True)
        print("✓ All ChromaDB vector collections cleared!")
    except Exception as e:
        print(f"Warning clearing ChromaDB: {e}")

print("[Reset Complete] Database is now 100% empty!")
