"""Hard spend cap across the whole evaluation suite.

The user has $100 of OpenRouter credit and wants total spend on this
evaluation kept under $50. This module computes actual spend so far by
summing the cost_usd columns of every checkpoint CSV already on disk
(cross-process safe, since every run script persists cost per row), and
provides a guard to stop BEFORE a run would exceed the cap.
"""

import os
import glob
import pandas as pd

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")

BUDGET_CAP_USD = 50.0
# Leave a safety margin below the hard user-specified cap.
SAFE_CAP_USD = 45.0


def get_total_spend() -> float:
    total = 0.0
    for path in glob.glob(os.path.join(RESULTS_DIR, "*_raw.csv")):
        try:
            df = pd.read_csv(path)
            cost_col = "cost_usd" if "cost_usd" in df.columns else (
                "total_cost_usd" if "total_cost_usd" in df.columns else None
            )
            if cost_col:
                total += float(df[cost_col].sum())
        except Exception:
            continue
    return round(total, 4)


def check_budget(label: str = "") -> float:
    """Returns current total spend. Raises RuntimeError if the SAFE cap is hit."""
    total = get_total_spend()
    if total >= SAFE_CAP_USD:
        raise RuntimeError(
            f"[BUDGET GUARD] Stopping {label}: total spend ${total:.2f} has reached "
            f"the safety cap of ${SAFE_CAP_USD:.2f} (hard user limit ${BUDGET_CAP_USD:.2f})."
        )
    return total
