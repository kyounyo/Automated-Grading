# AutoGrade+ Empirical Evaluation Suite (Experiments 1 & 2)

This directory contains the automated evaluation framework used to benchmark and validate the **AutoGrade+ Multi-Agent Grading and Quality-Control Architecture** against human lecturer ground truth.

---

## 📑 Table of Contents
1. [Evaluation Dataset & Sampling Methodology](#1-evaluation-dataset--sampling-methodology)
2. [Experiment 1: Primary Grader Model Benchmark (Baseline)](#2-experiment-1-primary-grader-model-benchmark-baseline)
3. [Experiment 2: Two-Agent Auditor Quality-Control Benchmark](#3-experiment-2-two-agent-auditor-quality-control-benchmark)
4. [Statistical & Quality-Control Metrics Explained](#4-statistical--quality-control-metrics-explained)
5. [Checkpoint Resuming & Auto-Save Safety](#5-checkpoint-resuming--auto-save-safety)

---

## 1. Evaluation Dataset & Sampling Methodology

The evaluation uses authentic pharmacy student submissions from `Dataset for prompt.xlsx`:

| Question No. | Question Type / Concept | Max Mark | Sample Size ($N$) | Total Available |
| :---: | :--- | :---: | :---: | :---: |
| **Q6** | Polymer Microspheres & In-Situ Gelling | 10.0 | **25** | 125 |
| **Q8** | Peptide & Protein Delivery Concepts | 10.0 | **25** | 125 |
| **Q9** | Lipid Emulsions & Surfactants | 6.0 | **25** | 130 |
| **Q22** | Drug Delivery Mechanics | 6.0 | **25** | 130 |
| **TOTAL** | **Stratified Fixed Sample (`seed=42`)** | **All Scales** | **100** | **510** |

*Note: A composite key `(response_id, question_no)` is used to guarantee that all 4 questions get evaluated with exactly 25 responses each, even across duplicate student IDs.*

---

## 2. Experiment 1: Primary Grader Model Benchmark (Baseline)

### 🎯 Purpose
Evaluates the **standalone grading accuracy** of individual LLM models when acting as **Agent 2 (Primary Grader)** using Chain-of-Thought (CoT) prompting without an auditor.

```
Student Answer ──► [ Primary Grader Model ] ──► Predicted Score & Reasoning
```

### 🚀 How to Run Experiment 1

```bash
# Run Gemini 3.1 Flash Lite only (100 responses, ~8 mins)
./backend/venv/bin/python evaluation/run_experiment_suite.py --model A

# Run Nemotron 3 Super 120B only (100 responses, ~59 mins)
./backend/venv/bin/python evaluation/run_experiment_suite.py --model B

# Run both models sequentially and compile Master Comparison
./backend/venv/bin/python evaluation/run_experiment_suite.py --model all
```

### 📁 Output Files Generated:
* `results_Gemini_3.1_Flash_Lite.xlsx` (Multi-tab workbook: `Summary_Metrics`, `Q6`, `Q8`, `Q9`, `Q22`, `All_Responses`)
* `results_Nemotron_3_Super_120B.xlsx` (Multi-tab workbook: `Summary_Metrics`, `Q6`, `Q8`, `Q9`, `Q22`, `All_Responses`)
* `Model_Comparison_Master.xlsx` (Master Leaderboard & per-question ICC comparison matrix)

### 🏆 Baseline Results Summary:
| Model | Overall ICC (A,1) | MAE | Mean Error (Bias) | $\pm 1$ Mark (%) | Exact Match (%) | Pearson $r$ | Avg Latency / Resp | Total Run Time (100 Qs) | Total Cost |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Gemini 3.1 Flash Lite** | 0.787 | 0.91 | -0.32 *(strict)* | 76.0% | 37.0% | 0.721 | **5.04s** | **8m 23s** | **$0.045** |
| **Nemotron 3 Super 120B** | **0.881** | **0.70** | **+0.06** *(unbiased)* | **79.0%** | **50.0%** | **0.809** | 35.59s | 59m 19s | $0.266 |

---

## 3. Experiment 2: Two-Agent Auditor Quality-Control Benchmark

### 🎯 Purpose
Evaluates the **Multi-Agent Quality-Control Architecture** (Grader $\to$ Auditor $\to$ Confidence Engine). 

In AutoGrade+, **the Auditor does not overwrite grades**; instead, it detects grading conflicts and triggers the **Deterministic Flagging Engine** to isolate errors for human lecturer review.

```
                    Student Answer
                          │
                          ▼
                  ┌───────────────┐
                  │Primary Grader │ ── Assigns Predicted Grade
                  └───────┬───────┘
                          │
                          ▼
                  ┌───────────────┐
                  │ Auditor Agent │ ── Checks for Material Discrepancies
                  └───────┬───────┘
                          │
            ┌─────────────┴─────────────┐
            ▼                           ▼
   [AUDIT PASSED: "graded"]    [CONFLICT: "flagged"]
   Auto-approved for student   Sent to Lecturer Review Queue
```

### 🚀 How to Run Experiment 2

You can manually specify any **Grader** and **Auditor** model via CLI flags or interactive prompt:

#### Shorthand Model Keys:
* `A` = Gemini 3.1 Flash Lite (`google/gemini-3.1-flash-lite`)
* `B` = Nemotron 3 Super 120B (`nvidia/nemotron-3-super-120b-a12b`)
* `C` = Claude 4.6 Sonnet (`anthropic/claude-sonnet-4.6`)

#### Commands:
```bash
# 1. Heterogeneous: Fast Grader + Deep Auditor (Gemini 3.1 -> Nemotron 120B)
./backend/venv/bin/python evaluation/run_experiment_2_audit.py --grader A --auditor B

# 2. Self-Audit A: Gemini 3.1 -> Gemini 3.1
./backend/venv/bin/python evaluation/run_experiment_2_audit.py --grader A --auditor A

# 3. Heterogeneous: Deep Grader + Fast Guardrail (Nemotron 120B -> Gemini 3.1)
./backend/venv/bin/python evaluation/run_experiment_2_audit.py --grader B --auditor A

# 4. Self-Audit B: Nemotron 120B -> Nemotron 120B
./backend/venv/bin/python evaluation/run_experiment_2_audit.py --grader B --auditor B

# 5. Interactive Mode (prompts in terminal):
./backend/venv/bin/python evaluation/run_experiment_2_audit.py

# 6. Re-compile Master Comparison from existing CSVs:
./backend/venv/bin/python evaluation/run_experiment_2_audit.py --compile_only
```

### 📁 Output Files Generated:
* `results_exp2_{Grader}_to_{Auditor}.xlsx` (Contains tabs: `Audit_Summary`, `Q6_Audit`, `Q8_Audit`, `Q9_Audit`, `Q22_Audit`, `Flagged_For_Lecturer`, `All_Responses`)
* `Experiment_2_Audit_Master_Comparison.xlsx` (Master Leaderboard comparing all audited pairings side-by-side)

---

## 4. Statistical & Quality-Control Metrics Explained

### A. Reliability & Agreement Metrics
* **ICC (A,1) (Two-Way Random, Absolute Agreement)**: Measures agreement between AI score and Lecturer Ground Truth. ($>0.75$ = Good, $>0.90$ = Excellent).
* **MAE (Mean Absolute Error)**: Average mark discrepancy between AI and Human.
* **Mean Error (Bias)**: Positive value = AI is lenient (over-marks); Negative value = AI is strict (under-marks).
* **$\pm 1$ Mark Accuracy (%)**: Percentage of submissions within 1 mark of human grade.

### B. Quality-Control & Flagging Confusion Matrix
* **Actual Grading Error**: Defined operationally as $|\text{Grader Score} - \text{Human Score}| \ge 1.0\text{ mark}$.
* **Positive**: Flagged by system (`status = "flagged"` $\to$ sent to lecturer).
* **Negative**: Auto-approved (`status = "graded"` $\to$ no human review).

| Metric | Formula | Academic Meaning |
| :--- | :---: | :--- |
| **Flagging Recall (Sensitivity)** | $\frac{\text{TP}}{\text{TP} + \text{FN}}$ | **Error Detection Power**: Percentage of genuine AI grading errors caught and flagged by the Auditor. |
| **Flagging Precision (PPV)** | $\frac{\text{TP}}{\text{TP} + \text{FP}}$ | **Flag Quality**: Percentage of flagged submissions that were actual grading mistakes. |
| **Flagging $F_1$-Score** | $2 \times \frac{\text{Precision} \times \text{Recall}}{\text{Precision} + \text{Recall}}$ | **Overall Balance**: Harmonic mean balancing error detection power vs over-flagging. |
| **Leakage Rate (FN Rate)** | $\frac{\text{FN}}{\text{TP} + \text{FN}}$ | **Safety Risk**: Percentage of erroneous grades that slipped through unflagged. |
| **Over-flagging Rate (FP Rate)** | $\frac{\text{FP}}{\text{FP} + \text{TN}}$ | **Friction**: Percentage of accurate grades unnecessarily flagged. |
| **Automation Rate (%)** | $100\% - \text{Flag Rate}$ | Percentage of total class volume graded with zero human effort. |
| **Auto-Approved Cohort ICC** | $ICC \mid \text{Status} = \text{"graded"}$ | Accuracy on the safe auto-passed cohort. |

---

## 5. Checkpoint Resuming & Auto-Save Safety

Both evaluation scripts include **live persistence and interruption safety**:
* **Every 5 responses**: The multi-tab `.xlsx` workbook is updated and saved to disk.
* **Every single response**: Appended to the `.csv` checkpoint log.
* **Safe to Intercept (`Ctrl+C`)**: If you stop the script at any time, the Excel files will **never disappear**.
* **Seamless Resuming**: Re-running the command automatically skips previously evaluated students and continues from where it left off.
