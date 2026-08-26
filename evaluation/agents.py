"""
Standalone multi-agent grading pipeline used for model/role evaluation.

The prompts, JSON schema field names, and confidence-engine formula in this
file are ported VERBATIM from the production implementation on the main
branch (backend/app/services/llm_service.py + confidence.py, as invoked by
evaluation/run_experiment_suite.py and run_experiment_2_audit.py) so that
results are directly comparable to the reference Model Comparison PDFs.
Only the transport layer (this uses the openai client + our own retry/backoff
instead of main's raw urllib call with a 35s timeout) and the explicit
model-per-role parameterization are different -- main's 35s timeout drops a
large fraction of Nemotron calls given its observed 30-450s latency, so this
keeps a more generous timeout/retry policy while keeping prompts identical.
"""

import os
import re
import json
import time
from typing import Dict, Any, Optional, Tuple, List

from openai import OpenAI
from model_config import estimate_cost

_client: Optional[OpenAI] = None

AUDIT_DISCREPANCY_THRESHOLD = 0.15  # matches main/confidence.py


def get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY not set")
        _client = OpenAI(api_key=api_key, base_url="https://openrouter.ai/api/v1")
    return _client


def clean_json_response(content: str) -> Dict[str, Any]:
    """Ported from main's _clean_json_response: strips <think> blocks / markdown
    fences and repairs common JSON issues, with a regex fallback extractor."""
    if not content:
        raise ValueError("Empty response string received from LLM.")

    clean_text = content.strip()

    think_match = re.search(r"<think>.*?</think>", clean_text, flags=re.DOTALL)
    if think_match:
        clean_text = clean_text.replace(think_match.group(0), "").strip()

    if clean_text.startswith("```json"):
        clean_text = clean_text[7:]
    elif clean_text.startswith("```"):
        clean_text = clean_text[3:]
    if clean_text.endswith("```"):
        clean_text = clean_text[:-3]
    clean_text = clean_text.strip()

    start_idx = clean_text.find("{")
    end_idx = clean_text.rfind("}")
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        clean_text = clean_text[start_idx:end_idx + 1]

    try:
        return json.loads(clean_text)
    except json.JSONDecodeError:
        pass

    repaired = clean_text
    repaired = re.sub(r",\s*([\}\]])", r"\1", repaired)
    repaired = re.sub(r'("(?:[^"\\]|\\.)*")\s*\n?\s*(")', r"\1, \2", repaired)
    repaired = re.sub(r"(\d+(?:\.\d+)?|true|false|null)\s*\n?\s*(\")", r"\1, \2", repaired)
    repaired = re.sub(r"(\})\s*\n?\s*(\{)", r"\1, \2", repaired)
    repaired = re.sub(r"(\])\s*\n?\s*(\{)", r"\1, \2", repaired)

    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass

    # Schema-agnostic fallback: this parser backs the Parser/Grader/Auditor
    # agents alike, whose JSON schemas use different field names
    # (overall_score vs auditor_score). Detect which one is present so a
    # fallback-parsed auditor response doesn't come back missing
    # auditor_score/audit_passed (silently breaking downstream .get() calls).
    score_m = re.search(r'"overall_score"\s*:\s*([0-9.]+)', clean_text)
    auditor_score_m = re.search(r'"auditor_score"\s*:\s*([0-9.]+)', clean_text)
    audit_passed_m = re.search(r'"audit_passed"\s*:\s*(true|false)', clean_text, re.IGNORECASE)
    conf_m = re.search(r'"confidence_score"\s*:\s*([0-9.]+)', clean_text)
    summary_m = re.search(r'"summary"\s*:\s*"([^"]*)"', clean_text)
    note_m = re.search(r'"discrepancy_note"\s*:\s*"([^"]*)"', clean_text)

    result: Dict[str, Any] = {"reasoning": "Extracted via robust JSON fallback parser.", "parse_fallback": True}

    if auditor_score_m:
        result["auditor_score"] = float(auditor_score_m.group(1))
        result["audit_passed"] = audit_passed_m.group(1).lower() == "true" if audit_passed_m else True
        result["conflicting_questions"] = []
        result["auditor_breakdown"] = []
        result["discrepancy_note"] = note_m.group(1) if note_m else "Extracted via fallback parser."

    if score_m or not auditor_score_m:
        result["overall_score"] = float(score_m.group(1)) if score_m else 0.0
        result["confidence_score"] = float(conf_m.group(1)) if conf_m else 0.9
        result["status"] = "graded"
        result["feedback"] = {"summary": summary_m.group(1) if summary_m else "AI grading evaluation completed.", "breakdown": []}
        result["highlights"] = []

    return result


