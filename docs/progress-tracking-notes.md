# Methodology & Progress Tracking — Notes

**Prepared by:** Ching Ee Gwen · **For:** MDS17 Mid-Term Presentation · **Slide owner:** Ee Gwen (Methodology & Progress Tracking)
**As of:** 2 September 2026

**Methodology / caveat:** `gh` CLI was not available in this environment, so the actual GitHub Projects/Issues Kanban board (if one exists) could not be pulled directly. The "Kanban status" below is reconstructed from `git log --all`, branch divergence (`git log main..<branch>`), and direct inspection of the implementation files on each branch (`grading.py`, `confidence.py`, `rag.py`, `document_parser.py`, `icc_tracker.py`, the frontend pages). Cross-check against the team's real board if one exists.

**Branches inspected:** `main`, `AI-Evaluation`, `LLM`, `Doc-parser`, `PDF-parser`, `prompt-engineering-q6-q8`, `Q9-Test`.

---

## 1. Kanban Board Status (reconstructed from branches)

| Column | Item | Evidence / Owner |
|---|---|---|
| **Done** (merged to `main`) | Full-stack scaffold: React + FastAPI + PostgreSQL + AWS S3 + ChromaDB | Zoe (`kyounyo`) |
| Done | Multi-agent grading pipeline (Parser → Grader → Auditor) via OpenRouter | Zoe |
| Done | Deterministic confidence / decision engine (weighted formula, 15% discrepancy threshold) | Zoe |
| Done | ICC tracker — benchmarks AI marks vs. lecturer marks | Zoe |
| Done | Human-in-the-loop review UI: per-question override, final score override, approve/flag | Zoe |
| Done | Dashboard analytics: score distribution chart, class average, question breakdown | Zoe |
| **In Review** (open branch, not merged to `main`) | `AI-Evaluation`: UI polish, bulk-upload feedback, submission preview, flexible Excel rubric parser | Zoe — 2 commits ahead of `main`, unmerged |
| In Review | `Doc-parser`: rubric + question document splitting/pairing logic — latest commit message literally flagged **"(TBD)"** | Chi Shien |
| In Progress | `LLM` branch: Gemini / Claude / Nemotron model-role benchmarking (Retriever/Grader/Auditor combinations) | Ee Gwen — Phase B still running per project log (~$4.47 of $50 budget spent at last check) |
| In Progress | `prompt-engineering-q6-q8`: prompt tuning for Q6–Q8 — **uncommitted local changes** currently sitting in `llm_service.py`, `run_experiment_2_audit.py`, `run_experiment_suite.py` | Ee Gwen |
| In Progress | Open-ended Q22 prompt tuning | Qian Jun (not yet cleanly separable into its own branch/commit trail) |
| **Backlog / Not Started** | Authentication / access control (RTM NFR-04) | — |
| Backlog | Formal performance testing — 30 submissions in <10 min (RTM NFR-01) | — |
| Backlog | Deployment pipeline — no Dockerfile, CI/CD config, or cloud deploy script found anywhere in the repo | — |
| Backlog | Image-based assessment grading (explicitly Low priority / future extension in the proposal) | — |
| Backlog | Synthesizer as a distinct 4th agent — current pipeline has 3 agents (Retriever/Parser → Grader → Auditor); the Synthesizer's "consolidate & decide" role is folded into `confidence.py` instead of being a separate LangChain agent | — |

**Talking point:** `AI-Evaluation` (Zoe's latest frontend work) and `LLM` (the model-role research) are both real, visible "in progress" branches — not merged into `main` yet. Good concrete evidence for the "in progress" column.

---

## 2. Percentage of Work Completed — Calculation Logic

Two independent methods were run against the team's own proposal documents. They converge on the same number, which is a useful consistency check for the slide.

### Method A — RTM requirement coverage
```
% Complete = (Completed Requirements ÷ Total Requirements) × 100
```
Scored each of the 16 RTM items (FR-01→FR-10, NFR-01→NFR-06) against the actual code:

- **Completed (10):** FR-01, FR-02, FR-03, FR-05, FR-06, FR-07, FR-08, FR-09, FR-10, NFR-02
- **In progress (4):** FR-04 (multi-agent pipeline works, but built as direct OpenRouter orchestration rather than LangChain as specced, and multi-LLM role-optimisation is still running), NFR-01 (untested), NFR-05 (commit distribution is uneven across members — see §4), NFR-06 (partial error handling only)
- **Not started (2):** NFR-03 (no formal cross-browser test on record), NFR-04 (no authentication layer)

**10 / 16 = 62.5%** (or **(10 + 4×0.5) / 16 = 75%** giving half-credit for in-progress items)

### Method B — Milestone / iteration coverage (matches the Gantt chart)
```
% Complete = (Completed Milestones + 0.5 × In-Progress Milestones) ÷ Total Milestones × 100
```
- Milestone 1 (Iter 1 — requirements/architecture/model selection): **Completed**
- Milestone 2 (Iter 2 — core platform): **Completed**
- Milestone 3 (Iter 3 — end-to-end AI grading system): **In progress**
- Milestone 4 (Iter 4 — integration/deployment): **Not started**

**(2 + 0.5×1) / 4 = 62.5%**

### Result
Both methods land on **~62–63% complete**. This also matches where the Gantt chart says the team *should* be on 2 September 2026 (partway through Iteration 3, "Mid-August – September 2026") — i.e., the project is roughly on schedule.

---

## 3. Completed vs. Remaining Milestones

**Completed**
- **Milestone 1 — Requirements, architecture & grading model approved.** Literature review, requirements elicitation, system architecture, and Phase 1 LLM benchmarking (10-model ICC comparison table) all done and documented in the proposal.
- **Milestone 2 — Core platform validated.** AWS S3 + PostgreSQL + ChromaDB provisioned; React dashboard + FastAPI backend working; bulk upload, assignment creation, and submission management all functional in the codebase.

**In progress — Milestone 3 (target: stakeholder acceptance of the AI grading system)**
- ✅ Built: RAG retrieval, 3-agent grading pipeline, confidence/decision engine, ICC tracker, lecturer review + override UI, analytics dashboard.
- 🔄 Still open: `AI-Evaluation` and `Doc-parser` branches unmerged; model-role optimisation (`LLM` branch) unfinished; Q6/Q8/Q22 prompt tuning ongoing; no formal sign-off yet from Dr. Ronald on grading accuracy.

**Not started — Milestone 4 (integration, validation & deployment)**
- Full system/UAT testing (only one unit test file exists in the entire repo — `test_flexible_excel.py`)
- Authentication / access control (NFR-04)
- Formal performance testing against the 10-minute / 30-submission NFR
- Deployment prep (no Docker/CI/CD config found) and final stakeholder approval

---

## 4. Supporting Evidence

- **Commit distribution (all branches, `git log --all --format=%an`):** `kyounyo` (Zoe) 24, `JongChiShien` (Chi Shien) 6, `EeGwen` 2, `CCChuck03` (Qian Jun) 2. Note: Ee Gwen and Qian Jun's actual workload (prompt engineering, model evaluation) lives mostly in uncommitted local changes and the still-running `LLM` branch experiments — commit count understates their effort at this point in the timeline.
- **No deployment/CI files found:** searched for `docker`, `deploy`, `.github`, `workflow`, `ci.yml` — only `docs/user_workflow.md` matched (a doc, not a config).
- **Test coverage:** exactly one test file in the whole repo (`backend/tests/test_flexible_excel.py`).
- **Branch merge status:** `AI-Evaluation` is **not** an ancestor of `main` — 2 commits ahead, diverged, unmerged as of this check.
