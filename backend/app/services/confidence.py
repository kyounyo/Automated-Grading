import re
from typing import Dict, Any, List

AUDIT_DISCREPANCY_THRESHOLD = 0.15  # Standardized 15% discrepancy threshold across system


def normalize_question_number(q_num: str) -> str:
    """Normalizes question keys (e.g. 'Q6(a)', 'Q6 (a)', 'q6(a)', 'Q6(A)') for exact matching."""
    if not q_num:
        return ""
    return re.sub(r"\s+", "", str(q_num)).lower()


def extract_main_question_number(q_num: str) -> str:
    """Extracts main question identifier (e.g. 'Q6(a)' -> 'Q6', '6b' -> 'Q6', 'Question 8' -> 'Q8')."""
    if not q_num:
        return ""
    s = str(q_num).strip().upper()
    m = re.search(r'(?:QUESTION|Q)?\s*(\d+)', s, re.IGNORECASE)
    if m:
        return f"Q{m.group(1)}"
    clean = re.sub(r'[^A-Z0-9]', '', s)
    return clean or s


def evaluate_discrepancy(
    primary_score: float,
    auditor_score: float,
    max_score: float,
    tolerance_rate: float,
    absolute_cap: float = 2.0
) -> Dict[str, Any]:
    """
    Evaluates multi-agent discrepancy against dynamic tolerance and absolute cap.

    Decision Rule:
        D_i = min(tolerance_rate * max_score, absolute_cap)
        Conflict if |primary_score - auditor_score| > D_i + 1e-5
    """
    diff = round(abs(float(primary_score) - float(auditor_score)), 4)
    raw_allowed = float(tolerance_rate) * float(max_score)
    allowed_diff = round(min(raw_allowed, float(absolute_cap)), 4)
    is_conflict = diff > (allowed_diff + 1e-5)

    return {
        "difference": diff,
        "allowed_difference": allowed_diff,
        "is_conflict": is_conflict,
        "tolerance_rate": tolerance_rate,
        "absolute_cap_applied": raw_allowed > float(absolute_cap)
    }


