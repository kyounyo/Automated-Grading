import sys
import logging
from pathlib import Path
from dotenv import load_dotenv

# Ensure terminal stdout and stderr flush immediately without buffering delay
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(line_buffering=True)

# Ensure backend .env is loaded regardless of execution working directory
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=_env_path, override=True)
load_dotenv(override=True)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .database import engine, Base
from . import models
from .routes import assignments, submissions, uploads
from sqlalchemy import inspect, text

# Suppress repetitive background polling GET requests from cluttering the backend terminal
class PollingAccessLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if "GET" in msg and any(ep in msg for ep in ["/submissions", "/grading-status"]):
            return False
        return True

logging.getLogger("uvicorn.access").addFilter(PollingAccessLogFilter())

# Auto-create database tables on startup & ensure schema columns exist
try:
    Base.metadata.create_all(bind=engine)
    with engine.connect() as conn:
        insp = inspect(engine)
        if 'assignments' in insp.get_table_names():
            cols = [c['name'] for c in insp.get_columns('assignments')]
            if 'calibration_enabled' not in cols:
                conn.execute(text('ALTER TABLE assignments ADD COLUMN calibration_enabled BOOLEAN DEFAULT 0'))
            if 'calibration_sample_size' not in cols:
                conn.execute(text('ALTER TABLE assignments ADD COLUMN calibration_sample_size INTEGER DEFAULT 3'))
            if 'calibration_settings' not in cols:
                conn.execute(text('ALTER TABLE assignments ADD COLUMN calibration_settings JSON'))
            if 'tolerance_rate' not in cols:
                conn.execute(text('ALTER TABLE assignments ADD COLUMN tolerance_rate FLOAT DEFAULT 0.10'))
            if 'grading_started_at' not in cols:
                conn.execute(text('ALTER TABLE assignments ADD COLUMN grading_started_at TIMESTAMP'))
        if 'submissions' in insp.get_table_names():
            sub_cols = [c['name'] for c in insp.get_columns('submissions')]
            if 'is_calibration_sample' not in sub_cols:
                conn.execute(text('ALTER TABLE submissions ADD COLUMN is_calibration_sample BOOLEAN DEFAULT 0'))
            
            # Startup Self-Healing: Reset any stuck in-progress submissions left by previous server crashes/restarts
            conn.execute(text("""
                UPDATE submissions 
                SET status = CASE 
                    WHEN score IS NOT NULL AND feedback LIKE '%flag_reasons%' AND feedback NOT LIKE '%"flag_reasons": []%' THEN 'flagged'
                    WHEN score IS NOT NULL THEN 'graded'
                    ELSE 'pending'
                END
                WHERE status IN ('processing', 'extracting_answers', 'retrieving_rubric', 'grading')
            """))
        if 'evaluation_logs' in insp.get_table_names():
            eval_cols = [c['name'] for c in insp.get_columns('evaluation_logs')]
            if 'assignment_id' not in eval_cols:
                conn.execute(text('ALTER TABLE evaluation_logs ADD COLUMN assignment_id VARCHAR'))
            if 'question_number' not in eval_cols:
                conn.execute(text('ALTER TABLE evaluation_logs ADD COLUMN question_number VARCHAR'))
            if 'grading_mode' not in eval_cols:
                conn.execute(text('ALTER TABLE evaluation_logs ADD COLUMN grading_mode VARCHAR'))
            if 'calibration_version' not in eval_cols:
                conn.execute(text('ALTER TABLE evaluation_logs ADD COLUMN calibration_version INTEGER'))
            if 'calibration_examples_count' not in eval_cols:
                conn.execute(text('ALTER TABLE evaluation_logs ADD COLUMN calibration_examples_count INTEGER'))
        conn.commit()
    print("[Database Success] Database tables & schema verified. Self-healed orphaned statuses.", flush=True)
except Exception as e:
    print(f"[Database Error] Table initialization/migration: {e}", flush=True)

app = FastAPI(
    title="AutoGrade+ API Service",
    description="Backend API Service for AI-Assisted Automated Grading Platform",
    version="2.0.0"
)

# CORS Configuration allowing React UI requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows local Vite dev server http://localhost:5173
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static uploads directory for local file serving fallback
UPLOADS_DIR = Path(__file__).resolve().parent.parent / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")

# Mount API Routers
app.include_router(assignments.router)
app.include_router(submissions.router)
app.include_router(uploads.router)


@app.get("/")
def root():
    return {
        "service": "AutoGrade+ Backend Service",
        "status": "online",
        "docs": "/docs",
        "version": "2.0.0"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
