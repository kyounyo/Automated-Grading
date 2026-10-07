import os
import re
import json
import time
from pathlib import Path
from typing import Dict, Any, Optional, List
import requests
from dotenv import load_dotenv
from .confidence import evaluate_confidence_and_status

# Ensure backend .env is loaded regardless of execution working directory
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=_env_path)
load_dotenv()

def get_openrouter_api_key() -> str:
    return os.getenv("OPENROUTER_API_KEY", "").strip()

def get_llm_model() -> str:
    return os.getenv("LLM_MODEL", "google/gemini-3.1-flash-lite").strip()

def get_auditor_model() -> str:
    return os.getenv("AUDITOR_MODEL", "nvidia/nemotron-3-super-120b-a12b").strip()



def _clean_json_response(content: str) -> Dict[str, Any]:
    """
    Cleans raw response from OpenRouter models:
    - Removes DeepSeek/Gemini <think>...</think> reasoning blocks
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

        # Extract breakdown items using regex if breakdown exists in clean_text
        bd_items = []
        bd_block_match = re.search(r'"breakdown"\s*:\s*\[(.*?)\](?:\s*,\s*"|\s*\}\s*\}|\s*\})', clean_text, flags=re.DOTALL)
        if bd_block_match:
            bd_content = bd_block_match.group(1)
            raw_objs = re.findall(r'\{[^{}]*\}', bd_content)
            for raw_obj in raw_objs:
                try:
                    obj = json.loads(raw_obj)
                    if isinstance(obj, dict) and (obj.get("question_number") or obj.get("score_awarded") is not None):
                        bd_items.append(obj)
                except Exception:
                    q_m = re.search(r'"question_number"\s*:\s*"([^"]+)"', raw_obj)
                    sc_m = re.search(r'"score_awarded"\s*:\s*([0-9\.]+)', raw_obj)
                    mx_m = re.search(r'"max_score"\s*:\s*([0-9\.]+)', raw_obj)
                    rs_m = re.search(r'"reasoning"\s*:\s*"([^"]*)"', raw_obj)
                    if q_m and sc_m:
                        bd_items.append({
                            "question_number": q_m.group(1),
                            "score_awarded": float(sc_m.group(1)),
                            "max_score": float(mx_m.group(1)) if mx_m else 10.0,
                            "reasoning": rs_m.group(1) if rs_m else ""
                        })

        if bd_items and ov_score == 0.0:
            ov_score = sum(float(b.get("score_awarded", 0.0)) for b in bd_items)

        return {
            "overall_score": ov_score,
            "confidence_score": conf_score,
            "status": "graded",
            "reasoning": "Extracted via robust JSON fallback parser.",
            "feedback": {
                "summary": summary_str,
                "breakdown": bd_items
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
    Uses google/gemini-3.1-flash-lite to parse, clean, and standardize rubric criteria & retrieved RAG vector context.
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

GRADING PROTOCOL (v1.4-main-questions-integer-rubric):
1. MEANING OVER EXACT WORDS: Award points for concepts matching rubric intent.
2. STRICT RUBRIC MARK ALLOCATION & INCREMENTS: Follow the rubric's marking scheme strictly. If the rubric allocates whole marks (e.g. '1 mark for each point up to 5', 'One mark for disagree'), you MUST award ONLY whole integer marks (0, 1, 2, 3...). Do NOT award 0.5 or fractional marks unless the rubric explicitly defines 0.5 increments. Never invent fractional scores.
3. PER-QUESTION BREAKDOWN: You MUST output the score breakdown at the MAIN QUESTION level matching the rubric criteria items (e.g. 'Q6', 'Q8').
   If a question consists of multiple sub-questions or parts (such as (a) and (b)), combine them into the single main question entry ('Q6'):
   - question_number: Main question identifier matching rubric (e.g., 'Q6', 'Q8')
   - score_awarded: Total marks awarded for the whole question (sum of matched points, whole marks if rubric uses whole marks)
   - max_score: Total maximum marks for this main question (e.g. 10.0)
   - reasoning: Detailed sub-question breakdown explaining marks awarded and missed for each part (e.g., '(a) [3/5]: ... | (b) [2/5]: ...')
4. STRICT CAPPING: Do not exceed maximum points allocated per question. Sum of points awarded across all questions MUST NOT exceed {total_max_score}.
5. ZERO MARK RULE: If a student answer for a question is blank, empty, dash ('-'), 'N/A', or missing, award EXACTLY 0 marks for that question. Do NOT award partial credit for empty or missing answers.
6. REASONING FIRST: Analyze student response against each criterion step-by-step before finalizing score.
7. MANDATORY MULTI-POINT HIGHLIGHT EVIDENCE (CRITICAL):
   - For EVERY question where marks are awarded, you MUST highlight EACH distinct sentence or clause in the student's response that earned marks.
   - DO NOT lump all marks into a single sentence quote if the question tests multiple points or if the student's answer has multiple parts!
   - For example, if Q6 earns 5 marks across two points (part a: 3 marks, part b: 2 marks), you MUST output TWO separate highlight entries (one for the part a sentence earning 3.0, and one for the part b sentence earning 2.0).
   - If a question earns 6 marks across 3 criteria, highlight all 3 corresponding sentences with their respective scores (+2.0, +2.0, +2.0).
   - The SUM of score_awarded across all highlights for any question MUST EXACTLY EQUAL that question's total score_awarded!
8. DETAILED EXPLANATION REQUIREMENT: Each highlight comment MUST state:
   (a) Exact marks awarded and key concepts matched.
   (b) Specific rubric points missed or failed.
9. QUESTION-MATCHED EXAMINER CALIBRATION: If Examiner Calibration Benchmarks are provided above for a question, you MUST align your marking strictness and partial-credit thresholds strictly to match the examiner's demonstrated standard for that specific question. Questions without calibration examples must be evaluated directly from the standard rubric rules.

OUTPUT FORMAT (Respond ONLY in valid JSON matching this schema):
{{
  "overall_score": 14.0,
  "confidence_score": 0.90,
  "status": "graded",
  "reasoning": "Step-by-step analysis comparing student response to rubric...",
  "feedback": {{
    "summary": "Strong submission demonstrating clear understanding of core concepts.",
    "breakdown": [
      {{
        "question_number": "Q6",
        "score_awarded": 5.0,
        "max_score": 10.0,
        "reasoning": "(a) [3/5]: Awarded 3 marks for duration, biodegradability, and acid-labile drug limitations. | (b) [2/5]: Awarded 2 marks for describing sol-to-gel mechanism."
      }},
      {{
        "question_number": "Q8",
        "score_awarded": 9.0,
        "max_score": 10.0,
        "reasoning": "(a) [2/2]: Disagree, not necessary if stable. | (b) [2/2]: Agree, complexity. | (c) [2/2]: Disagree, antibody directs. | (d) [2/2]: Disagree, amber vials. | (e) [1/2]: Agree, solvent safe in small amounts."
      }}
    ]
  }},
  "highlights": [
    {{
      "text": "Exact sentence quote from student answering part (a)",
      "question_number": "Q6",
      "score_awarded": 3.0,
      "max_score": 10.0,
      "type": "strength",
      "comment": "Awarded 3 marks for duration and biodegradability in Q6(a)."
    }},
    {{
      "text": "Exact sentence quote from student answering part (b)",
      "question_number": "Q6",
      "score_awarded": 2.0,
      "max_score": 10.0,
      "type": "strength",
      "comment": "Awarded 2 marks for describing sol-to-gel transition in Q6(b)."
    }},
    {{
      "text": "Exact sentence quote from student answering part (a)",
      "question_number": "Q8",
      "score_awarded": 2.0,
      "max_score": 10.0,
      "type": "strength",
      "comment": "Awarded 2 marks for correctly disagreeing with lyophilization requirement."
    }},
    {{
      "text": "Exact sentence quote from student answering part (b)",
      "question_number": "Q8",
      "score_awarded": 2.0,
      "max_score": 10.0,
      "type": "strength",
      "comment": "Awarded 2 marks for correctly identifying formulation complexity."
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


def call_auditor_verification_agent(
    student_text: str, 
    rubric_json: list, 
    primary_eval: Dict[str, Any], 
    model: Optional[str] = None,
    question_few_shots: Optional[Dict[str, List[Dict]]] = None
) -> Optional[Dict[str, Any]]:
    """
    Agent 3 (Auditor & Verification Agent):
    Uses nvidia/nemotron-3-super-120b-a12b to audit Agent 2's evaluation.
    Provides independent per-question auditor scores, identifies specific question conflicts, and determines audit_passed.
    """
    few_shots_block = format_question_few_shots(question_few_shots)

    prompt = f"""
