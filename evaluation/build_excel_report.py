"""
Compiles all evaluation results (Phase A baselines + Phase B/C multi-agent
combos) into a single Excel workbook for side-by-side comparison, plus a
plain-language recommendation sheet on which model should take which role.

Usage:
    python build_excel_report.py
Output:
    evaluation/model_role_comparison_results.xlsx
"""

import os
import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(SCRIPT_DIR, "results")
OUT_PATH = os.path.join(SCRIPT_DIR, "model_role_comparison_results.xlsx")

MODEL_DISPLAY_NAMES = {
    "gemini": "Gemini 3.1 Flash Lite",
    "claude": "Claude Sonnet 4.6",
    "nemotron": "Nemotron 3 Super",
    "free": "Free Model (Llama 3.3 70B)",
}

# (column_name, Higher/Lower-is-better annotation) -- matches the user's
# reference "Multi-Agent (Grader and Auditor)" table format exactly.
MULTIAGENT_SHEET_TITLE = "Multi- Agent (Grader and Auditor)"
MULTIAGENT_COLUMN_ANNOTATIONS = [
    ("Architecture / Model Pairing", ""),
    ("Type", ""),
    ("Grader ICC", "H"),
    ("Grader MAE", "L"),
    ("Auto-Approved ICC", "H"),
    ("Auto-Approved MAE", "L (Auto-approved MAE < Overall MAE ideally)"),
    ("Automation Rate (%)", "H"),
    ("Flag Rate (%)", "L (when recall is acceptable)"),
    ("Flagging Recall (%)", "H (Of all the incorrect AI grades, how many did the Auditor successfully flag?)"),
    ("Flagging Precision (%)", "H (flagged submissions that actually had the defined grading error.)"),
    ("Flagging F1-Score (%)", "H"),
    ("Leakage (FN Rate) (%)", "L (Of the genuinely incorrect grades, how many escaped the Auditor and were automatically approved?)"),
    ("Over-flag (FP Rate) (%)", "L (Of the genuinely correct grades, how many did the Auditor unnecessarily flag?)"),
    ("Avg Latency (s)", "-"),
    ("Total Run Time", "-"),
    ("Total Cost (100 Qs)", "-"),
]


def fmt_pct(x):
    return f"{x:.2f}%" if pd.notna(x) else ""


def fmt_seconds_to_runtime(total_seconds):
    total_seconds = int(round(total_seconds))
    m, s = divmod(total_seconds, 60)
    return f"{m}m {s}s"


def safe_read_csv(path):
    return pd.read_csv(path) if os.path.exists(path) else pd.DataFrame()


def build_recommendation(baseline_summary: pd.DataFrame, multiagent_summary: pd.DataFrame) -> pd.DataFrame:
    rows = []

    if not baseline_summary.empty:
        best_grader = baseline_summary.sort_values("icc_a1", ascending=False).iloc[0]
        rows.append({
            "Role": "Grader (single-model baseline)",
            "Recommended Model": best_grader["model_key"],
            "Why": f"Highest ICC(A,1) = {best_grader['icc_a1']} against human scores, MAE = {best_grader['mae']}, "
                   f"at ${best_grader['total_cost_usd']} / avg {best_grader['avg_latency_s']}s per response."
        })
        worst_grader = baseline_summary.sort_values("icc_a1", ascending=True).iloc[0]
        rows.append({
            "Role": "Grader - weakest option",
            "Recommended Model": f"Avoid: {worst_grader['model_key']}",
            "Why": f"Lowest ICC(A,1) = {worst_grader['icc_a1']}, MAE = {worst_grader['mae']}."
        })

    if not multiagent_summary.empty:
        ms = multiagent_summary.copy()
        # Prefer combos with high ICC and good flagging recall (catches genuinely wrong grades)
        ms["rank_score"] = ms["icc_a1"].fillna(0) * 0.6 + (ms["flagging_recall_pct"].fillna(0) / 100.0) * 0.4
        best_combo = ms.sort_values("rank_score", ascending=False).iloc[0]
        rows.append({
            "Role": "Grader + Auditor pairing",
            "Recommended Model": f"Grader={best_combo['grader_model']}, Auditor={best_combo['auditor_model']}",
            "Why": f"ICC={best_combo['icc_a1']}, Flagging Recall={best_combo['flagging_recall_pct']}%, "
                   f"Flagging Precision={best_combo['flagging_precision_pct']}%, "
                   f"Automation Rate={best_combo['automation_rate_pct']}%, cost=${best_combo['total_cost_usd']}."
        })

        parser_rows = ms[ms["parser_model"] != "(none)"]
        if not parser_rows.empty:
            best_parser = parser_rows.sort_values("icc_a1", ascending=False).iloc[0]
            rows.append({
                "Role": "Retriever / Parser",
                "Recommended Model": best_parser["parser_model"],
                "Why": f"With this parser: ICC={best_parser['icc_a1']}, MAE={best_parser['mae']}, "
                       f"cost=${best_parser['total_cost_usd']}. Compare against the (none)/paid-parser row(s) "
                       f"in MultiAgent Summary to see whether the free model causes any accuracy loss."
            })

    return pd.DataFrame(rows)


