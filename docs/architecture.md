# AutoGrade+ System Architecture

## Architecture Overview

AutoGrade+ is an AI-assisted automated grading platform designed with a **Human-in-the-Loop (HITL)** architecture. It ensures high grading accuracy, transparency, and instructor control through real-time metrics, automated flagging, and statistical agreement verification.

```
                  +-----------------------------------+
                  |         Lecturer Interface        |
                  |     (frontend/ - React + Vite)    |
                  +-----------------+-----------------+
                                    |
                                    v
                  +-----------------+-----------------+
                  |         Backend API Service       |
                  |       (backend/ - REST / GraphQL) |
                  +--------+----------------+---------+
                           |                |
             +-------------+                +-------------+
             |                                            |
             v                                            v
+------------+--------------------+        +--------------+-------------------+
|         AI Pipeline             |        |        Evaluation Suite          |
|  (ai-pipeline/ - Prompt Engine) |        |  (evaluation/ - ICC Benchmarking) |
+---------------------------------+        +----------------------------------+
```

## System Components

### 1. Frontend (`frontend/`)
- Built with **React** (Vite) and **Vanilla CSS**.
- Provides interactive visual dashboards (Mark distribution charts, average marks per question).
- Implements targeted text highlighting for AI reasoning and side-by-side rubric comparison.
- Supports manual grade overrides and review workflow for flagged submissions.

### 2. Backend Service (`backend/`)
- Handles authentication, assignment management, submission storage, and audit logs.
- Dispatches evaluation tasks to the AI pipeline and exposes APIs for the frontend UI.

### 3. AI Pipeline (`ai-pipeline/`)
- Implements prompt templates (Chain-of-Thought, Rubric-driven).
- Formats structured JSON outputs (score, reasoning, text highlights, confidence level).
- Provides mock context generators for frontend development.

### 4. Evaluation & Verification Suite (`evaluation/`)
- Evaluates LLM grading performance against human-graded benchmark datasets.
- Calculates **Intraclass Correlation Coefficients (ICC)** to measure rater reliability.
- Exports granular JSON logs and statistical summary reports.