def call_agent(
    system_prompt: str,
    user_prompt: str,
    model: str,
    temperature: float = 0.0,
    max_tokens: int = 8000,
    retries: int = 2,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """
    Calls an OpenRouter model and returns (parsed_json_or_None, meta) where
    meta contains latency_s, input_tokens, output_tokens, cost_usd, raw_text, error.
    """
    client = get_client()
    last_err = None
    meta = {"latency_s": 0.0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "raw_text": "", "error": None}
    for attempt in range(retries + 1):
        start = time.time()
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            latency = time.time() - start
            if not getattr(response, "choices", None):
                err_detail = getattr(response, "error", None) or "no choices in response"
                raise RuntimeError(f"empty_choices: {err_detail}")
            raw_text = response.choices[0].message.content or ""
            usage = getattr(response, "usage", None)
            in_tok = getattr(usage, "prompt_tokens", 0) or 0
            out_tok = getattr(usage, "completion_tokens", 0) or 0
            cost = estimate_cost(model, in_tok, out_tok)

            meta = {
                "latency_s": round(latency, 3),
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "cost_usd": round(cost, 6),
                "raw_text": raw_text,
                "error": None,
            }
            if not raw_text.strip():
                last_err = "empty_response"
                meta["error"] = last_err
                continue
            parsed = clean_json_response(raw_text)
            return parsed, meta
        except Exception as e:
            last_err = str(e)
            latency = time.time() - start
            meta = {
                "latency_s": round(latency, 3),
                "input_tokens": 0,
                "output_tokens": 0,
                "cost_usd": 0.0,
                "raw_text": "",
                "error": last_err,
            }
            if "429" in last_err or "rate" in last_err.lower() or "empty_choices" in last_err or "empty_response" in last_err:
                time.sleep(4 * (attempt + 1))
            continue
    return None, meta


def clamp_score(score: float, max_score: float) -> float:
    """Ported from main: score = max(0.0, min(max_score, score))."""
    return max(0.0, min(float(max_score), float(score)))


# ---------------------------------------------------------------------------
# Agent 1: Retriever / Parser Agent  (main: call_rubric_context_parser_agent)
# ---------------------------------------------------------------------------

def call_parser_agent(question_no: str, rubric: str, max_score: float, model: str, rag_context: str = ""):
    rubric_json = [{"question_number": question_no, "max_score": float(max_score), "criterion": rubric}]
    prompt = f"""
You are an expert Academic Rubric Parser. Standardize the following rubric criteria and reference model answers into clean, structured evaluation rules.

Retrieved Vector Context:
{rag_context}

Reference Model Answer:
{rubric or "Evaluate answer based on clarity, technical accuracy, and completeness."}

Raw Rubric Criteria:
{json.dumps(rubric_json, indent=2)}

OUTPUT FORMAT (Respond ONLY in valid JSON matching this schema):
{{
  "structured_rules": [
    {{
      "question_number": "Q1",
      "max_score": 10.0,
      "core_concepts": ["Concept A", "Concept B"],
      "grading_guidelines": "Award full credit if both concepts are explained."
    }}
  ],
  "parser_notes": "Rubric and RAG context successfully standardized."
}}
"""
    system = "You are a precise academic rubric parsing agent. Always respond strictly in valid JSON format."
    return call_agent(system, prompt, model, temperature=0.0, max_tokens=1500)


# ---------------------------------------------------------------------------
# Agent 2: Grader Agent  (main: call_primary_grading_agent)
# ---------------------------------------------------------------------------

def call_grader_agent(
    question_no: str,
    rubric: str,
    max_score: float,
    student_answer: str,
    model: str,
    structured_rubric: Optional[Dict[str, Any]] = None,
    rag_context: str = "",
):
    raw_rubric_json = [{"question_number": question_no, "max_score": float(max_score), "criterion": rubric}]
    struct_rubric = structured_rubric or {
        "structured_rules": [
            {"question_number": question_no, "max_score": float(max_score), "grading_guidelines": rubric}
        ]
    }

    prompt = f"""
You are an expert academic evaluator specializing in objective short-answer grading.

{rag_context}

Standardized Rubric Rules:
{json.dumps(struct_rubric, indent=2)}

Raw Rubric Criteria:
{json.dumps(raw_rubric_json, indent=2)}

Total Assignment Max Score: {max_score}

Model Answer / Marking Scheme:
{rubric or "Evaluate answer based on clarity, technical accuracy, and completeness."}

Student Submission:
{student_answer}

GRADING PROTOCOL (v1.3-multi-question-highlights):
1. MEANING OVER EXACT WORDS: Award points for concepts matching rubric intent.
2. STRICT CAPPING: Do not exceed maximum points allocated per question. Sum of points awarded across all questions MUST NOT exceed {max_score}.
3. ZERO MARK RULE: If a student answer for a question is blank, empty, dash ('-'), 'N/A', or missing, award EXACTLY 0 marks for that question. Do NOT award partial credit for empty or missing answers.
4. REASONING FIRST: Analyze student response against each criterion step-by-step before finalizing score.
5. MANDATORY PER-QUESTION HIGHLIGHTS: You MUST generate at least one highlight entry for EVERY question and sub-part in the student submission (e.g., Q6(a), Q6(b), Q8(a), Q8(b)). Highlight exact quotes from the student's text for each question.
6. DETAILED EXPLANATION REQUIREMENT: Each highlight comment MUST state:
   (a) Exact marks awarded and key concepts matched (e.g. 'Awarded 1 mark for mentioning prolonged therapeutic effect in (a)').
   (b) Specific rubric points missed or failed (e.g. 'Failed to address specific advantages (biodegradability) and disadvantages required by rubric').

OUTPUT FORMAT (Respond ONLY in valid JSON matching this schema):
{{
  "overall_score": 8.5,
  "confidence_score": 0.90,
  "status": "graded",
  "reasoning": "Step-by-step analysis comparing student response to rubric...",
  "feedback": {{
    "summary": "Strong submission demonstrating clear understanding of core concepts.",
    "breakdown": [
      {{
        "question_number": "Q6(a)",
        "score_awarded": 1.0,
        "max_score": 2.5,
        "reasoning": "Awarded 1 mark for mentioning prolonged therapeutic effect. Omitted biodegradability advantages."
      }}
    ]
  }},
  "highlights": [
    {{
      "text": "Exact text quote copied verbatim from student submission for Q6(a)",
      "question_number": "Q6(a)",
      "score_awarded": 1.0,
      "max_score": 2.5,
      "type": "strength",
      "comment": "Awarded 1 mark for mentioning prolonged therapeutic effect in (a). The response failed to address specific advantages (biodegradability, non-surgical) and disadvantages required by the rubric."
    }}
  ]
}}
"""
    system = "You are a precise, objective automated academic grading engine. Always respond strictly in valid JSON format."
    return call_agent(system, prompt, model, temperature=0.1, max_tokens=8000)


# ---------------------------------------------------------------------------
# Agent 3: Auditor Agent  (main: call_auditor_verification_agent)
# ---------------------------------------------------------------------------

def call_auditor_agent(
    question_no: str,
    rubric: str,
    max_score: float,
    student_answer: str,
    grader_result: Dict[str, Any],
    model: str,
):
    rubric_json = [{"question_number": question_no, "max_score": float(max_score), "criterion": rubric}]
    prompt = f"""
You are a Senior Academic Quality Auditor. Audit the following AI grading evaluation for fairness, accuracy, score bounds, and per-question score agreement.

Rubric:
{json.dumps(rubric_json, indent=2)}

Student Submission:
{student_answer}

Primary AI Evaluation Result:
{json.dumps(grader_result, indent=2)}

INDEPENDENCE REQUIREMENT:
Do NOT simply agree with or copy the Primary AI Evaluation.
Independently evaluate the student text per subquestion first using only:
1. Student Submission Text
2. Rubric Criteria & Model Answer

After determining your independent scores for each subquestion, compare your scores against the Primary Grader.

AUDIT TASKS:
1. Re-evaluate student text independently per rubric subquestion (e.g. Q6(a), Q6(b), Q8(a)).
2. Provide your independent score for EVERY subquestion in "auditor_breakdown".
3. Identify subquestion(s) where you have a material score disagreement (>= 1.0 mark) with the primary grader.
4. List materially conflicting subquestions in "conflicting_questions" array.
5. Set "audit_passed" to FALSE if you have a material subquestion disagreement (>= 1.0 mark) or if total score discrepancy is > 15%. Set TRUE if question scores align within 1.0 mark.
6. Provide a clear explanation in "discrepancy_note" stating which question(s) had conflict and why.

OUTPUT FORMAT (Respond ONLY in valid JSON matching this schema):
{{
  "audit_passed": false,
  "auditor_score": 7.5,
  "auditor_breakdown": [
    {{
      "question_number": "Q6(a)",
      "auditor_score": 2.5,
      "max_score": 2.5
    }}
  ],
  "conflicting_questions": ["Q6(b)"],
  "discrepancy_note": "Multi-Agent Conflict on Q6(b): Primary grader awarded 2.5 marks whereas auditor recommends 1.0 mark due to missing sol-to-gel mechanism."
}}
"""
    system = "You are a rigorous academic audit agent. Respond strictly in valid JSON."
    return call_agent(system, prompt, model, temperature=0.0, max_tokens=4000)


# ---------------------------------------------------------------------------
# Deterministic confidence engine, ported verbatim from main's confidence.py
# ---------------------------------------------------------------------------

def normalize_question_number(q_num: str) -> str:
    if not q_num:
        return ""
    return re.sub(r"\s+", "", str(q_num)).lower()


def evaluate_confidence_and_status(
    llm_result: Dict[str, Any],
    raw_text: str,
    total_max_score: float = 20.0
) -> Dict[str, Any]:
    """
    Confidence = (0.40 * Score_Agreement) + (0.40 * Question_Agreement) + (0.20 * Audit_Factor)
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

    score_agreement = max(0.0, 1.0 - (score_discrepancy / max_sc))

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
                    if diff >= 1.0:
                        material_conflicting_qs.append(q_num)
                else:
                    if norm_key in [normalize_question_number(q) for q in raw_conflicting_qs]:
                        q_agreed = 0.5
                        material_conflicting_qs.append(q_num)
                    else:
                        q_agreed = score_agreement

                question_agreements.append(q_agreed)

    question_agreement = sum(question_agreements) / len(question_agreements) if question_agreements else score_agreement

    audit_factor = 1.0 if (auditor_passed and len(material_conflicting_qs) == 0) else 0.5

    deterministic_confidence = round((0.40 * score_agreement) + (0.40 * question_agreement) + (0.20 * audit_factor), 2)
    final_confidence = max(0.05, min(1.0, deterministic_confidence))

    flag_reasons: List[str] = []
    q_str = f" on {', '.join(material_conflicting_qs)}" if material_conflicting_qs else ""
    discrepancy_pct = (score_discrepancy / max_sc) * 100.0

    if len(material_conflicting_qs) > 0:
        flag_reasons.append(f"Multi-Agent Conflict{q_str}: Material subquestion score discrepancy (>= 1.0 mark)")
    elif discrepancy_pct > (AUDIT_DISCREPANCY_THRESHOLD * 100.0):
        flag_reasons.append(f"Multi-Agent Conflict: Overall score discrepancy of {score_discrepancy:.1f} points ({discrepancy_pct:.1f}%)")

    if final_confidence < 0.65:
        flag_reasons.append(f"Low System Confidence ({final_confidence * 100:.0f}% < 65%)")

    score_pct = (primary_score / max_sc) * 100.0
    if 48.0 <= score_pct <= 52.0:
        flag_reasons.append("Borderline Pass/Fail Grade: Human verification recommended")

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
            "audit_factor": audit_factor,
        },
    }