def build_multiagent_leaderboard(multiagent_summary: pd.DataFrame, multiagent_raw_frames: dict) -> pd.DataFrame:
    """Reproduces the exact 'Multi-Agent (Grader and Auditor)' table format
    from the reference Model Comparison PDF, one row per grader/auditor combo."""
    rows = []
    for _, r in multiagent_summary.iterrows():
        grader_name = MODEL_DISPLAY_NAMES.get(r["grader_model"], r["grader_model"])
        auditor_name = MODEL_DISPLAY_NAMES.get(r["auditor_model"], r["auditor_model"])
        combo_type = "Self-Audit" if r["grader_model"] == r["auditor_model"] else "Heterogeneous"

        raw_df = multiagent_raw_frames.get(r["combo_name"])
        total_run_time_s = float(raw_df["total_latency_ms"].sum()) / 1000.0 if raw_df is not None and "total_latency_ms" in raw_df.columns else 0.0

        def r3(x):
            return round(x, 3) if pd.notna(x) else x

        rows.append({
            "Architecture / Model Pairing": f"{grader_name} ➔ {auditor_name}",
            "Type": combo_type,
            "Grader ICC": r3(r.get("icc_a1")),
            "Grader MAE": r3(r.get("mae")),
            "Auto-Approved ICC": r3(r.get("auto_approved_icc")),
            "Auto-Approved MAE": r3(r.get("auto_approved_mae")),
            "Automation Rate (%)": fmt_pct(r.get("automation_rate_pct")),
            "Flag Rate (%)": fmt_pct(r.get("flag_rate_pct")),
            "Flagging Recall (%)": fmt_pct(r.get("flagging_recall_pct")),
            "Flagging Precision (%)": fmt_pct(r.get("flagging_precision_pct")),
            "Flagging F1-Score (%)": fmt_pct(r.get("flagging_f1_pct")),
            "Leakage (FN Rate) (%)": fmt_pct(r.get("leakage_fn_rate_pct")),
            "Over-flag (FP Rate) (%)": fmt_pct(r.get("overflag_fp_rate_pct")),
            "Avg Latency (s)": r.get("avg_latency_s"),
            "Total Run Time": fmt_seconds_to_runtime(total_run_time_s),
            "Total Cost (100 Qs)": f"${r.get('total_cost_usd'):.4f}" if pd.notna(r.get("total_cost_usd")) else "",
        })
    cols = [c for c, _ in MULTIAGENT_COLUMN_ANNOTATIONS]
    return pd.DataFrame(rows, columns=cols)


