import random
from typing import Dict, Any, List


def evaluate_confidence_and_status(llm_result: Dict[str, Any], raw_text: str) -> Dict[str, Any]:
    """
    Decision Engine: Evaluates multi-factor confidence score and determines status ('graded' vs 'flagged').
    
    A submission is FLAGGED if any of these conditions are met:
    1. Multi-Agent Auditor Discrepancy: Agent 3 auditor failed verification or score discrepancy > 15%
    2. Blank / Short Answer: Raw response text is missing or < 40 characters
    3. Low AI Confidence: Self-reported confidence < 75%
    4. Borderline Pass/Fail Grade: Overall score falls between 45% - 55%
    5. Random Quality Control Audit: 5% random sampling for lecturer review
    """
    confidence = llm_result.get("confidence_score", 0.85)
    overall_score = llm_result.get("overall_score", 0.0)
    
    multi_audit = llm_result.get("multi_agent_audit", {})
    auditor_passed = multi_audit.get("auditor_passed", True)
    score_discrepancy = multi_audit.get("score_discrepancy", 0.0)

    flag_reasons: List[str] = []

    # 1. Multi-Agent Auditor Discrepancy Check
    if not auditor_passed:
        flag_reasons.append("Multi-Agent Auditor: Scoring logic contradiction detected")
    elif score_discrepancy > 15.0:
        flag_reasons.append(f"Multi-Agent Auditor: Score discrepancy of {score_discrepancy:.1f} points between agents")

    # 2. Low AI Confidence Check
    if confidence < 0.75:
        flag_reasons.append(f"Low AI Confidence ({confidence * 100:.0f}% < 75%)")

    # 4. Borderline Pass/Fail Boundary Check
    if 45.0 <= overall_score <= 55.0:
        flag_reasons.append("Borderline Pass/Fail Grade: Human verification recommended")

    # 5. Random 5% Quality Control Audit Sampling
    if random.random() < 0.05:
        flag_reasons.append("Random 5% Quality Control Audit Sample")

    # Check if primary agent explicitly requested flagging
    if llm_result.get("status") == "flagged" and not flag_reasons:
        flag_reasons.append("Primary AI Grader requested audit review")

    status = "flagged" if len(flag_reasons) > 0 else "graded"

    return {
        "confidence_score": max(0.0, min(1.0, round(confidence, 2))),
        "status": status,
        "flag_reasons": flag_reasons,
        "is_borderline": (45.0 <= overall_score <= 55.0),
        "is_audit_flagged": len(flag_reasons) > 0
    }