def evaluate_confidence_and_status(
    llm_result: Dict[str, Any],
    raw_text: str,
    total_max_score: float = 20.0,
    tolerance_rate: float = 0.10
) -> Dict[str, Any]:
    """
    Deterministic Confidence & Decision Engine (AutoGrade+ Architecture):
    Calculates confidence independently based on measurable grading evidence rather than self-reported LLM values.
    Evaluates at the Question-by-Question level (not micro-subquestions).
    """
    max_sc = total_max_score if total_max_score > 0 else 20.0
    primary_score = float(llm_result.get("overall_score", 0.0))
    
    multi_audit = llm_result.get("multi_agent_audit", {})
    auditor_passed = bool(multi_audit.get("auditor_passed", True))
    auditor_score = float(multi_audit.get("auditor_score", primary_score))
    score_discrepancy = float(multi_audit.get("score_discrepancy", abs(primary_score - auditor_score)))
    disagreement_severity = str(multi_audit.get("disagreement_severity", "NONE")).upper()
    raw_conflicting_qs = multi_audit.get("conflicting_questions", [])
    if not isinstance(raw_conflicting_qs, list):
        raw_conflicting_qs = []
    
    audit_note = multi_audit.get("audit_note", "")

    # Component 1: Overall Score Agreement (0.0 to 1.0)
    score_agreement = max(0.0, 1.0 - (score_discrepancy / max_sc))

    # Component 2: Main Question-Level Agreement (Question-by-Question)
    feedback = llm_result.get("feedback", {})
    primary_breakdown = feedback.get("breakdown", []) if isinstance(feedback, dict) else []
    auditor_breakdown = multi_audit.get("auditor_breakdown", [])

    # Group subquestions into Main Questions (e.g. Q6, Q8)
    def aggregate_by_main_q(items_list: list, score_key: str = "score_awarded"):
        agg = {}
        if not items_list or not isinstance(items_list, list):
            return agg
        for item in items_list:
            if not isinstance(item, dict):
                continue
            raw_q = str(item.get("question_number") or item.get("criterion") or "").strip()
            main_q = extract_main_question_number(raw_q)
            if not main_q:
                continue
            sc = None
            for k in [score_key, "score_awarded", "auditor_score", "score"]:
                if item.get(k) is not None:
                    try:
                        sc = float(item[k])
                        break
                    except (ValueError, TypeError):
                        pass
            if sc is None:
                sc = 0.0
            mx = float(item.get("max_score", item.get("maxMark", 10.0)))
            if main_q not in agg:
                agg[main_q] = {"score": sc, "max_score": mx}
            else:
                agg[main_q]["score"] += sc
                agg[main_q]["max_score"] += mx
        return agg

    p_main_map = aggregate_by_main_q(primary_breakdown, "score_awarded")
    a_main_map = aggregate_by_main_q(auditor_breakdown, "auditor_score")

    question_agreements: List[float] = []
    material_conflicting_qs: List[str] = []

    if p_main_map:
        for main_q, p_data in p_main_map.items():
            p_q_score = p_data["score"]
            q_max = p_data["max_score"] if p_data["max_score"] > 0 else 10.0

            if main_q in a_main_map:
                a_q_score = a_main_map[main_q]["score"]
                disc = evaluate_discrepancy(
                    primary_score=p_q_score,
                    auditor_score=a_q_score,
                    max_score=q_max,
                    tolerance_rate=tolerance_rate,
                    absolute_cap=2.0
                )
                diff = disc["difference"]
                q_agreed = max(0.0, 1.0 - (diff / q_max))
                # Only flag as conflict if overall severity is not NONE or auditor did not pass cleanly
                if disc["is_conflict"] and not (auditor_passed and score_discrepancy == 0.0 and disagreement_severity == "NONE"):
                    material_conflicting_qs.append(
                        f"{main_q} (Primary: {p_q_score:g} pts vs Auditor: {a_q_score:g} pts | Δ{diff:.1f} pts > {disc['allowed_difference']:.1f} limit)"
                    )
            else:
                q_agreed = score_agreement

            question_agreements.append(q_agreed)

    # Clean audit pass overrides any micro-rounding offset
    if (auditor_passed and score_discrepancy == 0.0) or disagreement_severity == "NONE":
        material_conflicting_qs = []

    if question_agreements:
        question_agreement = sum(question_agreements) / len(question_agreements)
    else:
        question_agreement = score_agreement

    # Component 3: Audit Factor (1.0 if audit passed and no material conflicts, else 0.5)
    audit_factor = 1.0 if (auditor_passed and len(material_conflicting_qs) == 0) else 0.5

    # Component 4: Answer Evidence & Completeness Factor (0.0 to 1.0)
    word_count = len(re.findall(r'\b\w+\b', raw_text or ""))
    # Terse answers (< 30 words) carry higher grading ambiguity
    if word_count >= 60:
        evidence_factor = 1.0
    elif word_count >= 30:
        evidence_factor = 0.85
    elif word_count >= 15:
        evidence_factor = 0.65
    else:
        evidence_factor = 0.45

    # Deterministic Final Confidence Formula (Calibrated & Realistic)
    # Agreement: 70%, Audit: 15%, Evidence/Completeness: 15%
    raw_confidence = (
        (0.35 * score_agreement) +
        (0.35 * question_agreement) +
        (0.15 * audit_factor) +
        (0.15 * evidence_factor)
    )

    # Uncertainty penalty on partial scores (middle scores carry more subjectivity than 0% or 100%)
    score_pct = (primary_score / max_sc) * 100.0
    if 30.0 <= score_pct <= 70.0 and (score_agreement < 0.95 or question_agreement < 0.95):
        raw_confidence -= 0.05

    # Calibrate ceiling so AI grading isn't deceptively 100% (max 0.95 for perfect responses)
    calibrated_confidence = round(min(0.95, max(0.20, raw_confidence)), 2)

    # Multi-Factor Flagging Rules (Aligned with Frontend 75% threshold & realistic QA)
    flag_reasons: List[str] = []

    # Total assignment discrepancy check
    num_qs = max(1, len(primary_breakdown) if primary_breakdown else 1)
    total_disc = evaluate_discrepancy(
        primary_score=primary_score,
        auditor_score=auditor_score,
        max_score=max_sc,
        tolerance_rate=tolerance_rate,
        absolute_cap=2.0 * num_qs
    )
    is_total_conflict = total_disc["is_conflict"]

    # Flag as Multi-Agent Discrepancy if question or total discrepancy exceeds tolerance
    tol_pct_label = f"{int(round(tolerance_rate * 100))}%"
    if len(material_conflicting_qs) > 0:
        flag_reasons.append(f"🤖 Multi-Agent Discrepancy on {', '.join(material_conflicting_qs)}: Exceeds {tol_pct_label} quality-control tolerance")
    elif is_total_conflict:
        flag_reasons.append(
            f"🤖 Multi-Agent Discrepancy: Overall score delta of {score_discrepancy:.1f} pts (Primary: {primary_score:g} pts vs Auditor: {auditor_score:g} pts) exceeds {tol_pct_label} tolerance ({total_disc['allowed_difference']:.1f} pts limit)"
        )
    elif not auditor_passed and disagreement_severity in ["MAJOR", "MODERATE"]:
        flag_reasons.append(
            f"🤖 Multi-Agent Quality Audit Failed ({disagreement_severity} Discrepancy): {audit_note or 'Auditor rejected primary score; requires lecturer review'}"
        )

    # Flag low confidence when below configured threshold (e.g. 75%, 80%)
    # If already flagged for multi-agent discrepancy, the low confidence is a direct consequence of the discrepancy
    import os
    conf_threshold = float(os.getenv("CONFIDENCE_THRESHOLD", "0.75"))
    if calibrated_confidence < conf_threshold and not any("Multi-Agent" in r for r in flag_reasons):
        flag_reasons.append(f"📉 Low System Confidence ({calibrated_confidence * 100:.0f}% < {conf_threshold * 100:.0f}%)")

    # Flag terse answers
    if word_count < 20 and max_sc >= 5.0:
        flag_reasons.append(f"⚠️ Terse Answer ({word_count} words): Verify student explanation depth")

    status = "flagged" if len(flag_reasons) > 0 else "graded"

    # Audit Trail for Discrepancy-Based Quality Control
    discrepancy_audit = {
        "primary_score": round(primary_score, 2),
        "auditor_score": round(auditor_score, 2),
        "reconciled_score": round(auditor_score if status == "graded" else primary_score, 2),
        "discrepancy": round(score_discrepancy, 2),
        "allowed_discrepancy": round(total_disc["allowed_difference"], 2),
        "tolerance_rate": tolerance_rate,
        "resolution_status": "reconciled_auto_approved" if status == "graded" else "escalated_lecturer_review",
        "conflicting_questions": material_conflicting_qs
    }

    return {
        "confidence_score": calibrated_confidence,
        "status": status,
        "flag_reasons": flag_reasons,
        "is_borderline": False,
        "is_audit_flagged": len(flag_reasons) > 0,
        "confidence_components": {
            "score_agreement": round(score_agreement, 2),
            "question_agreement": round(question_agreement, 2),
            "audit_factor": audit_factor,
            "evidence_factor": round(evidence_factor, 2)
        },
        "discrepancy_audit": discrepancy_audit
    }

