# AutoGrade+

**AutoGrade+** is an enterprise-grade, AI-powered automated grading platform designed for university courses. It combines **RAG-augmented vector similarity retrieval (ChromaDB)**, **Gemini 2.5 Flash LLM Chain-of-Thought evaluation**, **Human-in-the-Loop audit safeguards**, and **statistical reliability benchmarking**.

---

## 🌟 Key System Features

- **RAG Vector Database (ChromaDB)**: Embeds self-contained question vectors (`question_id`, `max_score`, `Question Prompt`, and `Marking Criteria & Model Answer`) for targeted semantic retrieval.
- **Multi-Format Rubric & Submission Parser**: Parses `.xlsx`, `.csv`, `.docx`, and `.pdf` files. Automatically groups student responses by `Student_ID` across questions.
- **Database Upsert & Batch Tracking**: Enforces strict database uniqueness `(student_id, assignment_id)` to prevent duplicates on re-uploads, and assigns a `batch_id` to trace upload batches.
- **Granular AI Pipeline Statuses**:
  `uploaded` → `extracting_answers` → `retrieving_rubric` → `grading` → `graded` / `flagged`
- **Human-in-the-Loop Audit & Override**: Flags low-confidence evaluations for lecturer review. Records all manual score overrides in PostgreSQL `AuditLog` and `EvaluationLog` benchmarking tables.
- **Extracted Content Verification View**: Frontend visualization allowing instructors to verify raw extracted student text responses.

---

## 📁 Repository Directory Structure

```
AutoGrade+ /
├── frontend/                     # React + Vite UI Application
│   ├── src/
│   │   ├── components/           # UI Components (Navigation, Header, Layout)
│   │   ├── context/              # React Context (Assignment & Submissions state)
│   │   ├── pages/                # Pages (Dashboard, AssignmentCreator, BulkUpload, SubmissionsList, GradingReview)
│   │   └── api/                  # Axios REST API client
│   ├── package.json
│   └── vite.config.js
│
├── backend/                      # FastAPI Python Service
│   ├── app/
│   │   ├── routes/               # API Endpoints (assignments.py, uploads.py, submissions.py)
│   │   ├── services/             # Core Logic (embedding.py, grading.py, document_parser.py, storage.py)
│   │   ├── models.py             # SQLAlchemy ORM Models (Assignment, Submission, AuditLog, EvaluationLog)
│   │   ├── schemas.py            # Pydantic Schemas
│   │   └── database.py           # PostgreSQL / SQLite Engine connection
│   ├── chroma_db/                # ChromaDB Persistent Vector Store
│   ├── uploads/                  # Local storage fallback for student submissions
│   ├── reset_db.py               # Database table & vector store wipe helper
│   ├── requirements.txt
│   └── venv/
│
├── ai-pipeline/                  # Data Generation & Prompts
│   └── generate_mock_data.py     # Script to generate mock datasets
│
├── evaluation/                   # Rater Reliability & ICC Benchmarking
│   ├── evaluate_prompts.py       # Prompt evaluation benchmark script
│   └── raw_grading_results.csv
│
├── package.json                  # Root runner scripts
└── README.md                     # Project overview
```

---

## ⚡ Quick Start

### 1. Prerequisites
- **Node.js**: v18+ 
- **Python**: v3.10+
- **npm**: v9+

### 2. Environment Setup

Copy `.env.example` to `.env` in `backend/` and `evaluation/`:

```env
OPENROUTER_API_KEY=your_api_key_here
LLM_MODEL=google/gemini-2.5-flash
PROMPT_VERSION=v1.2-rubric-cot
```

---

### 3. Running the Application

#### Option A: Running Full Stack (Backend + Frontend)

From the root directory, run:

```bash
npm start
```

#### Option B: Running Services Separately

1. **Start FastAPI Backend Server**:
   ```bash
   npm run backend:dev
   # OR
   cd backend && venv/bin/uvicorn app.main:app --reload --port 8000
   ```
   API Docs available at: `http://localhost:8000/docs`

2. **Start React Frontend Server**:
   ```bash
   npm run dev
   # OR
   cd frontend && npm run dev
   ```
   Frontend Application available at: `http://localhost:5173`

---

## 📊 Dataset Templates & CSV Formats

### 1. Rubric Excel / CSV Format (`question_n,question,answer,max_mark`)
```csv
question_n,question,answer,max_mark
6,"(a) Polymer microspheres advantages & disadvantages (5 marks)...","(a) Advantages: May be biodegradable (+1). Disadvantages: Complex manufacture (+1)...",10
8,"Consider the five statements... (a) Lyophilization (b) Protein structure...","(a) Disagree: Not necessary if stable in solution (+1)...",10
```

### 2. Student Submissions CSV Format (`Student_ID,question_no,Response`)
```csv
Student_ID,question_no,Response
30720842,6,"-"
30881447,6,"(a) Advantages: May be biodegradable - do not need removal. Reduces administration frequency..."
30883350,6,"(a) Advantages: Reduces administration frequency. Injectable system no surgery required..."
30720842,8,"(a) Disagree: Lyophilization is not necessary if drug is stable in solution..."
```

---

## 🛠️ Management Commands

### Reset Database & Vector Stores
Wipes all database records, drops/recreates schema tables, and clears ChromaDB vector collections:

```bash
npm run reset-db
```

### Delete Submissions via API
- **Delete Single Submission**: `DELETE http://localhost:8000/api/submissions/{submission_id}`
- **Delete All Submissions for Assignment**: `DELETE http://localhost:8000/api/assignments/{assignment_id}/submissions`
