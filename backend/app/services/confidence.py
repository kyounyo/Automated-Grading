from typing import Dict, Any


def evaluate_confidence_and_status(llm_result: Dict[str, Any], raw_text: str) -> Dict[str, Any]:
    """
    Evaluates confidence score and determines status ('graded' vs 'flagged').
    Flags submission for lecturer audit if confidence score is low (< 0.75) or text length is very short.
    """
    confidence = llm_result.get("confidence_score", 0.85)
    overall_score = llm_result.get("overall_score", 0.0)

    # Flagging heuristic checks
    is_borderline = (45.0 <= overall_score <= 55.0)  # Borderline pass/fail
    is_low_confidence = (confidence < 0.75)
    is_too_short = (len(raw_text.strip()) < 50)

    if is_low_confidence or is_borderline or is_too_short:
        status = "flagged"
    else:
        status = "graded"

    return {
        "confidence_score": round(confidence, 2),
        "status": status
    }
