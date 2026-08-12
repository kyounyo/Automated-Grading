import re
from typing import Dict, Any, List

AUDIT_DISCREPANCY_THRESHOLD = 0.10  # Standardized 10% discrepancy threshold across system


def normalize_question_number(q_num: str) -> str:
    """Normalizes question keys (e.g. 'Q6(a)', 'Q6 (a)', 'q6(a)', 'Q6(A)') for exact matching."""
    if not q_num:
        return ""
    return re.sub(r"\s+", "", str(q_num)).lower()


def evaluate_confidence_and_status(
    llm_result: Dict[str, Any],
    raw_text: str,
    total_max_score: float = 20.0
) -> Dict[str, Any]:
    """
    Deterministic Confidence & Decision Engine (AutoGrade+ Architecture):
    Calculates confidence independently based on measurable grading evidence rather than self-reported LLM values.
    
    Formula:
      Confidence = (0.40 * Score_Agreement) + (0.40 * Question_Agreement) + (0.20 * Audit_Factor)
      
    Components:
    1. Overall Score Agreement: 1 - (|Primary_Score - Auditor_Score| / Total_Max_Score)
    2. Question-Level Agreement: Average normalized agreement across all subquestions
    3. Audit Factor: 1.0 if Agent 3 audit_passed else 0.5
    """
    max_sc = total_max_score if total_max_score > 0 else 20.0
    primary_score = float(llm_result.get("overall_score", 0.0))
    
    multi_audit = llm_result.get("multi_agent_audit", {})
    auditor_passed = bool(multi_audit.get("auditor_passed", True))
    auditor_score = float(multi_audit.get("auditor_score", primary_score))
    score_discrepancy = float(multi_audit.get("score_discrepancy", abs(primary_score - auditor_score)))
    conflicting_qs = multi_audit.get("conflicting_questions", [])
    if not isinstance(conflicting_qs, list):
        conflicting_qs = []
    
    conflicting_qs_norm = [normalize_question_number(q) for q in conflicting_qs]
    audit_note = multi_audit.get("audit_note", "")

    # Component 1: Overall Score Agreement (0.0 to 1.0)
    score_agreement = max(0.0, 1.0 - (score_discrepancy / max_sc))

    # Component 2: Question-Level Agreement (0.0 to 1.0)
    feedback = llm_result.get("feedback", {})
    primary_breakdown = feedback.get("breakdown", []) if isinstance(feedback, dict) else []
    auditor_breakdown = multi_audit.get("auditor_breakdown", [])

    question_agreements: List[float] = []

    if primary_breakdown and isinstance(primary_breakdown, list):
        auditor_map = {}
        if auditor_breakdown and isinstance(auditor_breakdown, list):
            for a_item in auditor_breakdown:
                if isinstance(a_item, dict):
                    q_num = str(a_item.get("question_number", "")).strip()
                    norm_key = normalize_question_number(q_num)
                    if norm_key:
                        auditor_map[norm_key] = float(a_item.get("auditor_score", 0.0))

        for p_item in primary_breakdown:
            if isinstance(p_item, dict):
                q_num = str(p_item.get("question_number", "")).strip()
                norm_key = normalize_question_number(q_num)
                p_q_score = float(p_item.get("score_awarded", 0.0))
                q_max = float(p_item.get("max_score", 5.0))
                if q_max <= 0:
                    q_max = 5.0

                if norm_key in auditor_map:
                    a_q_score = auditor_map[norm_key]
                    diff = abs(p_q_score - a_q_score)
                    q_agreed = max(0.0, 1.0 - (diff / q_max))
                else:
                    if norm_key in conflicting_qs_norm:
                        q_agreed = 0.5
                    else:
                        q_agreed = score_agreement

                question_agreements.append(q_agreed)

    if question_agreements:
        question_agreement = sum(question_agreements) / len(question_agreements)
    else:
        question_agreement = score_agreement

    # Component 3: Audit Factor (1.0 if audit passed, else 0.5)
    audit_factor = 1.0 if auditor_passed else 0.5

    # Deterministic Final Confidence Formula
    deterministic_confidence = round(
        (0.40 * score_agreement) + (0.40 * question_agreement) + (0.20 * audit_factor),
        2
    )
    final_confidence = max(0.05, min(1.0, deterministic_confidence))

    # Multi-Factor Flagging Rules (Consistent 10% threshold)
    flag_reasons: List[str] = []

    q_str = f" on {', '.join(conflicting_qs)}" if conflicting_qs else ""
    discrepancy_pct = (score_discrepancy / max_sc) * 100.0

    if not auditor_passed or len(conflicting_qs) > 0:
        flag_reasons.append(f"🤖 Multi-Agent Conflict{q_str}: {audit_note or 'Scoring logic discrepancy detected between agents'}")
    elif discrepancy_pct > (AUDIT_DISCREPANCY_THRESHOLD * 100.0):
        flag_reasons.append(f"🤖 Multi-Agent Conflict{q_str}: Overall score discrepancy of {score_discrepancy:.1f} points ({discrepancy_pct:.1f}%)")

    if final_confidence < 0.75:
        flag_reasons.append(f"📉 Low System Confidence ({final_confidence * 100:.0f}% < 75%)")

    score_pct = (primary_score / max_sc) * 100.0
    if 45.0 <= score_pct <= 55.0:
        flag_reasons.append("⚖️ Borderline Pass/Fail Grade: Human verification recommended")

    if llm_result.get("status") == "flagged" and not flag_reasons:
        flag_reasons.append(f"🤖 Auditor requested review: {audit_note or 'Audit verification required'}")

    status = "flagged" if len(flag_reasons) > 0 else "graded"

    return {
        "confidence_score": final_confidence,
        "status": status,
        "flag_reasons": flag_reasons,
        "is_borderline": (45.0 <= score_pct <= 55.0),
        "is_audit_flagged": len(flag_reasons) > 0,
        "confidence_components": {
            "score_agreement": round(score_agreement, 2),
            "question_agreement": round(question_agreement, 2),
            "audit_factor": audit_factor
        }
    }
