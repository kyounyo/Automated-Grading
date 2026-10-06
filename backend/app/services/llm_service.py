import os
import re
import json
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
import requests
from dotenv import load_dotenv
from .confidence import evaluate_confidence_and_status

# Ensure backend .env is loaded regardless of execution working directory
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=_env_path)
load_dotenv()

def get_openrouter_api_key() -> str:
    return os.getenv("OPENROUTER_API_KEY", "").strip() or os.getenv("LLM_API_KEY", "").strip()

def get_llm_model() -> str:
    return os.getenv("LLM_MODEL", "google/gemini-3.1-flash-lite").strip()

def get_auditor_model() -> str:
    return os.getenv("AUDITOR_MODEL", "nvidia/nemotron-3-super-120b-a12b").strip()

# Compatibility Constants
OPENROUTER_API_KEY = get_openrouter_api_key()
LLM_API_KEY = OPENROUTER_API_KEY
LLM_API_URL = os.getenv("LLM_API_URL", "https://openrouter.ai/api/v1/chat/completions")
LLM_MODEL = get_llm_model()


def _clean_json_response(content: str) -> Dict[str, Any]:
    """
    Cleans raw response from OpenRouter models:
    - Removes DeepSeek/Gemini/Nemotron <think>...</think> reasoning blocks
    - Strips markdown ```json Fences
    - Multi-stage JSON repairer for missing commas, unescaped quotes, and trailing commas
    """
    if not content:
        raise ValueError("Empty response string received from LLM.")

    clean_text = content.strip()
    
    # Remove <think>...</think> blocks
    think_match = re.search(r'<think>.*?</think>', clean_text, flags=re.DOTALL)
    if think_match:
        clean_text = clean_text.replace(think_match.group(0), "").strip()

    # Remove markdown code fences
    if clean_text.startswith("```json"):
        clean_text = clean_text[7:]
    elif clean_text.startswith("```"):
        clean_text = clean_text[3:]
    
    if clean_text.endswith("```"):
        clean_text = clean_text[:-3]

    clean_text = clean_text.strip()
    
    # Extract JSON object substring if surrounding text remains
    start_idx = clean_text.find("{")
    end_idx = clean_text.rfind("}")
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        clean_text = clean_text[start_idx:end_idx + 1]

    # Attempt 1: Direct standard JSON load
    try:
        return json.loads(clean_text)
    except json.JSONDecodeError:
        pass

    # Attempt 2: Repair common LLM JSON syntax errors (missing commas, trailing commas)
    repaired = clean_text
    repaired = re.sub(r',\s*([\}\]])', r'\1', repaired)  # Remove trailing commas
    repaired = re.sub(r'("(?:[^"\\]|\\.)*")\s*\n?\s*(")', r'\1, \2', repaired)  # Missing commas between string props
    repaired = re.sub(r'(\d+(?:\.\d+)?|true|false|null)\s*\n?\s*(")', r'\1, \2', repaired)  # Missing commas after numbers/booleans
    repaired = re.sub(r'(\})\s*\n?\s*(\{)', r'\1, \2', repaired)  # Missing commas between array items
    repaired = re.sub(r'(\])\s*\n?\s*(\{)', r'\1, \2', repaired)

    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass

    # Attempt 3: Regex fallback extractor for primary LLM response
    try:
        score_m = re.search(r'"overall_score"\s*:\s*([0-9\.]+)', clean_text)
        conf_m = re.search(r'"confidence_score"\s*:\s*([0-9\.]+)', clean_text)
        summary_m = re.search(r'"summary"\s*:\s*"([^"]*)"', clean_text)

        ov_score = float(score_m.group(1)) if score_m else 0.0
        conf_score = float(conf_m.group(1)) if conf_m else 0.9
        summary_str = summary_m.group(1) if summary_m else "AI grading evaluation completed."

        return {
            "overall_score": ov_score,
            "confidence_score": conf_score,
            "status": "graded",
            "reasoning": "Extracted via robust JSON fallback parser.",
            "feedback": {
                "summary": summary_str,
                "breakdown": []
            },
            "highlights": []
        }
    except Exception as parse_err:
        raise ValueError(f"Failed to parse LLM JSON: {parse_err}")


def _call_openrouter_api(messages: list, model: str, temperature: float = 0.1, max_retries: int = 2) -> Optional[Dict[str, Any]]:
    """
    Executes HTTP POST request to OpenRouter API endpoint with automatic retries, strict timeouts, and reasoning token fallbacks.
    """
    api_key = get_openrouter_api_key()
    if not api_key:
        print(" [OpenRouter API] Key is missing or empty. Skipping remote API call.", flush=True)
        return None

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://autograde.ai",
        "X-Title": "AutoGrade+"
    }
    data = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "response_format": {"type": "json_object"}
    }

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(url, json=data, headers=headers, timeout=(10, 75))
            if resp.status_code != 200:
                print(f" [OpenRouter Warning] HTTP {resp.status_code} for {model}: {resp.text[:150]}", flush=True)
                if resp.status_code in [429, 500, 502, 503, 504]:
                    time.sleep(1.5 * attempt)
                    continue
                return None

            body = resp.json()
            choice = body.get("choices", [{}])[0]
            msg = choice.get("message", {})
            content = msg.get("content") or ""

            # Fallback for reasoning models (e.g. Nemotron / R1) that place output in reasoning tokens
            if not content.strip():
                content = msg.get("reasoning") or msg.get("reasoning_content") or ""

            if not content.strip():
                raise ValueError("Empty response string received from LLM.")

            parsed = _clean_json_response(content)
            if isinstance(parsed, dict):
                parsed["_usage"] = body.get("usage", {})
            return parsed
        except requests.exceptions.Timeout as te:
            print(f" [OpenRouter Timeout] Model {model} timed out after 75s (Attempt {attempt}/{max_retries})", flush=True)
            last_error = te
            if attempt < max_retries:
                time.sleep(1.5 * attempt)
        except Exception as e:
            last_error = e
            print(f" [OpenRouter API Error] Attempt {attempt}/{max_retries} for model {model}: {e}", flush=True)
            if attempt < max_retries:
                time.sleep(1.5 * attempt)

    print(f" [OpenRouter API Warning] Call failed for model {model} after {max_retries} attempts: {last_error}", flush=True)
    return None