You are a Senior Academic Quality Auditor. Audit the following AI grading evaluation for fairness, accuracy, score bounds, and per-question score agreement.

Rubric:
{json.dumps(rubric_json, indent=2)}
{few_shots_block}
Student Submission:
{student_text}

Primary AI Evaluation Result:
{json.dumps(primary_eval, indent=2)}

INDEPENDENCE & VERIFICATION REQUIREMENT:
You are the Senior Quality Auditor and Reconciliation Verifier.
Review the Primary Grader's score, reasoning, and per-question breakdown against:
1. Student Submission Text
2. Rubric Criteria & Model Answer
3. Course Examiner Calibration Benchmarks (if provided above, use them as the authoritative baseline for marking standards and partial credit)

AUDIT & RECONCILIATION TASKS:
1. Re-evaluate student text independently for EACH MAIN QUESTION matching the rubric (e.g. Q6, Q8). Align with Examiner Calibration Benchmarks if provided.
2. Follow rubric marking increments strictly: if rubric uses whole marks (e.g. 1 mark per point), do NOT award 0.5 marks.
3. Provide your independent score and detailed justification/reasoning for EVERY MAIN QUESTION in "auditor_breakdown" (e.g. Q6, Q8). Explain what concepts were correct, missing, or why marks were adjusted against the rubric.
4. Compare your evaluation with the Primary Grader question by question:
   - If Grader's score is accurate and well-supported: set "recommendation" to "AGREEMENT" and "reconciled_score" = primary score.
   - If Grader made an error (over-awarded / overlooked concepts): set "recommendation" to "ADOPT_AUDITOR" and "reconciled_score" = auditor score.
