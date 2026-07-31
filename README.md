# AutoGrade+

**AutoGrade+** is an AI-powered automated grading platform designed to assist instructors through interactive grading dashboards, automated rubric evaluation, human-in-the-loop audit safeguards, and statistical reliability benchmarking.

---

## Directory Structure

```
AutoGrade+ /
├── frontend/                     # React + Vite UI Application
│   ├── public/
│   ├── src/
│   │   ├── components/           # UI Components (Dashboard, SubmissionReview, Header)
│   │   ├── context/              # React Context (Assignment state & mock data)
│   │   └── pages/                # Page layouts
│   ├── package.json
│   └── vite.config.js
│
├── backend/                      # Backend Service (Specifications & API endpoints)
│   └── README.md
│
├── ai-pipeline/                  # Prompt Engineering & Data Generation
│   ├── prompts.py                # Prompt strategies (Chain-of-Thought, Rubric-based)
│   ├── generate_mock_data.py     # Script to generate frontend mock dataset
│   └── README.md
│
├── evaluation/                   # Evaluation Benchmark & Statistical Analysis
│   ├── evaluate_prompts.py       # LLM grading benchmarking runner script
│   ├── Dataset for prompt.xlsx   # Question, rubric, and human response dataset
│   ├── raw_grading_results.csv   # Raw grade comparisons
│   ├── icc_summary_results.csv   # Intraclass Correlation Coefficient (ICC) report
│   └── requirements.txt          # Python evaluation dependencies
│
├── docs/                         # Documentation
│   ├── architecture.md           # System architecture overview
│   └── user_workflow.md          # Human-in-the-loop workflow
│
├── package.json                  # Root monorepo runner scripts
└── README.md                     # Project overview
```

---

## Quick Start

### 1. Frontend Development

Run the React development server from the root directory:

```bash
npm run dev
```

Or navigate to `frontend/`:

```bash
cd frontend
npm install
npm run dev
```

Open your browser at `http://localhost:5173`.

---

### 2. AI Pipeline & Mock Data Generation

To regenerate the mock dataset for the frontend:

```bash
npm run generate-mock
# OR
python3 ai-pipeline/generate_mock_data.py
```

---

### 3. Running Prompt Benchmarking & Evaluation

Install Python evaluation dependencies:

```bash
pip install -r evaluation/requirements.txt
```

Ensure your `.env` file in `evaluation/` contains your API key:
```env
OPENROUTER_API_KEY=your_api_key_here
```

Run the prompt evaluation pipeline:

```bash
npm run evaluate
# OR
python3 evaluation/evaluate_prompts.py
```

---

## Key Features

- **Lecturer Dashboard:** Class-wide score distributions and average marks per question.
- **Human-in-the-Loop Safeguards:** Flags for *Borderline Grades*, *Auditor Conflicts*, *Random Audits*, and *Low Confidence*.
- **Detailed Grading Review:** Side-by-side rubric comparison, AI reasoning highlights, and lecturer manual grade overrides.
- **Rater Reliability Analysis:** Intraclass Correlation Coefficient (ICC) calculation comparing LLM grades against human instructor evaluations.
