from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from .database import engine, Base
from .routes import assignments, submissions, uploads

# Auto-create database tables on startup
try:
    Base.metadata.create_all(bind=engine)
    print("[Database Success] PostgreSQL database tables initialized.")
except Exception as e:
    print(f"[Database Error] Table initialization: {e}")

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