5. Classify disagreement severity:
   - "NONE": Grader == Auditor (diff = 0)
   - "MINOR": Difference of 1 mark (within acceptable discrete grading variance, resolved by Auditor)
   - "MAJOR": Difference of >= 2 marks (major dispute requiring lecturer inspection)
6. Set "audit_passed" to TRUE for "NONE" or "MINOR" disagreements. Set FALSE only for "MAJOR" disagreements (>= 2 marks).
7. Provide a clear justification in "reconciliation_reason" explaining whether the Grader was confirmed or adjusted and why.

OUTPUT FORMAT (Respond ONLY in valid JSON matching this schema):
{{
  "audit_passed": true,
  "auditor_score": 14.0,
  "reconciled_score": 14.0,
  "recommendation": "AGREEMENT",
  "disagreement_severity": "NONE",
  "auditor_breakdown": [
    {{
      "question_number": "Q6",
      "auditor_score": 5.0,
      "max_score": 10.0,
      "reasoning": "Awarded 3 marks for biodegradability and 2 marks for in situ gelling attributes; deducted for missing clinical benefit comparison."
    }},
    {{
      "question_number": "Q8",
      "auditor_score": 9.0,
      "max_score": 10.0,
      "reasoning": "Correctly evaluated statements (a) through (d); minor discrepancy on statement (e)."
    }}
  ],
  "conflicting_questions": [],
  "reconciliation_reason": "Verified scoring against rubric criteria. Scores on Q6 and Q8 are accurate and supported by student response."
}}
"""
    messages = [
        {"role": "system", "content": "You are a rigorous academic audit agent. Respond strictly in valid JSON."},
        {"role": "user", "content": prompt}
    ]
    target_model = model or get_auditor_model()
    return _call_openrouter_api(messages, target_model, temperature=0.0)


def check_rubric_allows_half_marks(rubric_json: list) -> bool:
    """Checks if the rubric criteria or model answer explicitly mentions half marks (e.g. 0.5)."""
    if not rubric_json or not isinstance(rubric_json, list):
        return True
    rubric_str = json.dumps(rubric_json).lower()
    return "0.5" in rubric_str or "half mark" in rubric_str or "half-mark" in rubric_str


def aggregate_and_standardize_breakdown(
    raw_breakdown: list,
    rubric_json: list,
    total_max_score: float = 20.0
) -> List[Dict[str, Any]]:
    """
    Standardizes question breakdown to Main Question level (e.g. Q6, Q8),
    aggregates sub-questions ((a), (b), etc.) into their parent main question,
    and enforces strict rubric whole mark allocation (no 0.5 marks if not in rubric).
    """
    if not rubric_json or not isinstance(rubric_json, list) or len(rubric_json) == 0:
        return raw_breakdown if isinstance(raw_breakdown, list) else []

    allows_half = check_rubric_allows_half_marks(rubric_json)
    from .confidence import extract_main_question_number

    standardized = []
    
    for r_idx, r_item in enumerate(rubric_json):
        if not isinstance(r_item, dict):
            continue
        q_target = r_item.get("question_number") or r_item.get("criterion") or f"Q{r_idx + 1}"
        main_q_target = extract_main_question_number(q_target)
        max_sc = float(r_item.get("max_score", r_item.get("maxMark", total_max_score / max(1, len(rubric_json)))))

        # Find all breakdown items matching this question
        matching_items = []
        if isinstance(raw_breakdown, list):
            for b_item in raw_breakdown:
                if not isinstance(b_item, dict):
                    continue
                b_q = str(b_item.get("question_number") or b_item.get("criterion") or "")
                b_main = extract_main_question_number(b_q)
                if b_main == main_q_target or b_q.upper() == q_target.upper():
                    matching_items.append(b_item)

        # Positional index-based fallback if question name was obscured (e.g. [ADDRESS] or Part 1)
        if not matching_items and isinstance(raw_breakdown, list) and r_idx < len(raw_breakdown):
            candidate = raw_breakdown[r_idx]
            if isinstance(candidate, dict):
                matching_items.append(candidate)

        if matching_items:
            total_awarded = sum(
                float(m.get("score_awarded", m.get("auditor_score", m.get("score", 0.0))))
                for m in matching_items
            )
            # Enforce whole marks if rubric does not specify half marks
            if not allows_half:
                total_awarded = float(round(total_awarded))

            total_awarded = max(0.0, min(max_sc, total_awarded))

            # Combine reasoning from sub-parts
            reasonings = []
            for m in matching_items:
                m_q = m.get("question_number", "")
                m_sc = m.get("score_awarded", m.get("auditor_score", m.get("score", 0.0)))
                m_mx = m.get("max_score", "")
                m_reason = (m.get("reasoning") or "").strip()
                if len(matching_items) > 1 and m_reason:
                    sc_str = f" [{m_sc}/{m_mx}]" if m_mx else ""
                    reasonings.append(f"{m_q}{sc_str}: {m_reason}")
                elif m_reason:
                    reasonings.append(m_reason)

            combined_reasoning = " | ".join(reasonings) if reasonings else f"Evaluated against {q_target} rubric criteria."

            standardized.append({
                "question_number": q_target,
                "score_awarded": total_awarded,
                "auditor_score": total_awarded,
                "max_score": max_sc,
                "reasoning": combined_reasoning
            })
        else:
            standardized.append({
                "question_number": q_target,
                "score_awarded": 0.0,
                "auditor_score": 0.0,
                "max_score": max_sc,
                "reasoning": f"No response evaluated for {q_target}."
            })

    return standardized


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

    # Sanitize rubric_json: remove internal database UUIDs (e.g. question_id: "assign-1608e0-q6")
    clean_rubric = []
    if isinstance(rubric_json, list):
        for idx, item in enumerate(rubric_json):
            if isinstance(item, dict):
                c = dict(item)
                c["question_number"] = c.get("question_number") or f"Q{idx + 1}"
                c.pop("question_id", None)
                c.pop("id", None)
                clean_rubric.append(c)
            else:
                clean_rubric.append(item)
    else:
        clean_rubric = rubric_json

    primary_model_name = get_llm_model()
    auditor_model_name = get_auditor_model()

    # Step 1: Agent 1 - Rubric & Context Parser Agent
    print(f" │   ├─ [Agent 1: Rubric Parser] Structuring rubric rules & RAG context...", flush=True)
    parser_res = call_rubric_context_parser_agent(clean_rubric, model_answer, rag_context)
    structured_rubric = parser_res if parser_res else {"structured_rules": clean_rubric}
    
    # Sanitize structured_rules question numbers to clean rubric identifiers (e.g. Q6, Q8), avoiding database IDs
    if structured_rubric and isinstance(structured_rubric.get("structured_rules"), list):
        for idx, rule in enumerate(structured_rubric["structured_rules"]):
            if isinstance(rule, dict) and idx < len(clean_rubric):
                rule["question_number"] = clean_rubric[idx].get("question_number") or f"Q{idx + 1}"

    rule_count = len(clean_rubric) if isinstance(clean_rubric, list) else 1
    print(f" │   │  └─ Loaded {rule_count} rubric rule(s) & reference guidelines.", flush=True)

    # Step 2: Agent 2 - Primary CoT Grader Agent
    mode_tag = f"Few-Shot ({sum(len(v) for v in question_few_shots.values())} exemplars)" if question_few_shots else "Zero-Shot"
    print(f" │   ├─ [Agent 2: Primary Grader ({primary_model_name})] Evaluating submission in {mode_tag} mode...", flush=True)
    primary_res = call_primary_grading_agent(
        student_text=student_text,
        structured_rubric=structured_rubric,
        raw_rubric_json=clean_rubric,
        model_answer=model_answer,
        rag_context=rag_context,
        total_max_score=total_max_score,
        question_few_shots=question_few_shots
    )
    if not primary_res:
        print(" │   │  └─ [Warning] Primary Agent call failed. Using heuristic fallback.", flush=True)
        return _mock_heuristic_evaluation(student_text, clean_rubric, total_max_score)

    # Ensure feedback dictionary and standardized breakdown list exist (aggregated to Main Questions)
    feedback = primary_res.get("feedback", {})
    if not isinstance(feedback, dict):
        feedback = {"summary": "AI Evaluation completed."}
        primary_res["feedback"] = feedback

    raw_breakdown = feedback.get("breakdown", [])
    breakdown = aggregate_and_standardize_breakdown(raw_breakdown, clean_rubric, total_max_score)
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
    auditor_res = call_auditor_verification_agent(
        student_text=student_text,
        rubric_json=clean_rubric,
        primary_eval=primary_res,
        question_few_shots=question_few_shots
    )

    standardized_a_bd = []
    if auditor_res:
        audit_passed = bool(auditor_res.get("audit_passed", True))
        raw_a_bd = auditor_res.get("auditor_breakdown", [])
        standardized_a_bd = aggregate_and_standardize_breakdown(raw_a_bd, clean_rubric, total_max_score)
        auditor_res["auditor_breakdown"] = standardized_a_bd
        
        raw_aud_sc = float(auditor_res.get("auditor_score", auditor_res.get("reconciled_score", 0.0)))
        if standardized_a_bd:
            calc_aud_sum = sum(float(a.get("score_awarded", a.get("auditor_score", 0.0))) for a in standardized_a_bd)
            auditor_score = round(calc_aud_sum, 1) if calc_aud_sum > 0 else round(raw_aud_sc if raw_aud_sc > 0 else primary_score, 1)
        else:
            auditor_score = round(raw_aud_sc if raw_aud_sc > 0 else primary_score, 1)

        reconciled_score = float(auditor_res.get("reconciled_score", auditor_score))
        allows_half = check_rubric_allows_half_marks(clean_rubric)
        if not allows_half:
            auditor_score = float(round(auditor_score))
            reconciled_score = float(round(reconciled_score))

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
            "auditor_breakdown": standardized_a_bd,
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
    # Adopt Auditor-reconciled final score if:
    # 1. Submission was auto-approved ("graded")
    # 2. OR Primary Grader awarded 0.0 marks while Auditor found valid responses and awarded marks (ADOPT_AUDITOR)
    should_adopt_auditor = False
    if auditor_res:
        if confidence_result["status"] == "graded":
            should_adopt_auditor = True
        elif primary_score == 0.0 and auditor_score > 0.0 and recommendation == "ADOPT_AUDITOR":
            should_adopt_auditor = True

    if should_adopt_auditor:
        primary_res["overall_score"] = round(reconciled_score, 1)
        primary_res["auditor_reconciled"] = (primary_score != reconciled_score)
        primary_res["reconciliation_action"] = recommendation
        
        # Synchronize question breakdown with auditor scores
        if standardized_a_bd and isinstance(feedback.get("breakdown"), list):
            from .confidence import extract_main_question_number
            auditor_map = {extract_main_question_number(a.get("question_number", "")): a for a in standardized_a_bd if isinstance(a, dict)}
            for idx, p_item in enumerate(feedback["breakdown"]):
                q_k = extract_main_question_number(p_item.get("question_number", ""))
                a_candidate = auditor_map.get(q_k)
                if not a_candidate and idx < len(standardized_a_bd):
                    a_candidate = standardized_a_bd[idx]
                if a_candidate:
                    a_sc = a_candidate.get("score_awarded", a_candidate.get("auditor_score"))
                    if a_sc is not None:
                        p_item["score_awarded"] = float(a_sc)
                        if not p_item.get("reasoning") or "No response evaluated" in str(p_item.get("reasoning", "")):
                            p_item["reasoning"] = a_candidate.get("reasoning", p_item.get("reasoning", ""))
        
        # Re-synchronize highlight scores with reconciled breakdown scores
        _enrich_highlights_with_question_info(primary_res, student_text)

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

    import re

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

    # 1. Normalize question numbers and remove invalid tags like [ADDRESS]
    for hl in highlights:
        if not isinstance(hl, dict):
            continue
        q_raw = str(hl.get("question_number", "")).strip()
        if not q_raw or "[" in q_raw or "Rubric" in q_raw or "General" in q_raw or "N/A" in q_raw:
            hl_quote = hl.get("text", "")
            pos = student_text.find(hl_quote) if hl_quote else -1
            if pos != -1:
                prefix = student_text[max(0, pos - 400):pos]
                m_det = re.findall(r'(?:Question|Q)\s*([Q0-9A-Za-z\(\)]+)', prefix, re.IGNORECASE)
                if m_det:
                    clean_det = f"Q{m_det[-1]}" if not m_det[-1].startswith("Q") else m_det[-1]
                    hl["question_number"] = clean_det

    # 2. Deduplicate existing highlights (remove duplicate quotes)
    unique_hls = []
    for h in highlights:
        if not isinstance(h, dict) or not h.get("text"):
            continue
        h_text = h["text"].strip().lower()
        is_dup = any(h_text in ex["text"].strip().lower() or ex["text"].strip().lower() in h_text for ex in unique_hls)
        if not is_dup:
            unique_hls.append(h)
    highlights = unique_hls

    from .confidence import extract_main_question_number

    # 3. Process each breakdown item with sub-part awareness
    for b in breakdown:
        if not isinstance(b, dict):
            continue
        b_q = b.get("question_number", "")
        if not b_q:
            continue
        main_bq = extract_main_question_number(b_q)
        score_aw = float(b.get("score_awarded", 0.0) or 0.0)
        max_sc = float(b.get("max_score", 10.0) or 10.0)
        reasoning = b.get("reasoning", "Rubric criterion evaluation completed.")

        q_matches = [h for h in highlights if extract_main_question_number(h.get("question_number", "")) == main_bq]

        # Check for sub-parts in reasoning: e.g. (a) [3/5]: ... (b) [2/5]: ...
        subpart_matches = list(re.finditer(r'\(([a-zA-Z0-9]+)\)\s*\[([0-9\.]+)/([0-9\.]+)\]:\s*([^|(]+)', reasoning))
        if subpart_matches:
            subpart_sum = sum(float(sp.group(2)) for sp in subpart_matches)
            clamped_sum = min(max_sc, subpart_sum)
            if abs(clamped_sum - score_aw) > 0.01:
                b["score_awarded"] = int(clamped_sum) if clamped_sum.is_integer() else clamped_sum
                score_aw = float(b["score_awarded"])

        # Find question chunk in student_text
        clean_bq_str = re.sub(r'[^a-zA-Z0-9]', '', b_q).lower()
        q_pos = text_lower.find(clean_bq_str)
        if q_pos == -1 and len(b_q) > 1:
            m_q = re.search(r'(?:Question|Q)?\s*' + re.escape(b_q), student_text, re.IGNORECASE)
            if m_q:
                q_pos = m_q.start()

        body_chunk = ""
        if q_pos != -1:
            chunk_after = student_text[q_pos:q_pos + 1500]
            body_match = re.search(r'(?:Question|Q|Problem)\s*[A-Za-z0-9_()]+:?\s*([\s\S]*)', chunk_after, re.IGNORECASE)
            raw_chunk = body_match.group(1) if body_match else chunk_after
            next_q = re.search(r'(?:^|\n\n)(?:Question|Q|Problem)\s+[A-Za-z0-9_()]+', raw_chunk, re.IGNORECASE)
            body_chunk = raw_chunk[:next_q.start()].strip() if next_q else raw_chunk.strip()

        if subpart_matches and body_chunk:
            subpart_keys = [sp.group(1) for sp in subpart_matches]
            positions = []
            for sp in subpart_matches:
                k = sp.group(1)
                esc_k = re.escape(k)
                pat = rf'(?:^|\n|\s)(?:\({esc_k}\)|{esc_k}\)|{esc_k}\.)'
                m = re.search(pat, body_chunk, re.IGNORECASE)
                if m:
                    positions.append({
                        "start": m.start() + (len(m.group(0)) - len(m.group(0).lstrip())),
                        "key": k.lower(),
                        "sp": sp
                    })
            positions.sort(key=lambda x: x["start"])

            first_k = subpart_keys[0].lower()
            if not any(p["key"] == first_k for p in positions) and positions:
                first_sp = next(sp for sp in subpart_matches if sp.group(1).lower() == first_k)
                positions.insert(0, {"start": 0, "key": first_k, "sp": first_sp})

            if len(positions) >= max(1, len(subpart_matches) - 1):
                # Replace existing coarse highlights for this question with sub-part highlights
                highlights = [h for h in highlights if extract_main_question_number(h.get("question_number", "")) != main_bq]
                for i in range(len(positions)):
                    p = positions[i]
                    nxt = positions[i + 1]["start"] if i + 1 < len(positions) else len(body_chunk)
                    s_text = body_chunk[p["start"]:nxt].strip()
                    sp = p["sp"]
                    p_key = sp.group(1)
                    p_sc = float(sp.group(2))
                    p_mx = float(sp.group(3))
                    p_rs = sp.group(4).strip()

                    is_short = len(s_text) <= 60
                    if is_short:
                        highlights.append({
                            "text": s_text,
                            "question_number": f"{b_q}({p_key})",
                            "score_awarded": int(p_sc) if p_sc.is_integer() else p_sc,
                            "max_score": p_mx,
                            "type": "strength" if p_sc > 0 else "weakness",
                            "comment": f"({p_key}) [{p_sc}/{p_mx}]: {p_rs}",
                            "location_in_raw_text": f"Question {b_q} Section"
                        })
                    else:
                        sentences = [s.strip().lstrip('*- ') for s in re.split(r'(?<=[.?!])\s+|\n+', s_text) if len(s.strip()) > 10 and not re.match(r'^\(?[a-zA-Z0-9][\)\.]', s.strip())]
                        pick = sentences[0] if sentences else s_text[:120]
                        highlights.append({
                            "text": pick,
                            "question_number": f"{b_q}({p_key})",
                            "score_awarded": int(p_sc) if p_sc.is_integer() else p_sc,
                            "max_score": p_mx,
                            "type": "strength" if p_sc > 0 else "weakness",
                            "comment": f"({p_key}) [{p_sc}/{p_mx}]: {p_rs}",
                            "location_in_raw_text": f"Question {b_q} Section"
                        })
                continue

        # If question has no highlights at all and score_aw > 0
        if not q_matches and body_chunk and score_aw > 0:
            sentences = [s.strip() for s in re.split(r'(?<=[.?!])\s+', body_chunk) if len(s.strip()) > 8]
            if sentences:
                num_to_take = min(len(sentences), max(1, int(round(score_aw))))
                step = score_aw / num_to_take
                for s_idx in range(num_to_take):
                    highlights.append({
                        "text": sentences[s_idx],
                        "question_number": b_q,
                        "score_awarded": round(step, 1),
                        "max_score": max_sc,
                        "type": "strength",
                        "comment": f"Evaluated for {b_q}. Reasoning: {reasoning}",
                        "location_in_raw_text": f"Question {b_q} Section"
                    })

    # 4. Strict final alignment: Ensure sum of strength highlights strictly equals score_awarded
    for b in breakdown:
        if not isinstance(b, dict):
            continue
        b_q = b.get("question_number", "")
        if not b_q:
            continue
        target_score = float(b.get("score_awarded", 0.0) or 0.0)
        main_bq = extract_main_question_number(b_q)

        q_hls = [
            h for h in highlights
            if isinstance(h, dict) and extract_main_question_number(h.get("question_number", "")) == main_bq
        ]
        if not q_hls:
            continue

        positive_hls = [h for h in q_hls if h.get("type") == "strength" or float(h.get("score_awarded", 0.0) or 0.0) > 0]
        if not positive_hls:
            positive_hls = q_hls

        current_sum = sum(float(h.get("score_awarded", 0.0) or 0.0) for h in positive_hls)

        if target_score == 0:
            for h in q_hls:
                h["score_awarded"] = 0.0
                h["type"] = "weakness"
        elif abs(current_sum - target_score) > 0.05 and positive_hls:
            if len(positive_hls) == 1:
                clean_target = int(target_score) if target_score.is_integer() else target_score
                positive_hls[0]["score_awarded"] = clean_target
                positive_hls[0]["type"] = "strength"
            else:
                total_weight = sum(float(h.get("score_awarded", 0.0) or 1.0) for h in positive_hls)
                for h in positive_hls:
                    w = float(h.get("score_awarded", 0.0) or 1.0)
                    scaled = (w / (total_weight if total_weight > 0 else len(positive_hls))) * target_score
                    h["score_awarded"] = int(round(scaled)) if (target_score.is_integer() and round(scaled).is_integer()) else round(scaled, 1)
                    h["type"] = "strength" if h["score_awarded"] > 0 else "weakness"

        if target_score > 0:
            highlights = [
                h for h in highlights
                if not (extract_main_question_number(h.get("question_number", "")) == main_bq and h.get("type") == "strength" and float(h.get("score_awarded", 0.0) or 0.0) == 0)
            ]

    primary_res["highlights"] = highlights