def main():
    baseline_summary = safe_read_csv(os.path.join(RESULTS_DIR, "baseline_summary.csv"))
    baseline_per_q = safe_read_csv(os.path.join(RESULTS_DIR, "baseline_per_question.csv"))
    multiagent_summary = safe_read_csv(os.path.join(RESULTS_DIR, "multiagent_summary.csv"))

    baseline_raw_frames = []
    for f in os.listdir(RESULTS_DIR):
        if f.startswith("baseline_") and f.endswith("_raw.csv"):
            model_key = f[len("baseline_"):-len("_raw.csv")]
            df = pd.read_csv(os.path.join(RESULTS_DIR, f))
            df.insert(0, "model_key", model_key)
            baseline_raw_frames.append(df)
    baseline_raw = pd.concat(baseline_raw_frames, ignore_index=True) if baseline_raw_frames else pd.DataFrame()

    multiagent_raw_by_combo = {}
    for f in os.listdir(RESULTS_DIR):
        if f.startswith("multiagent_") and f.endswith("_raw.csv"):
            combo_name = f[len("multiagent_"):-len("_raw.csv")]
            df = pd.read_csv(os.path.join(RESULTS_DIR, f))
            multiagent_raw_by_combo[combo_name] = df
    if multiagent_raw_by_combo:
        multiagent_raw_frames = []
        for combo_name, df in multiagent_raw_by_combo.items():
            df = df.copy()
            df.insert(0, "combo_name", combo_name)
            multiagent_raw_frames.append(df)
        multiagent_raw = pd.concat(multiagent_raw_frames, ignore_index=True)
    else:
        multiagent_raw = pd.DataFrame()

    recommendation = build_recommendation(baseline_summary, multiagent_summary)
    multiagent_leaderboard = (
        build_multiagent_leaderboard(multiagent_summary, multiagent_raw_by_combo)
        if not multiagent_summary.empty else pd.DataFrame()
    )

    with pd.ExcelWriter(OUT_PATH, engine="openpyxl") as writer:
        if not recommendation.empty:
            recommendation.to_excel(writer, sheet_name="Recommendation", index=False)
        if not baseline_summary.empty:
            baseline_summary.to_excel(writer, sheet_name="Baseline Summary", index=False)
        if not baseline_per_q.empty:
            baseline_per_q.to_excel(writer, sheet_name="Baseline Per-Question", index=False)

        if not multiagent_leaderboard.empty:
            # Row 1: title, Row 2: Higher/Lower-is-better annotations, Row 3: headers, Row 4+: data
            multiagent_leaderboard.to_excel(writer, sheet_name="Multi-Agent (Grader Auditor)", index=False, startrow=2)
            ws = writer.sheets["Multi-Agent (Grader Auditor)"]
            ws.cell(row=1, column=1, value=MULTIAGENT_SHEET_TITLE)
            ws.cell(row=2, column=1, value="Higher/Lower Better?")
            for idx, (_, annotation) in enumerate(MULTIAGENT_COLUMN_ANNOTATIONS, start=1):
                if annotation:
                    ws.cell(row=2, column=idx, value=annotation)

        if not multiagent_summary.empty:
            multiagent_summary.to_excel(writer, sheet_name="MultiAgent Summary", index=False)
        if not baseline_raw.empty:
            baseline_raw.to_excel(writer, sheet_name="Baseline Raw", index=False)
        if not multiagent_raw.empty:
            multiagent_raw.to_excel(writer, sheet_name="MultiAgent Raw", index=False)

        # Auto-fit-ish column widths
        for sheet_name in writer.sheets:
            ws = writer.sheets[sheet_name]
            for col_cells in ws.columns:
                length = max((len(str(c.value)) if c.value is not None else 0) for c in col_cells)
                col_letter = col_cells[0].column_letter
                ws.column_dimensions[col_letter].width = min(60, max(10, length + 2))

    print(f"Saved Excel report to {OUT_PATH}")


if __name__ == "__main__":
    main()
