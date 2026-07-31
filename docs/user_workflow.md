# AutoGrade+ User & Grading Workflow

## Human-in-the-Loop Workflow

AutoGrade+ is designed around a **Lecturer-First** grading workflow, ensuring that AI suggestions save time while human judgment maintains academic standards.

```
[Student Submission]
         |
         v
[AI Pipeline Evaluation]
         |
         +---------------------------------------+
         |                                       |
  Score & Reasoning                       Flag Check
         |                                       |
         v                                       v
[Auto-Approved (High Confidence)]       [Action Required Flagged]
         |                               (Borderline, Conflict, Audit)
         |                                       |
         +-------------------+-------------------+
                             |
                             v
               [Lecturer Dashboard & Review]
                             |
                   +---------+---------+
                   |                   |
            [Confirm Grade]    [Manual Override]
```

## Audit Flag Types
1. **Borderline Grade**: Submissions near grade boundaries (e.g., 49% or 59%) flagged for human review.
2. **Auditor Conflict**: Discrepancy between automated rubric checks and model confidence thresholds.
3. **Random Audit (e.g. 5%)**: Randomly sampled submissions selected for quality control assurance.
4. **Low Confidence**: Ambiguous phrasing or non-standard answers requiring instructor verification.
