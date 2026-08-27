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

    q_str = f" on {', '.join(material_conflicting_qs)}" if material_conflicting_qs else ""
    discrepancy_pct = (score_discrepancy / max_sc) * 100.0

    if len(material_conflicting_qs) > 0:
        flag_reasons.append(f"🤖 Multi-Agent Conflict{q_str}: Subquestion score discrepancy")
    elif discrepancy_pct > (AUDIT_DISCREPANCY_THRESHOLD * 100.0):
        flag_reasons.append(f"🤖 Multi-Agent Conflict: Score discrepancy of {score_discrepancy:.1f} pts ({discrepancy_pct:.1f}%)")

    # Flag low confidence when below configured threshold (e.g. 75%, 80%)
    import os
    conf_threshold = float(os.getenv("CONFIDENCE_THRESHOLD", "0.75"))
    if calibrated_confidence < conf_threshold:
        flag_reasons.append(f"📉 Low System Confidence ({calibrated_confidence * 100:.0f}% < {conf_threshold * 100:.0f}%)")

    # Flag terse answers
    if word_count < 20 and max_sc >= 5.0:
        flag_reasons.append(f"⚠️ Terse Answer ({word_count} words): Verify student explanation depth")

    status = "flagged" if len(flag_reasons) > 0 else "graded"

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
        }
    }