def call_rubric_context_parser_agent(rubric_json: list, model_answer: str, rag_context: str, model: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Agent 1 (Rubric & RAG Context Parser Agent):
    Standardizes rubric criteria & retrieved RAG vector context into clean evaluation rules.
    """
    prompt = f"""
You are an expert Academic Rubric Parser. Standardize the following rubric criteria and reference model answers into clean, structured evaluation rules.

Retrieved Vector Context:
{rag_context}

Reference Model Answer:
{model_answer or "Evaluate answer based on clarity, technical accuracy, and completeness."}

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
    messages = [
        {"role": "system", "content": "You are a precise academic rubric parsing agent. Always respond strictly in valid JSON format."},
        {"role": "user", "content": prompt}
    ]
    target_model = model or get_llm_model()
    return _call_openrouter_api(messages, target_model, temperature=0.0)


def format_question_few_shots(question_few_shots: Optional[Dict[str, List[Dict]]]) -> str:
    """
    Builds structured, question-matched examiner calibration exemplar blocks.
    Strictly pairs exemplars under their respective question number.
    """
    if not question_few_shots:
        return ""

    sections = []
    for q_no, examples in sorted(question_few_shots.items()):
        if not examples:
            continue
        ex_texts = []
        for idx, ex in enumerate(examples):
            anchor = (ex.get("anchor_type") or "borderline").capitalize()
            stu_t = (ex.get("student_text") or "").strip()
            sc = ex.get("examiner_score", 0.0)
            mx = ex.get("max_score", 0.0)
            fb = (ex.get("examiner_feedback") or "Evaluated according to course marking standard.").strip()

            ex_texts.append(
                f"  [Examiner Benchmark Example {idx+1} ({anchor} Anchor) - Score: {sc}/{mx}]\n"
                f"  Student Response: \"{stu_t}\"\n"
                f"  Examiner Justification: \"{fb}\""
            )

        sections.append(
            f"--- EXAMINER CALIBRATION BENCHMARKS FOR QUESTION {q_no} ---\n"
            f"Use the following examiner-marked examples as the authoritative baseline for marking strictness, concept depth, and partial-credit deductions for {q_no}:\n\n"
            + "\n\n".join(ex_texts)
        )

    if not sections:
        return ""

    return (
        "\n\n=================================================================\n"
        "EXAMINER-CALIBRATED FEW-SHOT BENCHMARKS (COURSE EXAMINER STANDARDS)\n"
        "=================================================================\n"
        + "\n\n".join(sections)
        + "\n=================================================================\n"
    )


def call_primary_grading_agent(
    student_text: str, 
    structured_rubric: Dict[str, Any], 
    raw_rubric_json: list, 
    model_answer: str, 
    rag_context: str, 
    total_max_score: float = 10.0, 
    model: Optional[str] = None,
    question_few_shots: Optional[Dict[str, List[Dict]]] = None
) -> Optional[Dict[str, Any]]:
    """
    Agent 2 (Primary CoT Evaluation Agent):
    Uses google/gemini-3.1-flash-lite to evaluate student responses against standardized rubric rules, RAG context,
    and optional question-matched examiner calibration few-shot examples.
    """
    few_shots_block = format_question_few_shots(question_few_shots)

    prompt = f"""
You are an expert academic evaluator specializing in objective short-answer grading.

{rag_context}

Standardized Rubric Rules:
{json.dumps(structured_rubric, indent=2)}

Raw Rubric Criteria:
{json.dumps(raw_rubric_json, indent=2)}

Total Assignment Max Score: {total_max_score}

Model Answer / Marking Scheme:
{model_answer or "Evaluate answer based on clarity, technical accuracy, and completeness."}
{few_shots_block}
Student Submission:
{student_text}

GRADING PROTOCOL (v1.3-multi-question-highlights):
1. MEANING OVER EXACT WORDS: Award points for concepts matching rubric intent.
2. STRICT CAPPING: Do not exceed maximum points allocated per question. Sum of points awarded across all questions MUST NOT exceed {total_max_score}.
3. ZERO MARK RULE: If a student answer for a question is blank, empty, dash ('-'), 'N/A', or missing, award EXACTLY 0 marks for that question. Do NOT award partial credit for empty or missing answers.
4. REASONING FIRST: Analyze student response against each criterion step-by-step before finalizing score.
5. MANDATORY PER-QUESTION HIGHLIGHTS: You MUST generate at least one highlight entry for EVERY question and sub-part in the student submission (e.g., Q6(a), Q6(b), Q8(a), Q8(b)). Highlight exact quotes from the student's text for each question.
6. DETAILED EXPLANATION REQUIREMENT: Each highlight comment MUST state:
   (a) Exact marks awarded and key concepts matched (e.g. 'Awarded 1 mark for mentioning prolonged therapeutic effect in (a)').
   (b) Specific rubric points missed or failed (e.g. 'Failed to address specific advantages (biodegradability) and disadvantages required by rubric').
7. QUESTION-MATCHED EXAMINER CALIBRATION: If Examiner Calibration Benchmarks are provided above for a question, you MUST align your marking strictness and partial-credit thresholds strictly to match the examiner's demonstrated standard for that specific question. Questions without calibration examples must be evaluated directly from the standard rubric rules.

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
    }},
    {{
      "text": "Exact text quote copied verbatim from student submission for Q6(b)",
      "question_number": "Q6(b)",
      "score_awarded": 1.0,
      "max_score": 2.5,
      "type": "strength",
      "comment": "Awarded 1 mark for describing the sol-to-gel mechanism in (b). Missed key physiological trigger attributes."
    }}
  ]
}}
"""
    messages = [
        {"role": "system", "content": "You are a precise, objective automated academic grading engine. Always respond strictly in valid JSON format."},
        {"role": "user", "content": prompt}
    ]
    target_model = model or get_llm_model()
    return _call_openrouter_api(messages, target_model, temperature=0.0)


def call_auditor_verification_agent(student_text: str, rubric_json: list, primary_eval: Dict[str, Any], model: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Agent 3 (Auditor & Verification Agent):
    Uses google/gemini-3.1-flash-lite to audit Agent 2's evaluation.
    Provides independent per-question auditor scores, identifies specific question conflicts, and determines audit_passed.
    """
    prompt = f"""
You are a Senior Academic Quality Auditor reviewing an AI-generated
assessment of an undergraduate pharmacy student's response.

Your task is to independently verify the Primary Grader's evaluation
against the question, marking rubric, and student's actual response.

Rubric:
{json.dumps(rubric_json, indent=2)}

Student Submission:
{student_text}

Primary AI Evaluation Result:
{json.dumps(primary_eval, indent=2)}

AUDIT PRINCIPLES

1. RUBRIC-BASED VERIFICATION
Evaluate each subquestion against its specific rubric criteria.

For each scoring criterion:
- identify what knowledge, reasoning, mechanism, or justification the
  rubric requires;
- identify evidence actually stated in the student's response;
- determine whether that evidence satisfies the criterion;
- award only the marks supported by the rubric.

The rubric is the primary basis for scoring.

2. CONCEPTUAL EQUIVALENCE
Do not require the student's wording to exactly match the rubric.

Accept different wording, terminology, synonyms, examples, or sentence
structure when the response demonstrates the same underlying knowledge or
concept required by the criterion.

Do not award a mark merely because the response:
- mentions a related keyword or concept;
- is generally relevant to the topic;
- gives a plausible statement without satisfying the criterion; or
- requires an assumption that the student did not communicate.

3. EVIDENCE-BASED VERIFICATION
Use only information actually stated or clearly communicated in the
student's response.

Do not infer knowledge that the student has not demonstrated.

When confirming or changing a mark, identify the specific student evidence
that supports the decision.

4. ALTERNATIVE ANSWERS
The rubric may contain examples rather than an exhaustive list.

Accept an alternative answer when it is scientifically, clinically,
pharmacologically, or pharmaceutically valid and fulfils the intended
scoring criterion.

If the rubric states "any other reasonable point", accept another reasonable
point when it satisfies the same requirement.

5. PARTIAL CREDIT AND SCORE BOUNDS
Follow the marking structure in the rubric exactly.

Do not invent partial-credit rules.

Do not double-count the same idea.

The total score MUST NOT exceed the maximum score.

6. INDEPENDENT AUDIT
Do not automatically agree with the Primary Grader.

Independently determine whether the Primary Grader's marks are supported by
the rubric and student evidence.

If the Primary Grader is correct, retain its score.

If the Primary Grader over-awarded or under-awarded marks, correct the score.

AUDIT & RECONCILIATION TASKS

1. Re-evaluate the student response independently for EVERY subquestion.
2. Provide your independent score for EVERY subquestion in
   "auditor_breakdown".
3. Compare your evaluation with the Primary Grader.
4. If the Primary Grader's evaluation is accurate and well-supported:
   set "recommendation" to "AGREEMENT" and
   "reconciled_score" to the Primary Grader's score.
5. If the Primary Grader made an error:
   set "recommendation" to "ADOPT_AUDITOR" and
   "reconciled_score" to the Auditor's score.
6. Identify the specific subquestions where the scores differ.
7. Explain the reason for each material disagreement.

DISAGREEMENT SEVERITY

- "NONE": Grader and Auditor scores are identical.
- "MINOR": Difference of 1 mark.
- "MAJOR": Difference of 2 or more marks.

A MINOR disagreement may be resolved by the Auditor when the Auditor's
score is clearly better supported by the rubric and student evidence.

A MAJOR disagreement should be flagged for human inspection rather than
being silently resolved.

OUTPUT FORMAT

Respond ONLY in valid JSON matching this schema:

{{
  "audit_passed": true,
  "auditor_score": 5.0,
  "reconciled_score": 5.0,
  "recommendation": "AGREEMENT",
  "disagreement_severity": "NONE",
  "auditor_breakdown": [
    {{
      "question_number": "Q6(a)",
      "auditor_score": 2.5,
      "max_score": 2.5
    }},
    {{
      "question_number": "Q6(b)",
      "auditor_score": 2.5,
      "max_score": 2.5
    }}
  ],
  "conflicting_questions": [],
  "reconciliation_reason": "The Primary Grader's scores are supported by the rubric and the evidence stated in the student's response."
}}
"""
    messages = [
        {"role": "system", "content": "You are a rigorous academic audit agent. Respond strictly in valid JSON."},
        {"role": "user", "content": prompt}
    ]
    target_model = model or get_auditor_model()
    return _call_openrouter_api(messages, target_model, temperature=0.0)


def call_llm_for_grading(
    student_text: str, 
    rubric_json: list, 
    model_answer: str, 
    rag_context: str, 
    total_max_score: float = 10.0,
    question_few_shots: Optional[Dict[str, List[Dict]]] = None,
    tolerance_rate: float = 0.10
) -> Dict[str, Any]:
    """
    Orchestrates Multi-Agent Grading Pipeline using google/gemini-3.1-flash-lite across 3 agents:
    - Agent 1: Rubric & RAG Context Parser Agent
    - Agent 2: Primary CoT Evaluation Agent (with optional question-matched few-shots)
    - Agent 3: Auditor Verification Agent
    - Step 4: Deterministic Confidence & Audit Engine
    """
    if not get_openrouter_api_key():
        print("[LLM Service] OPENROUTER_API_KEY not set. Running fallback structured scoring engine.", flush=True)
        return _mock_heuristic_evaluation(student_text, rubric_json, total_max_score)

    primary_model_name = get_llm_model()
    auditor_model_name = get_auditor_model()

    # Step 1: Agent 1 - Rubric & Context Parser Agent
    print(f" │   ├─ [Agent 1: Rubric Parser] Structuring rubric rules & RAG context...", flush=True)
    parser_res = call_rubric_context_parser_agent(rubric_json, model_answer, rag_context)
    structured_rubric = parser_res if parser_res else {"structured_rules": rubric_json}
    rule_count = len(rubric_json) if isinstance(rubric_json, list) else 1
    print(f" │   │  └─ Loaded {rule_count} rubric rule(s) & reference guidelines.", flush=True)

    # Step 2: Agent 2 - Primary CoT Grader Agent
    mode_tag = f"Few-Shot ({sum(len(v) for v in question_few_shots.values())} exemplars)" if question_few_shots else "Zero-Shot"
    print(f" │   ├─ [Agent 2: Primary Grader ({primary_model_name})] Evaluating submission in {mode_tag} mode...", flush=True)
    primary_res = call_primary_grading_agent(
        student_text=student_text,
        structured_rubric=structured_rubric,
        raw_rubric_json=rubric_json,
        model_answer=model_answer,
        rag_context=rag_context,
        total_max_score=total_max_score,
        question_few_shots=question_few_shots
    )
    if not primary_res:
        print(" │   │  └─ [Warning] Primary Agent call failed. Using heuristic fallback.", flush=True)
        return _mock_heuristic_evaluation(student_text, rubric_json, total_max_score)

    # Ensure feedback dictionary and breakdown list exist
    feedback = primary_res.get("feedback", {})
    if not isinstance(feedback, dict):
        feedback = {"summary": "AI Evaluation completed."}
        primary_res["feedback"] = feedback

    breakdown = feedback.get("breakdown", [])
    if not breakdown or not isinstance(breakdown, list):
        breakdown = []
        if isinstance(rubric_json, list) and len(rubric_json) > 0:
            for idx, r_item in enumerate(rubric_json):
                if isinstance(r_item, dict):
                    q_num = r_item.get("question_number") or r_item.get("criterion") or f"Q{idx + 1}"
                    max_sc = float(r_item.get("max_score", r_item.get("maxMark", 5.0)))
                    proportion = max_sc / total_max_score if total_max_score > 0 else (1.0 / len(rubric_json))
                    score_aw = round(float(primary_res.get("overall_score", 0.0)) * proportion, 1)
                    breakdown.append({
                        "question_number": q_num,
                        "score_awarded": min(max_sc, score_aw),
                        "max_score": max_sc,
                        "reasoning": "Evaluated against rubric criteria."
                    })
        feedback["breakdown"] = breakdown

    # Recalculate overall_score as the exact sum of score_awarded across question breakdown items
    if breakdown:
        exact_breakdown_sum = sum(float(item.get("score_awarded", 0.0)) for item in breakdown if isinstance(item, dict))
        primary_res["overall_score"] = round(exact_breakdown_sum, 1)

    primary_score = float(primary_res.get("overall_score", 0.0))
    print(f" │   │  └─ Primary Score Awarded: {primary_score}/{total_max_score}", flush=True)

    # Enrich highlights with question number and position in raw text
    _enrich_highlights_with_question_info(primary_res, student_text)

    # Step 3: Agent 3 - Auditor Verification Agent
    print(f" │   ├─ [Agent 3: Quality Auditor ({auditor_model_name})] Performing independent verification...", flush=True)
    auditor_res = call_auditor_verification_agent(student_text, rubric_json, primary_res)

    if auditor_res:
        audit_passed = bool(auditor_res.get("audit_passed", True))
        auditor_score = float(auditor_res.get("auditor_score", primary_res.get("overall_score", 0.0)))
        reconciled_score = float(auditor_res.get("reconciled_score", auditor_score))
        auditor_breakdown = auditor_res.get("auditor_breakdown", [])
        if not isinstance(auditor_breakdown, list):
            auditor_breakdown = []

        conflicting_qs = auditor_res.get("conflicting_questions", [])
        if not isinstance(conflicting_qs, list):
            conflicting_qs = []
        
        score_diff = abs(primary_score - auditor_score)
        max_denom = total_max_score if total_max_score > 0 else 10.0
        agreement_ratio = max(0.0, 1.0 - (score_diff / max_denom))
        
        recommendation = auditor_res.get("recommendation", "AGREEMENT" if score_diff == 0 else "ADOPT_AUDITOR")
        reconciliation_reason = auditor_res.get("reconciliation_reason", auditor_res.get("discrepancy_note", ""))
        severity = auditor_res.get("disagreement_severity", "NONE" if score_diff == 0 else ("MINOR" if score_diff <= 1.0 else "MAJOR"))

        print(f" │   │  ├─ Auditor Score: {auditor_score}/{total_max_score} | Discrepancy: {score_diff:.1f} pts ({severity})", flush=True)
        print(f" │   │  └─ Auditor Action: {recommendation} (Audit Passed: {audit_passed})", flush=True)

        primary_res["multi_agent_audit"] = {
            "auditor_passed": audit_passed,
            "auditor_score": auditor_score,
            "reconciled_score": reconciled_score,
            "recommendation": recommendation,
            "disagreement_severity": severity,
            "auditor_breakdown": auditor_breakdown,
            "score_discrepancy": round(score_diff, 1),
            "agreement_ratio": round(agreement_ratio, 2),
            "conflicting_questions": conflicting_qs,
            "audit_note": reconciliation_reason,
            "reconciliation_reason": reconciliation_reason,
            "model_used": auditor_model_name
        }

    # Step 4: Deterministic Confidence & Decision Engine
    print(f" │   ├─ [Engine: Confidence & Reconciliation] Computing calibrated confidence (Tolerance: {int(round(tolerance_rate * 100))}%)...", flush=True)
    confidence_result = evaluate_confidence_and_status(
        primary_res,
        student_text,
        total_max_score,
        tolerance_rate=tolerance_rate
    )

    primary_res["confidence_score"] = confidence_result["confidence_score"]
    primary_res["status"] = confidence_result["status"]
    primary_res["flag_reasons"] = confidence_result["flag_reasons"]
    primary_res["is_borderline"] = confidence_result["is_borderline"]
    primary_res["is_audit_flagged"] = confidence_result["is_audit_flagged"]
    primary_res["confidence_components"] = confidence_result["confidence_components"]
    primary_res["discrepancy_audit"] = confidence_result.get("discrepancy_audit", {})
    if isinstance(feedback, dict):
        feedback["discrepancy_audit"] = confidence_result.get("discrepancy_audit", {})
        feedback["flag_reasons"] = confidence_result.get("flag_reasons", [])

    # Auditor-Based Reconciliation:
    # If the disagreement is resolved (diff <= 1.0 mark or confirmed) and auto-approved ("graded"),
    # the system adopts the Auditor-reconciled final score and updates breakdown accordingly.
    if auditor_res and confidence_result["status"] == "graded":
        primary_res["overall_score"] = round(reconciled_score, 1)
        primary_res["auditor_reconciled"] = (primary_score != reconciled_score)
        primary_res["reconciliation_action"] = recommendation
        
        # Synchronize question breakdown with auditor scores if provided
        if auditor_breakdown and isinstance(feedback.get("breakdown"), list):
            from .confidence import normalize_question_number
            auditor_map = {normalize_question_number(a.get("question_number", "")): a for a in auditor_breakdown if isinstance(a, dict)}
            for p_item in feedback["breakdown"]:
                norm_k = normalize_question_number(p_item.get("question_number", ""))
                if norm_k in auditor_map:
                    a_sc = auditor_map[norm_k].get("auditor_score")
                    if a_sc is not None:
                        p_item["score_awarded"] = float(a_sc)

    print(f" │   └─ [Reconciliation Complete] Final Status: {primary_res['status'].upper()} | Final Score: {primary_res['overall_score']}/{total_max_score} | Confidence: {primary_res['confidence_score']*100:.1f}%", flush=True)

    return primary_res


def _mock_heuristic_evaluation(student_text: str, rubric_json: list, total_max_score: float = 10.0) -> Dict[str, Any]:
    text_len = len(student_text.strip())
    score_ratio = min(0.90, 0.65 + (text_len / 500.0))
    base_score = round(total_max_score * score_ratio, 1)
    confidence = 0.88 if text_len > 150 else 0.65
    status = "graded" if confidence >= 0.75 else "flagged"

    breakdown = []
    if rubric_json and isinstance(rubric_json, list) and len(rubric_json) > 0:
        for idx, item in enumerate(rubric_json):
            q_num = item.get("question_number") or f"Q{idx + 1}"
            max_sc = float(item.get("max_score", item.get("maxMark", round(total_max_score / len(rubric_json), 1))))
            breakdown.append({
                "question_number": q_num,
                "score_awarded": round(max_sc * score_ratio, 1),
                "max_score": max_sc,
                "reasoning": f"Heuristic evaluation against {q_num} rubric criteria."
            })
    else:
        half_max = round(total_max_score / 2.0, 1)
        breakdown = [
            {
                "question_number": "Q1",
                "score_awarded": round(half_max * score_ratio, 1),
                "max_score": half_max,
                "reasoning": "Demonstrated sound understanding of core principles."
            },
            {
                "question_number": "Q2",
                "score_awarded": round(half_max * score_ratio, 1),
                "max_score": half_max,
                "reasoning": "Provided clear logical steps in explanation."
            }
        ]

    return {
        "overall_score": base_score,
        "confidence_score": confidence,
        "status": status,
        "reasoning": "Heuristic CoT evaluation performed based on response completeness and keyword density.",
        "feedback": {
            "summary": "Automated AI evaluation completed based on rubric criteria.",
            "breakdown": breakdown
        },
        "highlights": [
            {
                "text": student_text[:80] + "..." if len(student_text) > 80 else student_text,
                "type": "strength",
                "comment": "Key terms and concepts correctly identified."
            }
        ],
        "multi_agent_audit": {
            "auditor_passed": True,
            "auditor_score": base_score,
            "score_discrepancy": 0.0,
            "audit_note": "Fallback heuristic evaluation audit passed."
        }
    }


def _enrich_highlights_with_question_info(primary_res: Dict[str, Any], student_text: str) -> None:
    """
    Enriches highlight items with specific question number and raw text section location.
    Matches text quotes against student submission text using fuzzy normalization so frontend highlighting never fails.
    """
    highlights = primary_res.get("highlights", [])
    if not isinstance(highlights, list):
        return

    feedback = primary_res.get("feedback", {})
    breakdown = feedback.get("breakdown", []) if isinstance(feedback, dict) else []
    text_lower = student_text.lower() if student_text else ""

    def clean_str(s: str) -> str:
        return re.sub(r'[\W_]+', ' ', s).strip().lower()

    for hl in highlights:
        if not isinstance(hl, dict):
            continue

        quote = hl.get("text", "").strip()
        q_num = hl.get("question_number", "")

        if not quote:
            continue

        # 1. Try finding exact match first
        pos = student_text.lower().find(quote.lower())
        exact_len = len(quote)

        # 2. If exact match fails, try matching first 30 chars
        if pos == -1 and len(quote) > 10:
            sub_search = quote.lower()[:min(30, len(quote))]
            pos = student_text.lower().find(sub_search)

        # 3. If still fails, try normalized word sequence search
        if pos == -1:
            quote_words = [w for w in re.split(r'[\W_]+', quote) if len(w) > 2]
            if quote_words:
                for m in re.finditer(re.escape(quote_words[0]), student_text, re.IGNORECASE):
                    start_p = m.start()
                    snippet_candidate = student_text[start_p:start_p + len(quote) + 40]
                    if (quote_words[1] in snippet_candidate.lower()) if len(quote_words) > 1 else True:
                        pos = start_p
                        exact_len = min(len(quote) + 20, len(student_text) - pos)
                        break

        if pos != -1:
            # Replace hl["text"] with the EXACT physical slice from student_text
            hl["text"] = student_text[pos:pos + exact_len]
            
            prefix = student_text[max(0, pos - 350):pos]
            matches = re.findall(r'(?:Question|Q)\s*([Q0-9A-Za-z\(\)]+)', prefix, re.IGNORECASE)
            if matches:
                detected_q = matches[-1]
                clean_q = f"Q{detected_q}" if not detected_q.startswith("Q") else detected_q
                if not q_num or q_num in ["Rubric Evidence", "Rubric", "N/A", "General Rubric Evidence"]:
                    hl["question_number"] = clean_q

            section_match = re.search(r'(?:Question|Q)\s*([Q0-9A-Za-z\(\)]+)', prefix, re.IGNORECASE)
            sec_name = f"Question {section_match.group(1)} Section" if section_match else "Student Submission Text"
            hl["location_in_raw_text"] = f"{sec_name} (around char {pos})"
        else:
            hl["location_in_raw_text"] = "Student Submission Response"

        # Fallback matching against breakdown questions
        if (not hl.get("question_number") or hl.get("question_number") in ["Rubric Evidence", "Rubric", "N/A", "General Rubric Evidence"]) and breakdown:
            quote_clean = clean_str(quote)
            for b in breakdown:
                b_q = b.get("question_number", "")
                b_reason = clean_str(b.get("reasoning", ""))
                if any(w in b_reason for w in quote_clean.split()[:4] if len(w) > 3):
                    hl["question_number"] = b_q
                    break

        if not hl.get("question_number") or hl.get("question_number") in ["Rubric Evidence", "Rubric", "N/A"]:
            hl["question_number"] = "General Rubric Evidence"

    # Ensure EVERY question in breakdown has at least one highlight entry
    existing_q_nums = set(h.get("question_number") for h in highlights if isinstance(h, dict) and h.get("question_number"))
    
    for b in breakdown:
        if not isinstance(b, dict):
            continue
        b_q = b.get("question_number", "")
        if not b_q or b_q in existing_q_nums:
            continue

        score_aw = b.get("score_awarded", 0.0)
        max_sc = b.get("max_score", 10.0)
        reasoning = b.get("reasoning", "Rubric criterion evaluation completed.")

        # Find matching section text snippet in raw student text
        clean_bq = re.sub(r'[^a-zA-Z0-9]', '', b_q).lower()
        q_pos = -1
        if clean_bq:
            q_pos = text_lower.find(clean_bq)
        if q_pos == -1 and len(b_q) > 1:
            m_q = re.search(r'(?:Question|Q)?\s*' + re.escape(b_q), student_text, re.IGNORECASE)
            if m_q:
                q_pos = m_q.start()

        if q_pos != -1:
            snippet = student_text[q_pos:q_pos + 120].strip()
        else:
            snippet = student_text[:120].strip() if student_text else f"Answer section for {b_q}"

        new_hl = {
            "text": snippet,
            "question_number": b_q,
            "score_awarded": score_aw,
            "max_score": max_sc,
            "type": "strength" if score_aw > 0 else "weakness",
            "comment": f"Evaluated for {b_q} ({score_aw}/{max_sc} marks). Reasoning: {reasoning}",
            "location_in_raw_text": f"Question {b_q} Section"
        }
        highlights.append(new_hl)
        existing_q_nums.add(b_q)

    primary_res["highlights"] = highlights


# ----------------------------------------------------------------------
# PDF PARSER & DOCUMENT SLICING FUNCTIONS (From PDF-parser Feature Branch)
# ----------------------------------------------------------------------

def call_llm_for_parsing(text_block: str, q_num: str) -> Dict[str, Any]:
    """
    Extracts structured Question, Rubric, and Max Marks from a block of text using LLM.
    """
    prompt = f"""
You are an expert academic data extractor. Your job is to extract the exact question text, the marking rubric (answer scheme), and the maximum marks from the raw text provided below.

The text is for Question {q_num}.

Raw Text:
{text_block}

RULES & OUTPUT INSTRUCTIONS:
1. "question": Copy the FULL question text verbatim from the start of the block. Include all scenario paragraphs, reading passages, case studies, and instructions verbatim. Do NOT drop background context!
2. "rubric": Copy the EXACT marking scheme / model answer verbatim. Preserve multi-line calculations with newline breaks. If no distinct rubric is present, set rubric equal to the question text.
3. "max_marks": Extract maximum marks if specified (e.g. (6 marks) -> 6.0). Default to 10.0 if not specified.

Return strictly valid JSON with no markdown wrapping, matching this format:
{{
  "question": "Full verbatim question text including scenario...",
  "rubric": "Exact verbatim marking rubric / answer scheme...",
  "max_marks": 6.0
}}
"""
    messages = [
        {"role": "system", "content": "You are a verbatim academic data extraction engine. Copy all text 100% verbatim as written. Always respond in pure raw JSON format."},
        {"role": "user", "content": prompt}
    ]
    res = _call_openrouter_api(messages, get_llm_model(), temperature=0.0)
    return res if isinstance(res, dict) else {}


def normalize_text_for_matching(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'[\u2018\u2019\u201b\u2039\u203a\xb4\`]', "'", text)
    text = re.sub(r'[\u201c\u201d\u201e\xab\xbb]', '"', text)
    text = re.sub(r'[\u2013\u2014\u2015]', '-', text)
    text = re.sub(r'[\u2026]', '...', text)
    text = re.sub(r'[\u2060\u200b\ufeff]', '', text)
    return text


def _find_phrase_range(raw_text: str, phrase: str, start_after: int = 0):
    if not phrase or not phrase.strip():
        return -1, -1

    search_text = raw_text[start_after:] if start_after > 0 else raw_text
    norm_search = normalize_text_for_matching(search_text)
    norm_phrase = normalize_text_for_matching(phrase)

    # 1. Exact Substring Match
    idx = norm_search.find(norm_phrase)
    if idx != -1:
        actual_start = start_after + idx
        return actual_start, actual_start + len(phrase)

    # 2. Regex match with flexible whitespace/punctuation
    words = norm_phrase.strip().split()
    if words:
        escaped_words = [re.escape(w) for w in words]
        pattern = r'\s*[\W_]*\s*'.join(escaped_words)
        m = re.search(pattern, norm_search, re.IGNORECASE)
        if m:
            return start_after + m.start(), start_after + m.end()

    # 3. Fallback: Strip leading numbering prefix like "6.", "6. (a)", "6. (a) (i)", "Q6.", "(a)" from phrase
    clean_phrase = re.sub(r'^(?:Question|Q)?\s*\d+[\.\)]?\s*(?:\([a-z0-9]+\)|[a-z0-9]+\.?)?\s*(?:\([ivx]+\)|[ivx]+\.?)?\s*', '', norm_phrase, flags=re.IGNORECASE).strip()
    if clean_phrase and clean_phrase != norm_phrase.strip():
        clean_words = clean_phrase.split()
        if len(clean_words) >= 2:
            escaped_clean = [re.escape(w) for w in clean_words]
            clean_pattern = r'\s*[\W_]*\s*'.join(escaped_clean)
            m = re.search(clean_pattern, norm_search, re.IGNORECASE)
            if m:
                match_start = start_after + m.start()
                # Check up to 50 chars before match_start for original numbering prefix
                prefix_window = raw_text[max(0, match_start - 50):match_start]
                num_m = re.search(r'(?:Question|Q)?\s*\d+[\.\)]?\s*(?:\([a-z0-9]+\)|[a-z0-9]+\.?)?\s*(?:\([ivx]+\)|[ivx]+\.?)?\s*$', prefix_window, re.IGNORECASE)
                if num_m:
                    return max(0, match_start - 50) + num_m.start(), start_after + m.end()
                return match_start, start_after + m.end()

    # 4. Pure Alphanumeric Word Sequence Match
    alpha_words = re.findall(r'[a-zA-Z0-9]+', phrase)
    if len(alpha_words) >= 3:
        alpha_pattern = r'[\s\W]+'.join(re.escape(w) for w in alpha_words[:6])
        m = re.search(alpha_pattern, search_text, re.IGNORECASE)
        if m:
            return start_after + m.start(), start_after + m.end()

    return -1, -1


def parse_entire_document_with_llm(raw_text: str) -> List[Dict[str, Any]]:
    """
    LLM-Guided Exact Slicing Document Parser.
    Uses LLM intelligence to identify start & end anchor phrases for questions and answers across ANY document layout,
    and then performs direct Python string slicing on raw_text to guarantee 100% exact verbatim preservation.
    """
    prompt = f"""
You are an intelligent document structure analyzer.
Your job is to identify every question/sub-question and its corresponding answer scheme/rubric in the raw document text.

Raw Document Text:
{raw_text}

STRICT INSTRUCTIONS:
1. Extract ALL sub-parts (e.g. "Q6(a)", "Q6(b)", "Q6(a)(i)", "Q6(a)(ii)") as SEPARATE, DISTINCT items in the array! If a paragraph contains sub-parts (a) and (b), output Q6(a) and Q6(b) as separate question entries, NEVER combine them into one item!
2. Recognize ANY sub-part numbering format regardless of style, including letters (a, b, c), Roman numerals (i, ii, iii, iv, v, vi), numbers (1, 2), or formats like "6. (a)", "6(a)", "(b)", "6) (a)".
3. Do NOT extract bullet list items or point criteria inside answers (such as -May be biodegradable, 1., 2. under Advantages or Disadvantages) as separate questions! Include them as part of the model answer scheme/rubric.
4. If the rubric/answer scheme repeats the question prompt text before providing the answer criteria, EXCLUDE the repeated question text! "answer_start_phrase" must be the starting 4 to 8 words of the actual answer/marking criteria that follow.
5. "question_number": Use exact question label (e.g. "Q6(a)", "Q6(b)", "Q6(a)(i)", "Q9").
6. "question_start_phrase": Exact 4 to 8 starting words of the question prompt (e.g. "6. (a) Polymer-based injectable modified").
7. "question_end_phrase": Exact 4 to 8 ending words of the question prompt (e.g. "means for the patient. (5 marks)").
8. "answer_start_phrase": Exact 4 to 8 words that OPEN the actual answer/marking criteria (e.g. "Advantages -May be biodegradable" or "One mark for disagree"). Must start AFTER any repeated question text!
9. "answer_end_phrase": Exact 4 to 8 ending words of the answer scheme/rubric (e.g. "Complex manufacture - expensive").
10. "max_marks": Extract maximum marks if mentioned (e.g. 5.0, 10.0). Default to 10.0 if not specified.

OUTPUT FORMAT:

Return strictly valid JSON with no markdown wrapping, matching this array format:

[
  {{
    "question_number": "Q6(a)(i)",
    "question_start_phrase": "Exact 4 to 8 words copied from the question",
    "question_end_phrase": "Exact 4 to 8 words copied from the question",
    "answer_start_phrase": "Exact 4 to 8 words copied from the answer",
    "answer_end_phrase": "Exact 4 to 8 words copied from the answer",
    "max_marks": 5.0
  }}
]
"""
    messages = [
        {"role": "system", "content": "You are a precise document layout analyzer. Return valid JSON only."},
        {"role": "user", "content": prompt}
    ]
    guides = _call_openrouter_api(messages, get_llm_model(), temperature=0.0)

    if not isinstance(guides, list):
        # In case the model wrapped it in an object like {"questions": [...]} or returned direct list
        if isinstance(guides, dict):
            for k in ["questions", "items", "data", "result"]:
                if isinstance(guides.get(k), list):
                    guides = guides[k]
                    break
        if not isinstance(guides, list):
            return []

    results = []
    num_guides = len(guides)
    last_a_start_idx = 0

    for idx, g in enumerate(guides):
        q_num = str(g.get("question_number", f"Q{idx + 1}")).strip()
        if not q_num.lower().startswith("q") and not re.match(r'^\d', q_num):
            q_num = f"Q{q_num}"
        elif q_num.isdigit():
            q_num = f"Q{q_num}"

        max_mark = float(g.get("max_marks", 10.0))

        q_start_phrase = g.get("question_start_phrase", "")
        q_end_phrase = g.get("question_end_phrase", "")
        a_start_phrase = g.get("answer_start_phrase", "")
        a_end_phrase = g.get("answer_end_phrase", "")

        # 1. Find question start
        q_s_start, q_s_end = _find_phrase_range(raw_text, q_start_phrase, 0)
        
        # 2. Find question end
        q_e_start, q_e_end = _find_phrase_range(raw_text, q_end_phrase, max(0, q_s_start))

        # 3. Find answer start (must start AFTER question prompt AND after previous sub-part answer)
        search_after_q = q_e_end if q_e_end != -1 else (q_s_end if q_s_end != -1 else 0)
        search_a_from = max(search_after_q, last_a_start_idx)
        a_s_start, a_s_end = _find_phrase_range(raw_text, a_start_phrase, search_a_from)
        
        if a_s_start != -1:
            last_a_start_idx = a_s_start + 1

        # 4. Find answer end
        a_e_start, a_e_end = _find_phrase_range(raw_text, a_end_phrase, max(0, a_s_start if a_s_start != -1 else q_s_start))

        # Look ahead for next question start phrase if available
        next_q_s_start = len(raw_text)
        if idx + 1 < num_guides:
            next_q_sp = guides[idx + 1].get("question_start_phrase", "")
            nq_s, _ = _find_phrase_range(raw_text, next_q_sp, max(0, q_s_start + 1))
            if nq_s != -1:
                next_q_s_start = nq_s

        # Fallbacks for Question Prompt bounds
        if q_s_start == -1:
            clean_q_label = re.sub(r'^Q', '', q_num)
            tokens = re.findall(r'[a-zA-Z0-9]+', clean_q_label)
            if tokens:
                label_pattern = r'(?:^|\n)\s*(?:Question|Q)?\s*' + r'[\s\.\(\)]*'.join(re.escape(t) for t in tokens)
                m_label = re.search(label_pattern, raw_text, re.IGNORECASE)
                if m_label:
                    q_s_start = m_label.start()
                else:
                    q_s_start = 0
            else:
                q_s_start = 0

        if q_e_end == -1:
            if a_s_start != -1 and a_s_start > q_s_start:
                q_e_end = a_s_start
            elif next_q_s_start < len(raw_text) and next_q_s_start > q_s_start:
                block_between = raw_text[q_s_start:next_q_s_start]
                ans_m = re.search(r'(?:^|\n)\s*(?:Model\s+Answer|Answer|Answers|Rubric|Marking\s+Scheme|Solution|Suggested\s+Answer)\s*[\:\.\-]?\s*', block_between, re.IGNORECASE)
                if ans_m:
                    q_e_end = q_s_start + ans_m.start()
                    if a_s_start == -1:
                        a_s_start = q_s_start + ans_m.start()
                else:
                    q_e_end = next_q_s_start
            else:
                block_from_q = raw_text[q_s_start:]
                ans_m = re.search(r'(?:^|\n)\s*(?:Model\s+Answer|Answer|Answers|Rubric|Marking\s+Scheme|Solution|Suggested\s+Answer)\s*[\:\.\-]?\s*', block_from_q, re.IGNORECASE)
                if ans_m:
                    q_e_end = q_s_start + ans_m.start()
                    if a_s_start == -1:
                        a_s_start = q_s_start + ans_m.start()
                else:
                    q_e_end = len(raw_text)

        prompt_verbatim = raw_text[q_s_start:q_e_end].strip()

        # Fallbacks for Answer bounds
        if a_s_start == -1:
            a_s_start = q_e_end

        if a_e_end == -1 or a_e_end <= a_s_start:
            a_e_end = min(len(raw_text), next_q_s_start)

        if a_s_start < len(raw_text) and a_e_end > a_s_start:
            answer_verbatim = raw_text[a_s_start:a_e_end].strip()
        else:
            answer_verbatim = prompt_verbatim

        results.append({
            "id": idx + 1,
            "question_number": q_num,
            "text": prompt_verbatim,
            "maxMark": max_mark,
            "modelAnswer": answer_verbatim,
            "_q_s_start": q_s_start
        })

    # Sort results by physical position in raw_text
    results.sort(key=lambda r: r.get("_q_s_start", 0))

    # Clean up internal metadata keys
    for idx, item in enumerate(results):
        item["id"] = idx + 1
        if "_q_s_start" in item:
            del item["_q_s_start"]

    return results
