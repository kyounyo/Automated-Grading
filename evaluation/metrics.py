"""Shared metric computation, matching the columns used in the project's
existing Model Comparison PDFs (ICC, MAE, bias, exact-match%, +-1 mark%,
Pearson r, Spearman rho, and multi-agent flagging quality metrics)."""

import pandas as pd
import pingouin as pg
from scipy import stats


def compute_grading_metrics(df: pd.DataFrame, score_col: str, human_col: str = "human_score") -> dict:
    """df must have one row per response with response_id, human_col, score_col."""
    sub = df.dropna(subset=[score_col, human_col]).copy()
    if sub.empty:
        return {}

    diff = sub[score_col] - sub[human_col]
    abs_diff = diff.abs()

    # response_id is the STUDENT's id, reused across their Q6/Q8/Q9/Q22
    # responses, so it is NOT unique on its own when a dataframe spans
    # multiple questions. Build a composite target key to avoid pingouin
    # silently merging different questions' rows for the same student.
    if "question_no" in sub.columns:
        target_key = sub["response_id"].astype(str) + "_" + sub["question_no"].astype(str)
    else:
        target_key = sub["response_id"].astype(str)

    sub = sub.assign(_target_key=target_key)
    icc_value = None
    try:
        long_rows = []
        for _, r in sub.iterrows():
            long_rows.append({"target": r["_target_key"], "rater": "Human", "score": r[human_col]})
            long_rows.append({"target": r["_target_key"], "rater": "AI", "score": r[score_col]})
        long_df = pd.DataFrame(long_rows)
        icc = pg.intraclass_corr(data=long_df, targets="target", raters="rater", ratings="score")
        icc_value = float(icc.set_index("Type").loc["ICC(A,1)", "ICC"])
    except Exception:
        icc_value = None

    try:
        pearson_r = float(stats.pearsonr(sub[human_col], sub[score_col])[0])
    except Exception:
        pearson_r = None
    try:
        spearman_r = float(stats.spearmanr(sub[human_col], sub[score_col])[0])
    except Exception:
        spearman_r = None

    return {
        "n": int(len(sub)),
        "icc_a1": round(icc_value, 4) if icc_value is not None else None,
        "mae": round(float(abs_diff.mean()), 4),
        "mean_error_bias": round(float(diff.mean()), 4),
        "exact_match_pct": round(float((abs_diff == 0).mean() * 100), 2),
        "within_1_mark_pct": round(float((abs_diff <= 1).mean() * 100), 2),
        "pearson_r": round(pearson_r, 4) if pearson_r is not None else None,
        "spearman_rho": round(spearman_r, 4) if spearman_r is not None else None,
    }


def compute_flagging_metrics(df: pd.DataFrame, score_col: str, status_col: str, human_col: str = "human_score") -> dict:
    """
    Ground truth for a "genuinely incorrect" AI grade: |score - human| >= 1 mark
    (matches the actual_error_ge_1mark convention used in the project's PDFs).
    status_col values expected: 'Auto-Approved' / 'Action Required'.
    """
    sub = df.dropna(subset=[score_col, human_col, status_col]).copy()
    if sub.empty:
        return {}

    sub["genuinely_wrong"] = (sub[score_col] - sub[human_col]).abs() >= 1.0
    sub["flagged"] = sub[status_col] == "Action Required"

    n = len(sub)
    auto = sub[~sub["flagged"]]
    flagged = sub[sub["flagged"]]

    tp = int(((sub["flagged"]) & (sub["genuinely_wrong"])).sum())
    fn = int(((~sub["flagged"]) & (sub["genuinely_wrong"])).sum())
    fp = int(((sub["flagged"]) & (~sub["genuinely_wrong"])).sum())
    tn = int(((~sub["flagged"]) & (~sub["genuinely_wrong"])).sum())

    recall = tp / (tp + fn) if (tp + fn) > 0 else None
    precision = tp / (tp + fp) if (tp + fp) > 0 else None
    f1 = (2 * precision * recall / (precision + recall)) if (precision and recall and (precision + recall) > 0) else None
    leakage = fn / (tp + fn) if (tp + fn) > 0 else None  # genuinely wrong that slipped through as auto-approved
    overflag = fp / (fp + tn) if (fp + tn) > 0 else None  # genuinely correct that got flagged anyway

    auto_metrics = compute_grading_metrics(auto, score_col, human_col) if len(auto) else {}

    return {
        "automation_rate_pct": round(len(auto) / n * 100, 2),
        "flag_rate_pct": round(len(flagged) / n * 100, 2),
        "flagging_recall_pct": round(recall * 100, 2) if recall is not None else None,
        "flagging_precision_pct": round(precision * 100, 2) if precision is not None else None,
        "flagging_f1_pct": round(f1 * 100, 2) if f1 is not None else None,
        "leakage_fn_rate_pct": round(leakage * 100, 2) if leakage is not None else None,
        "overflag_fp_rate_pct": round(overflag * 100, 2) if overflag is not None else None,
        "auto_approved_icc": auto_metrics.get("icc_a1"),
        "auto_approved_mae": auto_metrics.get("mae"),
        "auto_approved_n": auto_metrics.get("n", 0),
    }
