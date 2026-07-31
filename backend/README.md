# AutoGrade+ Backend Service

## Overview
The `backend/` directory is designated for the server-side API services of AutoGrade+. The backend connects the React frontend with the AI grading pipeline and database persistence.

## Expected API Endpoints

### 1. Assignments
- `GET /api/assignments` - List all active assignments and summaries.
- `GET /api/assignments/:id` - Fetch detailed metrics, score distribution, and student submission status for a specific assignment.
- `POST /api/assignments` - Create a new assignment with rubric and model answers.

### 2. Submissions & AI Grading
- `GET /api/assignments/:id/submissions` - Retrieve student submissions and AI evaluation status.
- `POST /api/submissions/grade` - Submit student responses to the AI grading engine for evaluation.
- `PATCH /api/submissions/:id/override` - Update score and justification when a lecturer manually overrides an AI grade.

### 3. Auditing & Quality Assurance
- `GET /api/audits/flagged` - List submissions flagged for human review (Borderline Grade, Auditor Conflict, Random Audit, Low Confidence).

## Target Tech Stack
- **Framework:** Node.js (Express / Fastify) or Python (FastAPI)
- **Database:** PostgreSQL / SQLite (for storing assignments, rubrics, submissions, and audit trails)
- **ORM / Query Builder:** Prisma or SQLAlchemy
