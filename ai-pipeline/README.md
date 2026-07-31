# AutoGrade+ AI Pipeline

## Overview
The `ai-pipeline/` module contains the prompt engineering templates, evaluation strategies, and mock data generators for AutoGrade+.

## Key Modules

### 1. `prompts.py`
Defines prompt strategies used to grade student responses against marking rubrics:
- **`chain_of_thought`**: Direct step-by-step reasoning prompting strategy.
- **`rubric_strict`**: Strict rubric checking with explicit penalty breakdowns.
- **`few_shot`**: Example-guided grading for consistent score distributions.

### 2. `generate_mock_data.py`
Generates populated mock React context data (`AssignmentContext.jsx`) containing simulated student submissions, AI justifications, highlighted text tokens, and human-in-the-loop audit flags.

#### How to Run Mock Data Generation
```bash
python3 ai-pipeline/generate_mock_data.py
```
This updates `frontend/src/context/AssignmentContext.jsx`.
