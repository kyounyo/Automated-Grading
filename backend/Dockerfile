# AutoGrade+ backend (FastAPI + ChromaDB)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install Python dependencies first so this layer is cached between code changes
COPY requirements-docker.txt .
RUN pip install -r requirements-docker.txt

# Download ChromaDB's default embedding model at build time,
# so the first assignment upload doesn't stall waiting for it
RUN python -c "from chromadb.utils.embedding_functions import DefaultEmbeddingFunction as E; E()(['warm up'])"

# Application code and maintenance scripts
COPY app ./app
COPY reset_db.py seed_db.py delete_assignment.py ./

# Persistent data locations (mounted as Docker volumes by docker-compose.yml)
#   /app/data       SQLite database
#   /app/chroma_db  ChromaDB vector store
#   /app/uploads    uploaded rubrics and student submissions
RUN mkdir -p /app/data /app/chroma_db /app/uploads

ENV DATABASE_URL=sqlite:////app/data/autograde.db

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/', timeout=4)" || exit 1

# Single worker: grading runs as in-process background tasks
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
