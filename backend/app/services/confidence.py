import re
from typing import Dict, Any, List

AUDIT_DISCREPANCY_THRESHOLD = 0.15  # Standardized 15% discrepancy threshold across system


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
    raw_conflicting_qs = multi_audit.get("conflicting_questions", [])
    if not isinstance(raw_conflicting_qs, list):
        raw_conflicting_qs = []
    
    audit_note = multi_audit.get("audit_note", "")

    # Component 1: Overall Score Agreement (0.0 to 1.0)
    score_agreement = max(0.0, 1.0 - (score_discrepancy / max_sc))

    # Component 2: Question-Level Agreement (0.0 to 1.0)
    feedback = llm_result.get("feedback", {})
    primary_breakdown = feedback.get("breakdown", []) if isinstance(feedback, dict) else []
    auditor_breakdown = multi_audit.get("auditor_breakdown", [])

    question_agreements: List[float] = []
    material_conflicting_qs: List[str] = []

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
                    
                    # Only treat as material conflict if score difference >= 1.0 mark
                    if diff >= 1.0:
                        material_conflicting_qs.append(q_num)
                else:
                    if norm_key in [normalize_question_number(q) for q in raw_conflicting_qs]:
                        q_agreed = 0.5
                        material_conflicting_qs.append(q_num)
                    else:
                        q_agreed = score_agreement

                question_agreements.append(q_agreed)

    if question_agreements:
        question_agreement = sum(question_agreements) / len(question_agreements)
    else:
        question_agreement = score_agreement

    # Component 3: Audit Factor (1.0 if audit passed and no material conflicts, else 0.5)
    audit_factor = 1.0 if (auditor_passed and len(material_conflicting_qs) == 0) else 0.5

    # Deterministic Final Confidence Formula
    deterministic_confidence = round(
        (0.40 * score_agreement) + (0.40 * question_agreement) + (0.20 * audit_factor),
        2
    )
    final_confidence = max(0.05, min(1.0, deterministic_confidence))

    # Multi-Factor Flagging Rules (Pragmatic 15% threshold & material conflicts only)
    flag_reasons: List[str] = []

    q_str = f" on {', '.join(material_conflicting_qs)}" if material_conflicting_qs else ""
    discrepancy_pct = (score_discrepancy / max_sc) * 100.0

    if len(material_conflicting_qs) > 0:
        flag_reasons.append(f"🤖 Multi-Agent Conflict{q_str}: Material subquestion score discrepancy (>= 1.0 mark)")
    elif discrepancy_pct > (AUDIT_DISCREPANCY_THRESHOLD * 100.0):
        flag_reasons.append(f"🤖 Multi-Agent Conflict: Overall score discrepancy of {score_discrepancy:.1f} points ({discrepancy_pct:.1f}%)")

    if final_confidence < 0.65:
        flag_reasons.append(f"📉 Low System Confidence ({final_confidence * 100:.0f}% < 65%)")

    score_pct = (primary_score / max_sc) * 100.0
    if 48.0 <= score_pct <= 52.0:
        flag_reasons.append("⚖️ Borderline Pass/Fail Grade: Human verification recommended")

    status = "flagged" if len(flag_reasons) > 0 else "graded"

    return {
        "confidence_score": final_confidence,
        "status": status,
        "flag_reasons": flag_reasons,
        "is_borderline": (48.0 <= score_pct <= 52.0),
        "is_audit_flagged": len(flag_reasons) > 0,
        "confidence_components": {
            "score_agreement": round(score_agreement, 2),
            "question_agreement": round(question_agreement, 2),
            "audit_factor": audit_factor
        }
    }
