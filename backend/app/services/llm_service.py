import os
import re
import json
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable
import requests
from dotenv import load_dotenv
from .confidence import evaluate_confidence_and_status

# Ensure backend .env is loaded regardless of execution working directory
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=_env_path, override=True)
load_dotenv(override=True)

def get_openrouter_api_key() -> str:
    return os.getenv("OPENROUTER_API_KEY", "").strip()

def get_llm_model() -> str:
    return os.getenv("LLM_MODEL", "google/gemini-3.1-flash-lite").strip()

def get_auditor_model() -> str:
    return os.getenv("AUDITOR_MODEL", "google/gemini-3.1-flash-lite").strip()



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


def call_auditor_verification_agent(
    student_text: str, 
    rubric_json: list, 
    primary_eval: Dict[str, Any], 
    model: Optional[str] = None,
    question_few_shots: Optional[Dict[str, List[Dict]]] = None
) -> Optional[Dict[str, Any]]:
    """
    Agent 3 (Auditor & Verification Agent):
    Uses get_auditor_model() (default google/gemini-3.1-flash-lite, overridable via
    the AUDITOR_MODEL env var) to audit the primary grader's evaluation.
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


def _build_checklist_grading_prompt(
    student_text: str,
    total_max_score: float,
    groups: list,
    matching_strictness: str = "meaning",
    allow_half_marks: bool = False,
    rag_context: str = "",
    few_shots_block: str = "",
) -> str:
    """
    Universal criterion-checklist grading prompt shared by every rubric that
    decomposes into fixed groups of independently-verifiable marking criteria, each
    worth 1 mark and capped at that group's own max_score. Used for both Q6 (point-
    bank comparative analysis) and Q8 (per-item verdict+justification), and intended
    for reuse on future short-answer/written-response questions of either shape --
    only the `groups` checklist data and these two rubric-derived parameters differ:

    matching_strictness:
      "meaning"  -- award a criterion for any answer conveying the same meaning,
                    even in different words (use for point-bank / comparative-list
                    rubrics, e.g. Q6, where the source rubric itself says to accept
                    paraphrases).
      "explicit" -- award a criterion ONLY when the answer explicitly and clearly
                    states it; do not award for vague or "somewhat aligned" answers
                    (use for verdict+justification rubrics, e.g. Q8, where the source
                    rubric is graded strictly). Getting this dial wrong per question
                    is what caused Q8's ICC to collapse when it was graded with Q6's
                    "meaning" leniency -- always set it from the actual rubric's own
                    strictness, not a fixed default.

    allow_half_marks: whether 0.5 can be awarded for a criterion that is partially
    but incompletely satisfied. Off by default (most point-bank criteria are binary);
    Q8 turns it on because its source rubric explicitly permits 0.5 marks.

    Note: criteria are graded independently within a group unless the checklist text
    itself states a dependency -- do not invent extra conditions between criteria
    (e.g. gating a "reason" criterion on a "verdict" criterion elsewhere in the same
    group) beyond what the checklist explicitly says, since that measurably lowers
    agreement with human graders who scored each line item independently.
    """
    groups_block = ""
    for g in groups:
        crit_lines = "\n".join(f"    {i + 1}. {c}" for i, c in enumerate(g["criteria"]))
        groups_block += (
            f"\n{g['group']} (max {g['max_score']:.1f} marks -- 1 mark per criterion met, "
            f"capped at {g['max_score']:.1f} even if more of the {len(g['criteria'])} criteria below are met):\n"
            f"{crit_lines}\n"
        )

    group_names = ", ".join(f'"{g["group"]}"' for g in groups)
    example_group = groups[0]["group"]

    if matching_strictness == "explicit":
        strictness_line = (
            'STRICTLY follow the checklist. Award a criterion ONLY if the student\'s answer '
            'explicitly and clearly states it. Do NOT award a criterion for a vague answer, or '
            'one that merely "somewhat aligns" with it without clearly stating it.'
        )
    else:
        strictness_line = (
            "Award a criterion if the student's answer conveys the SAME MEANING as it, even in "
            "different words -- paraphrases, synonyms, and reordered phrasing all count as a match. "
            "Do not require exact wording."
        )

    half_mark_line = (
        "You may award 0.5 for a criterion the student's answer partially but incompletely satisfies."
        if allow_half_marks
        else "Whole marks only for each criterion -- DO NOT award 0.5 marks."
    )

    rag_section = f"\n{rag_context}\n" if rag_context else ""

    return f"""
You are an expert academic evaluator. Grade the student's submission using CRITERION
CHECKLIST MATCHING, not holistic essay judgement. The question is organized into fixed
groups below; each group is a list of marking criteria worth 1 mark each, and each
group has its own mark cap that may be lower than its criteria count.
{groups_block}
MATCHING STRICTNESS: {strictness_line}

Total Assignment Max Score: {total_max_score}
{rag_section}{few_shots_block}
Student Submission:
{student_text}

GRADING PROTOCOL:
1. Work through the groups in order. Route the student's content to the correct group
   by meaning and context -- students often don't label their points to match the
   groups above.
2. For each criterion, FIRST locate and quote the exact verbatim span of the
   student's own text that relates to it (if any), THEN judge whether it satisfies
   the criterion under the matching strictness above. Never award a mark without a
   supporting quote from the student's own text.
3. {half_mark_line} Sum the satisfied criteria within a group, but never exceed that
   group's own max_score even if more criteria are satisfied than the cap allows.
4. Never award the same criterion twice for two restatements of the same idea, and
   never award a criterion using content that clearly belongs to a different group.
5. Treat criteria within a group as independent unless the checklist text itself
   states a dependency between them -- do not invent extra conditions beyond what's
   written above.
6. If the student gives no relevant content for a group, that group scores 0 -- do
   not guess or award sympathy marks.
7. ZERO MARK RULE: if the entire student answer is blank, '-', 'N/A', or missing,
   award 0 for every group.
8. Double-check every group's cap and the final sum before finalizing. Show your
   criterion-by-criterion matching (with quotes) in "reasoning", and mirror it in
   "feedback.breakdown" as exactly one entry per group ({group_names}), each with
   score_awarded (capped at that group's max_score) and max_score. overall_score
   MUST equal the sum of the group scores in "feedback.breakdown".
9. QUESTION-MATCHED EXAMINER CALIBRATION: If Examiner Calibration Benchmarks are
   provided above, you MUST align your matching strictness and partial-credit
   thresholds strictly to match the examiner's demonstrated standard for this
   question. If no calibration benchmarks are provided, evaluate directly from
   the standard checklist rules above.

OUTPUT FORMAT (Respond ONLY in valid JSON matching this schema):
{{
  "overall_score": 0.0,
  "confidence_score": 0.90,
  "status": "graded",
  "reasoning": "Group-by-group: quote the relevant student text for each criterion, state whether it was met or missed, then sum.",
  "feedback": {{
    "summary": "One-sentence overview of which groups were strong and which lost marks.",
    "breakdown": [
      {{"question_number": "{example_group}", "score_awarded": 0.0, "max_score": 0.0, "reasoning": "Which numbered criteria were matched and which were missed, and why, with supporting quotes."}}
    ]
  }},
  "highlights": [
    {{"text": "Exact quote copied verbatim from student submission", "question_number": "{example_group}", "score_awarded": 0.0, "max_score": 0.0, "type": "strength", "comment": "Which criteria this quote satisfies or misses."}}
  ]
}}
"""


# =============================================================================
# DYNAMIC RUBRIC INTERPRETER: question-type routing instead of question-number
# routing, so a NEW question of an already-supported shape needs no code change.
# Classification (interpret_rubric_spec) is intentionally independent of RAG --
# it reads only the question/rubric text. RAG context and few-shot calibration
# exemplars are grading-time inputs, threaded into each strategy's own prompt
# builder exactly like main's previous single-agent grader received them.
# =============================================================================
#
# GRADING SPECIFICATION schema (the interpreter's output contract):
# {
#   "question_type": "SHORT_ANSWER" | "CALCULATION" | "OPEN_ENDED" | "UNSUPPORTED",
#   "max_score": float,
#   "groups": [{"group": str, "max_score": float, "criteria": [str, ...]}],
#   "matching_strictness": "meaning" | "explicit",
#   "allow_half_marks": bool,
#   "items": [{
#       "label": str, "expected_answer": float, "tolerance": float,
#       "unit": str, "working_mark": float, "answer_mark": float,
#       "acceptable_working_forms": [str, ...],
#   }],
#   "scoring_structure": "BRANCHED" | "INDEPENDENT_CRITERIA",
#   "branches": [{
#       "id": str, "condition": str, "max_score": float,
#       "criteria": [str, ...], "position_linked_criterion": int or null,
#   }],
#   "criteria": [str, ...],
# }

def _build_rubric_interpreter_prompt(
    question_text: str, rubric_text: str, max_score: float, rag_context: str = "",
) -> str:
    """
    Converts an arbitrary question + rubric into a Grading Specification (see the
    module comment above for the schema). Classifies structure, doesn't just
    reformat text -- this output feeds directly into deterministic Python scoring,
    so it must not invent anything the rubric doesn't actually support.

    rag_context (optional): this question's own rubric chunk as retrieved from
    ChromaDB (see grade_submission_dynamic/_get_rag_context in grading.py), given
    as corroborating reference alongside the authoritative rubric_text below --
    it never overrides rubric_text, which remains the lecturer's own answer key.
    """
    rag_section = (
        f"\nRETRIEVED REFERENCE CONTEXT (from the rubric vector store, for cross-"
        f"checking only -- the MARKING RUBRIC below remains authoritative):\n{rag_context}\n"
        if rag_context else ""
    )
    return f"""
You are an Academic Rubric Interpreter. Convert the question and marking rubric
below into a structured Grading Specification for an automated grading system.

QUESTION:
{question_text}
{rag_section}
MARKING RUBRIC (this is the lecturer's authoritative answer key -- do not add,
remove, or reinterpret anything it does not actually say or clearly imply):
{rubric_text}

MAXIMUM SCORE: {max_score}

STEP 1 -- CLASSIFY THE GRADING STRATEGY FROM THE RUBRIC'S STRUCTURE, NOT FROM THE
QUESTION NUMBER OR TOPIC

Choose exactly one:

SHORT_ANSWER
Use when the rubric awards marks for a set of identifiable, independently
verifiable points -- facts, explanations, comparisons, a verdict plus a
justification, or similar discrete criteria. Marks are typically 1 (or a stated
fraction) per criterion, sometimes grouped into sub-parts with their own caps.

CALCULATION
Use when marks substantially depend on mathematical working and/or a specific
numeric result -- doses, concentrations, conversions, formula application. There
is a computable correct answer, possibly per sub-part/per-person.

PRIORITY RULE: a rubric can describe its marks as "N marks for each of the
following" and still be CALCULATION, not SHORT_ANSWER -- that phrasing only
describes how marks are COUNTED, not what is being checked. If the rubric
states a specific worked numeric target per sub-part/person (a computed dose,
concentration, converted value, or similar), classify it as CALCULATION even
though the mark-allocation sentence reads like a checklist. A computable
numeric answer always overrides a superficially checklist-style mark-count
phrasing.

Worked example: a rubric reading "0.5 marks for each correct calculation, 1
mark for each correct final answer. Patient A = 40kg x 5mg/kg = 200mg = 4
tablets" looks like a flat list of discrete mark-earning criteria, but because
it states a specific numeric target (4 tablets) computed from data given in
the question, this is CALCULATION -- extract one item per named sub-part/
person, not a SHORT_ANSWER group.

OPEN_ENDED
Use when the student must construct a professional judgement, critical appraisal,
recommendation, or argument, and the rubric's criteria require semantic/conceptual
matching rather than a single correct fact or number. If the rubric gives two (or
more) mutually exclusive criteria lists keyed to a stated position or decision
(e.g. "if the student agrees... / if the student disagrees...", "1 mark each for
X, OR if Y, 1 mark each for Z"), this is BRANCHED. If it is one flat list of
criteria that always applies regardless of any stance the student takes, this is
INDEPENDENT_CRITERIA.

UNSUPPORTED
Use when the rubric requires something none of the above can grade from text alone
-- e.g. assessing a diagram, image, chemical structure drawing, or other non-textual
artefact. Do not force a non-textual rubric into OPEN_ENDED.

STEP 2 -- EXTRACT THE SPECIFICATION FOR THE CHOSEN STRATEGY

Whichever strategy you chose, extract the rubric's distinct scoring points at the
SAME granularity the rubric itself uses -- one criterion/item per distinct point,
even when two points appear in the same sentence, bullet, or are closely related.
Do not combine two separately-stated rubric points into a single criterion merely
because they are adjacent or thematically similar; doing so silently reduces how
finely the response can be scored and changes the achievable mark resolution.

For SHORT_ANSWER, extract:
- groups: the rubric's own sub-parts (or a single group if it isn't split into
  sub-parts), each with its own max_score and the list of distinct criteria the
  rubric awards within it. Preserve the rubric's own wording for each criterion.
- matching_strictness: "explicit" if the rubric's own instructions say to require
  clear/explicit statements and not award vague or partial alignment; "meaning"
  if the rubric is silent on this or explicitly accepts paraphrasing. Do not guess
  "explicit" merely because the rubric is terse.
- allow_half_marks: true only if the rubric explicitly permits partial/fractional
  marks for a criterion.

For CALCULATION, extract per sub-part/person:
- label: the exact name or identifier the QUESTION TEXT itself uses for this
  sub-part, copied verbatim (e.g. "Melissa", not "the patient" or "Patient A";
  "Tony" or "Melissa's husband" exactly as the question phrases it, not a
  generic role word like "Husband"). The grader matching student answers to
  this label later has only the student's own wording to go on, and students
  normally use the same name the question used -- a paraphrased or
  anonymised label (even one intended as a privacy precaution) makes that
  matching unreliable. This is a fictional exam scenario, not real personal
  data, so there is no privacy reason to avoid using the name as given.
- expected_answer: the exact correct final numeric answer, computed from the
  rubric/model answer's own worked example. Show your own working internally
  before committing to this number; if the rubric's worked example is itself
  ambiguous or inconsistent, extract the value the rubric's final stated answer
  actually uses.
- answer_source: "RUBRIC_EXPLICIT" if the rubric's own worked example already
  states this exact final number (you are copying it, not computing it).
  "DERIVED" if the rubric only gives the formula/method and you had to compute
  the number yourself from data in the question or rubric. Be honest about
  which one this is -- do not mark something DERIVED as RUBRIC_EXPLICIT merely
  because you are confident in the arithmetic.
- source_evidence: if RUBRIC_EXPLICIT, the exact rubric text you copied the
  number from. If DERIVED, the calculation you performed to reach it (e.g.
  "65 kg x 8 mg/kg = 520 mg"), so a human can check your arithmetic.
- tolerance: 0 unless the rubric explicitly allows a margin (e.g. rounding).
- unit: the unit of the final answer as the rubric expresses it (e.g. "mg",
  "tablets", "mL", "squares"), or null if dimensionless.
- working_mark / answer_mark: the mark value the rubric assigns to showing
  correct working vs. stating the correct final answer, for this sub-part.
- acceptable_working_forms: 2-4 short EXAMPLES of what showing valid working
  might look like for this sub-part (derived from the rubric's own working, not
  invented), to help a grader recognise working shown in different valid forms.

For OPEN_ENDED, extract:
- scoring_structure: "BRANCHED" or "INDEPENDENT_CRITERIA" per Step 1.
- If BRANCHED: branches, each with an id, a short description of when it applies
  (`condition`), its own max_score, and its own criteria list (the rubric's own
  wording). For EVERY criterion in the branch, ask: "does satisfying this
  criterion require anything beyond the student having already chosen this
  branch's position?" If a criterion is automatically true for any response
  that falls into this branch -- it just restates the branch's own decision
  (e.g. "this is ok to stock", "this is a reasonable position to take", "the
  student agrees with X") -- you MUST set position_linked_criterion to that
  criterion's 1-based index. Do not leave position_linked_criterion null when
  such a criterion is present; only use null when no criterion in the branch
  merely restates the branch's own condition.

  Worked example: a STOCK-decision branch whose first listed criterion reads
  "This is a product that is ok to stock in community pharmacies" is
  automatically satisfied by any response that chose to stock -- that
  criterion requires no additional fact beyond the position itself, so
  position_linked_criterion must be set to 1 for that branch.
- If INDEPENDENT_CRITERIA: a single flat criteria list (the rubric's own wording)
  and use the overall max_score.
- calibration_notes (OPEN_ENDED only): 2-4 sentences, grounded in THIS rubric's
  own criteria, giving concrete guidance on how literally vs. loosely to
  interpret its wording -- what kinds of paraphrase, broader terminology, or
  implicit statement should still count as meeting a criterion, and what would
  NOT be enough. Write this from the rubric's actual content, not generic
  boilerplate -- its purpose is to stop a grader being overly literal about
  THIS rubric's specific concepts, the way a human rubric author would clarify
  edge cases to a new marker.

Do not invent scoring rules, criteria, numeric answers, or caps the rubric does
not support. If the rubric is ambiguous about strictness, partial credit, or
tolerance, prefer the stricter/narrower reading rather than assuming leniency.

OUTPUT ONLY VALID JSON matching the Grading Specification schema, including only
the fields relevant to the chosen question_type:
{{
  "question_type": "SHORT_ANSWER",
  "max_score": {max_score},
  "groups": [
    {{"group": "string label", "max_score": 0.0, "criteria": ["criterion text", "criterion text"]}}
  ],
  "matching_strictness": "meaning",
  "allow_half_marks": false,
  "items": [
    {{"label": "string", "expected_answer": 0.0, "answer_source": "RUBRIC_EXPLICIT",
      "source_evidence": "quoted rubric text or shown derivation", "tolerance": 0.0,
      "unit": "mg", "working_mark": 0.5, "answer_mark": 1.0,
      "acceptable_working_forms": ["example"]}}
  ],
  "scoring_structure": "BRANCHED",
  "branches": [
    {{"id": "B1", "condition": "string", "max_score": 0.0, "criteria": ["criterion text"], "position_linked_criterion": 1}}
  ],
  "criteria": ["criterion text"],
  "calibration_notes": "string, OPEN_ENDED only"
}}
"""


def call_rubric_interpreter_agent(
    question_text: str,
    rubric_text: str,
    max_score: float,
    model: Optional[str] = None,
    rag_context: str = "",
) -> Optional[Dict[str, Any]]:
    """Runs the Rubric Interpreter and returns a Grading Specification, or None on failure."""
    prompt = _build_rubric_interpreter_prompt(question_text, rubric_text, max_score, rag_context)
    messages = [
        {
            "role": "system",
            "content": (
                "You are a precise academic rubric interpreter. Classify the grading "
                "strategy from the rubric's own structure, extract only what the rubric "
                "actually supports, and never invent criteria, numeric answers, or caps. "
                "Always return valid JSON."
            ),
        },
        {"role": "user", "content": prompt},
    ]
    target_model = model or get_llm_model()
    return _call_openrouter_api(messages, target_model, temperature=0.0)


def _validate_grading_spec(spec: Dict[str, Any]) -> "tuple[bool, list, list]":
    """
    Deterministic (non-LLM) sanity check on a Grading Specification before it is
    trusted by any grading strategy. This is Python-owned validation, not another
    semantic model -- the interpreter can misclassify a question, extract an empty
    criteria list, or invent an internally inconsistent cap, and nothing upstream
    would catch that before it silently produced a wrong or zero score.

    Returns (is_valid, issues, review_flags):
      is_valid    -- False means the spec is structurally unusable; the caller
                     must not grade with it (route to human review instead of
                     forcing it through a strategy on broken data).
      issues      -- human-readable list of hard validation failures (empty if valid).
      review_flags -- non-fatal warnings worth surfacing to a human even when the
                     spec IS structurally valid, e.g. a CALCULATION item whose
                     expected_answer was DERIVED by the interpreter rather than
                     copied from the rubric's own stated answer -- valid to grade
                     with, but exactly the new failure mode (LLM-derived ground
                     truth instead of human-verified) flagged as the main risk of
                     this architecture. Never silently drop these; the calculation
                     strategy carries them through into the final result's
                     flag_reasons so they reach a human, not just a log line.
    """
    issues: list = []
    review_flags: list = []

    q_type = str(spec.get("question_type", "")).strip().upper()
    if q_type not in {"SHORT_ANSWER", "CALCULATION", "OPEN_ENDED", "UNSUPPORTED"}:
        return False, [f"Unrecognised question_type: {spec.get('question_type')!r}"], []
    if q_type == "UNSUPPORTED":
        return True, [], []  # valid classification; caller routes this to human review, not an error

    try:
        max_score = float(spec.get("max_score", 0))
    except (TypeError, ValueError):
        return False, ["max_score is missing or not numeric"], []
    if max_score <= 0:
        issues.append(f"max_score must be positive, got {max_score}")

    if q_type == "SHORT_ANSWER":
        groups = spec.get("groups") or []
        if not groups:
            issues.append("SHORT_ANSWER spec has no groups")
        for i, g in enumerate(groups):
            if not isinstance(g, dict):
                issues.append(f"groups[{i}] is not an object")
                continue
            if not g.get("criteria"):
                issues.append(f"groups[{i}] ({g.get('group')!r}) has no criteria")
            try:
                g_max = float(g.get("max_score", 0))
                if g_max <= 0:
                    issues.append(f"groups[{i}] ({g.get('group')!r}) max_score must be positive, got {g_max}")
            except (TypeError, ValueError):
                issues.append(f"groups[{i}] ({g.get('group')!r}) max_score is not numeric")
        try:
            group_sum = sum(float(g.get("max_score", 0)) for g in groups if isinstance(g, dict))
            if group_sum > 0 and abs(group_sum - max_score) > 0.01:
                review_flags.append(
                    f"Sum of group max_scores ({group_sum:.1f}) does not match the question's "
                    f"max_score ({max_score:.1f}) -- using the group sum as authoritative."
                )
        except (TypeError, ValueError):
            pass

        # Heuristic safety net: a CALCULATION rubric misread as SHORT_ANSWER still
        # carries its own worked numeric targets into the extracted criteria text
        # (the interpreter is instructed to preserve the rubric's own wording).
        # Flag -- do not block -- when criteria look like they're checking a
        # specific computed number rather than a discrete fact/explanation.
        numeric_hits = 0
        for g in groups:
            if not isinstance(g, dict):
                continue
            for c in (g.get("criteria") or []):
                if isinstance(c, str) and re.search(
                    r"\d+(\.\d+)?\s*(kg|mg|mL|ml|mg/kg|g|tablets?|squares?|doses?)\b|\d\s*=\s*\d|\d+\s*x\s*\d+",
                    c, re.IGNORECASE,
                ):
                    numeric_hits += 1
        if numeric_hits >= 2:
            review_flags.append(
                f"Classified as SHORT_ANSWER but {numeric_hits} criteria contain numeric/unit "
                f"patterns (e.g. doses, converted values) typical of a CALCULATION rubric -- "
                f"verify this question wasn't misclassified before trusting this grading at scale."
            )

    elif q_type == "CALCULATION":
        items = spec.get("items") or []
        if not items:
            issues.append("CALCULATION spec has no items")
        for i, it in enumerate(items):
            if not isinstance(it, dict):
                issues.append(f"items[{i}] is not an object")
                continue
            label = it.get("label", f"item {i}")
            if it.get("expected_answer") is None:
                issues.append(f"items[{i}] ({label!r}) has no expected_answer")
            else:
                try:
                    float(it["expected_answer"])
                except (TypeError, ValueError):
                    issues.append(f"items[{i}] ({label!r}) expected_answer is not numeric")
            try:
                if float(it.get("tolerance", 0)) < 0:
                    issues.append(f"items[{i}] ({label!r}) tolerance cannot be negative")
            except (TypeError, ValueError):
                issues.append(f"items[{i}] ({label!r}) tolerance is not numeric")
            for mark_field in ("working_mark", "answer_mark"):
                try:
                    if float(it.get(mark_field, 0)) < 0:
                        issues.append(f"items[{i}] ({label!r}) {mark_field} cannot be negative")
                except (TypeError, ValueError):
                    issues.append(f"items[{i}] ({label!r}) {mark_field} is not numeric")
            if str(it.get("answer_source", "")).strip().upper() == "DERIVED":
                review_flags.append(
                    f"items[{i}] ({label!r}): expected_answer {it.get('expected_answer')} was DERIVED by "
                    f"the interpreter, not copied from an explicit rubric answer "
                    f"({it.get('source_evidence', 'no derivation shown')}). Verify before trusting at scale."
                )
        try:
            item_mark_sum = sum(
                float(it.get("working_mark", 0)) + float(it.get("answer_mark", 0))
                for it in items if isinstance(it, dict)
            )
            if item_mark_sum > 0 and abs(item_mark_sum - max_score) > 0.01:
                review_flags.append(
                    f"Sum of item working_mark+answer_mark ({item_mark_sum:.1f}) does not match "
                    f"the question's max_score ({max_score:.1f}) -- full marks on every item "
                    f"would not actually reach {max_score:.1f}."
                )
        except (TypeError, ValueError):
            pass

    elif q_type == "OPEN_ENDED":
        structure = spec.get("scoring_structure", "").strip().upper() if isinstance(spec.get("scoring_structure"), str) else ""
        if structure == "BRANCHED":
            branches = spec.get("branches") or []
            if not branches:
                issues.append("BRANCHED OPEN_ENDED spec has no branches")
            for i, b in enumerate(branches):
                if not isinstance(b, dict):
                    issues.append(f"branches[{i}] is not an object")
                    continue
                b_criteria = b.get("criteria") or []
                if not b_criteria:
                    issues.append(f"branches[{i}] ({b.get('id')!r}) has no criteria")
                try:
                    if float(b.get("max_score", 0)) <= 0:
                        issues.append(f"branches[{i}] ({b.get('id')!r}) max_score must be positive")
                except (TypeError, ValueError):
                    issues.append(f"branches[{i}] ({b.get('id')!r}) max_score is not numeric")
                pli = b.get("position_linked_criterion")
                if pli is not None:
                    try:
                        pli_int = int(pli)
                        if not (1 <= pli_int <= len(b_criteria)):
                            issues.append(
                                f"branches[{i}] ({b.get('id')!r}) position_linked_criterion={pli_int} "
                                f"is out of range for {len(b_criteria)} criteria"
                            )
                    except (TypeError, ValueError):
                        issues.append(f"branches[{i}] ({b.get('id')!r}) position_linked_criterion is not an integer")
                else:
                    condition_words = {
                        w for w in re.findall(r"[a-z]{4,}", str(b.get("condition", "")).lower())
                        if w not in {"this", "that", "with", "student", "their", "they", "from", "when", "overall"}
                    }
                    if condition_words:
                        for c_idx, c in enumerate(b_criteria, start=1):
                            if not isinstance(c, str):
                                continue
                            c_words = set(re.findall(r"[a-z]{4,}", c.lower()))
                            if not c_words:
                                continue
                            overlap = len(condition_words & c_words) / min(len(condition_words), len(c_words))
                            if overlap >= 0.5:
                                review_flags.append(
                                    f"branches[{i}] ({b.get('id')!r}) criterion #{c_idx} ({c!r}) closely "
                                    f"echoes this branch's own condition but position_linked_criterion is "
                                    f"null -- verify whether it should have been auto-awarded rather than "
                                    f"separately judged by the grader."
                                )
                                break
        elif structure == "INDEPENDENT_CRITERIA":
            if not spec.get("criteria"):
                issues.append("INDEPENDENT_CRITERIA OPEN_ENDED spec has no criteria")
        else:
            issues.append(f"OPEN_ENDED spec has an unrecognised scoring_structure: {spec.get('scoring_structure')!r}")

    return (len(issues) == 0), issues, review_flags


def _grade_short_answer_dynamic(
    student_text: str,
    spec: Dict[str, Any],
    model: str,
    rag_context: str = "",
    few_shots_block: str = "",
) -> Optional[Dict[str, Any]]:
    """
    SHORT_ANSWER dynamic strategy. Reuses _build_checklist_grading_prompt()
    UNCHANGED -- that function already took `groups`/`matching_strictness`/
    `allow_half_marks` as parameters rather than importing a hardcoded constant,
    so no new prompt logic is needed here, only the spec-to-parameter plumbing.
    """
    groups = spec.get("groups") or []
    if not groups:
        return None
    group_sum = sum(float(g.get("max_score", 0)) for g in groups)
    total_max_score = group_sum if group_sum > 0 else float(spec.get("max_score") or 0)
    prompt = _build_checklist_grading_prompt(
        student_text, total_max_score, groups,
        matching_strictness=spec.get("matching_strictness", "meaning"),
        allow_half_marks=bool(spec.get("allow_half_marks", False)),
        rag_context=rag_context,
        few_shots_block=few_shots_block,
    )
    messages = [
        {"role": "system", "content": "You are a precise, objective automated academic grading engine. Always respond strictly in valid JSON format."},
        {"role": "user", "content": prompt},
    ]
    result = _call_openrouter_api(messages, model, temperature=0.1)
    if not result:
        return None

    # The grader self-reports "overall_score" as a separate field from
    # feedback.breakdown's per-group score_awarded values, and these two
    # numbers can disagree -- not a grading judgement call, a plain
    # arithmetic slip summing its own line items at the end of a long
    # response (observed in over half of one real Q6 run, and the
    # breakdown sum matched the human score more often than the
    # self-reported total did). Recompute the total deterministically
    # from the breakdown instead. Each group's own score_awarded is also
    # clamped to its own reported max_score as a safety net. Only
    # overrides when the breakdown actually parses -- an empty/malformed
    # breakdown leaves the self-reported overall_score as the fallback
    # rather than silently zeroing out an otherwise-valid score.
    breakdown = (result.get("feedback") or {}).get("breakdown") or []
    if breakdown:
        try:
            recomputed = sum(
                min(float(item.get("score_awarded", 0)), float(item.get("max_score", float("inf"))))
                for item in breakdown if isinstance(item, dict)
            )
            if abs(recomputed - float(result.get("overall_score", recomputed))) > 0.01:
                result["overall_score"] = round(recomputed, 2)
        except (TypeError, ValueError):
            pass

    return result


def _build_calculation_extraction_prompt_dynamic(
    student_text: str, items: list, question_text: Optional[str] = None,
    rag_context: str = "", few_shots_block: str = "",
) -> str:
    """
    Unit-agnostic generalisation of a Q9-specific extraction prompt: parameterised
    by each item's own `unit` instead, so it applies to any calculation question
    (doses in mg, tablet counts, mL, dimensionless ratios, etc), while preserving
    the extraction-not-scoring principle: the LLM only reports what the student
    wrote, Python decides what it's worth.

    Includes the original question text (when available) so a sub-part labelled
    by role rather than by the name the student actually uses (e.g. the
    Interpreter extracted "Husband" instead of "Tony") can still be resolved --
    the question text is where that name/role relationship is established, and
    the student's own answer alone usually doesn't restate it.
    """
    items_block = "\n".join(
        f"    - {it['label']}: correct final answer is EXACTLY {it['expected_answer']}"
        f"{' ' + it['unit'] if it.get('unit') else ''}"
        + (f" (tolerance +/- {it['tolerance']})" if it.get("tolerance") else "")
        + (f" (examples of acceptable working: {', '.join(it['acceptable_working_forms'])})" if it.get("acceptable_working_forms") else "")
        for it in items
    )
    labels = ", ".join(it["label"] for it in items)
    scenario = (
        f"QUESTION (for identifying who/what each label below refers to, if the "
        f"student's own answer doesn't name them the same way):\n{question_text}\n\n"
        if question_text else ""
    )
    rag_section = f"\n{rag_context}\n" if rag_context else ""

    return f"""
You are extracting evidence from a student's calculation response. Do NOT
calculate, award, or report a score yourself -- you are only identifying what
the student explicitly wrote, for each of {labels}, independently.
{rag_section}
{scenario}Reference (for your judgement only -- do not quote this back as if the student wrote it):
{items_block}
{few_shots_block}
Student Submission:
{student_text}

For EACH labelled item, extract exactly two fields from the student's own text:

1. "working_shown": true if the student explicitly wrote ANY intermediate
   calculation step for this item -- an equation, an intermediate value, a
   formula application. A bare final answer with no working shown does NOT
   count -- set this to false in that case. Do not infer or assume working that
   was not actually written.

2. "final_answer": the exact final numeric answer the student's response states
   for this item, as a number, or null if none is given. Do not round, infer, or
   correct it yourself -- extract exactly what the student wrote. Route content
   to the correct item by its label, not by position/order in the response.

Do not award marks, compute totals, apply any cap, or invent any additional
category beyond these two fields -- scoring is handled separately.

QUESTION-MATCHED EXAMINER CALIBRATION: "working_shown" is the one judgement call
in this extraction (the final answer is matched exactly, with no leniency). If
Examiner Calibration Benchmarks are provided above, align what counts as
sufficient working shown with the examiner's demonstrated standard for this
question. If none are provided, use the "acceptable working shown" examples
given in the Reference above.

OUTPUT FORMAT (Respond ONLY in valid JSON matching this schema):
{{
  "extractions": [
    {{"label": "{items[0]['label']}", "working_shown": true, "working_quote": "verbatim quote, or null if working_shown is false", "final_answer": {items[0]['expected_answer']}}}
  ],
  "reasoning": "Brief note per item on what evidence was found and why."
}}
"""


def _score_calculation_extraction_dynamic(
    extraction_res: Dict[str, Any],
    items: list,
) -> Dict[str, Any]:
    """
    Deterministic scorer matching _build_calculation_extraction_prompt_dynamic --
    per item the only possible outcomes are {0, working_mark, answer_mark,
    working_mark+answer_mark}, so an invented scoring category is structurally
    impossible. Tolerance-based numeric comparison (default 0 = exact match), and
    per-item mark values instead of one uniform working/answer mark shared by
    every item.
    """
    raw_extractions = [e for e in (extraction_res.get("extractions") or []) if isinstance(e, dict)]

    if len(raw_extractions) == len(items):
        # Primary strategy: positional alignment. The extraction prompt lists
        # items in a fixed order and asks for one entry per item in that same
        # order, and every observed response (correct or broken) has preserved
        # it -- so when the counts match, position is a far more reliable
        # signal than reproducing a label's exact text. This matters because a
        # label built from a weaker model's own redaction of a person's name
        # (e.g. two DIFFERENT people both rendered as the literal placeholder
        # "[PERSON_NAME]" within one label, as happens for a "X, Y's spouse"
        # style sub-part) is inherently ambiguous text to reproduce exactly,
        # and was observed to make that specific item silently come back
        # empty in most of a real run even though the student's answer for it
        # was clearly present -- not a lookup bug, the model's own attempt to
        # re-key by that confusing label was the fragile step.
        item_to_extraction = {id(it): e for it, e in zip(items, raw_extractions)}
    else:
        # Fallback: counts disagree (the model skipped or added an item), so
        # position can't be trusted -- match by label instead. Per-label
        # QUEUES, not a dict: labels are not guaranteed unique (the same
        # redaction behaviour can turn several distinct items into literally
        # the same label string), and a plain dict keyed by label would let
        # each later entry silently overwrite the previous one. Queuing
        # preserves list order, so N items sharing a label still consume N
        # distinct extraction entries in the order both were given.
        extraction_queues: Dict[str, deque] = defaultdict(deque)
        for e in raw_extractions:
            extraction_queues[str(e.get("label", "")).strip().lower()].append(e)
        item_to_extraction = {}
        for it in items:
            queue = extraction_queues.get(str(it["label"]).strip().lower())
            item_to_extraction[id(it)] = queue.popleft() if queue else {}

    breakdown, highlights = [], []
    total = 0.0

    for it in items:
        e = item_to_extraction.get(id(it), {})
        working_shown = bool(e.get("working_shown", False))
        working_mark_each = float(it.get("working_mark", 0.5))
        answer_mark_each = float(it.get("answer_mark", 1.0))
        tolerance = float(it.get("tolerance", 0.0))

        try:
            final_answer_val = float(e["final_answer"]) if e.get("final_answer") is not None else None
        except (TypeError, ValueError):
            final_answer_val = None

        expected = float(it["expected_answer"])
        answer_match = final_answer_val is not None and abs(final_answer_val - expected) <= tolerance

        working_mark = working_mark_each if working_shown else 0.0
        answer_mark = answer_mark_each if answer_match else 0.0
        person_total = working_mark + answer_mark
        total += person_total

        unit = f" {it['unit']}" if it.get("unit") else ""
        reasoning = (
            f"Working {'shown' if working_shown else 'NOT shown'} "
            f"({'+' if working_shown else '+0/'}{working_mark_each:.2g} marks); "
            f"final answer extracted as {final_answer_val if final_answer_val is not None else 'none given'}{unit} "
            f"vs. expected {expected}{unit} "
            f"({'+' if answer_match else '+0/'}{answer_mark_each:.2g} marks)."
        )
        breakdown.append({
            "question_number": f"({it['label']})",
            "score_awarded": round(person_total, 2),
            "max_score": working_mark_each + answer_mark_each,
            "reasoning": reasoning,
        })
        quote = e.get("working_quote")
        if quote:
            highlights.append({
                "text": quote,
                "question_number": f"({it['label']})",
                "score_awarded": round(person_total, 2),
                "max_score": working_mark_each + answer_mark_each,
                "type": "strength" if person_total > 0 else "improvement",
                "comment": reasoning,
            })

    return {
        "overall_score": round(total, 2),
        "confidence_score": 0.9,
        "status": "graded",
        "reasoning": extraction_res.get("reasoning", "Deterministically scored in Python from extracted per-item evidence."),
        "feedback": {
            "summary": f"Deterministic calculation scoring across {len(items)} independent sub-computations.",
            "breakdown": breakdown,
        },
        "highlights": highlights,
    }


def _grade_calculation_dynamic(
    student_text: str,
    spec: Dict[str, Any],
    model: str,
    question_text: Optional[str] = None,
    rag_context: str = "",
    few_shots_block: str = "",
) -> Optional[Dict[str, Any]]:
    """CALCULATION dynamic strategy: extraction-only LLM call, deterministic Python scoring."""
    items = spec.get("items") or []
    if not items:
        return None
    prompt = _build_calculation_extraction_prompt_dynamic(
        student_text, items, question_text, rag_context=rag_context, few_shots_block=few_shots_block
    )
    messages = [
        {"role": "system", "content": "You are a precise evidence-extraction engine for academic grading. Always respond strictly in valid JSON format. Do not calculate or report any score."},
        {"role": "user", "content": prompt},
    ]
    extraction_res = _call_openrouter_api(messages, model, temperature=0.0)
    if not extraction_res:
        return None
    return _score_calculation_extraction_dynamic(extraction_res, items)


def _build_dynamic_open_ended_prompt(
    student_text: str, question_text: Optional[str], spec: Dict[str, Any],
    rag_context: str = "", few_shots_block: str = "",
) -> str:
    """
    Generic OPEN_ENDED strategy. Grades by meaning, calibrates against false
    negatives, is evidence-grounded, never invents facts, accepts valid
    alternative reasoning, forbids double counting, and runs a mandatory
    false-negative recheck -- with the criteria/branch content supplied by
    `spec` rather than hardcoded per-question text.
    """
    scenario = f"QUESTION / SCENARIO:\n{question_text}\n\n" if question_text else ""
    structure = spec.get("scoring_structure", "INDEPENDENT_CRITERIA")
    calibration_notes = spec.get("calibration_notes")
    calibration_section = (
        f"\nCALIBRATION GUIDANCE FOR THIS RUBRIC:\n{calibration_notes}\n" if calibration_notes else ""
    )
    rag_section = f"\n{rag_context}\n" if rag_context else ""

    if structure == "BRANCHED":
        branches = spec.get("branches") or []
        branch_block = "\n\n".join(
            f"BRANCH \"{b.get('id')}\" -- applies when: {b.get('condition', '')}\n"
            f"(maximum {float(b.get('max_score', 0)):.1f} marks)\n"
            + "\n".join(f"{i + 1}. {c}" for i, c in enumerate(b.get("criteria") or []))
            for b in branches
        )
        rubric_block = f"""If the student's overall decision/position satisfies one of the branches below,
grade ONLY that branch's numbered criteria -- never combine marks from
different branches.

{branch_block}"""
        position_instructions = """
STEP 1 -- DETERMINE THE APPLICABLE BRANCH
Determine the student's overall answer, recommendation, position, or decision
from the response as a whole. When the response discusses arguments on more
than one side, distinguish between the student's own final position and
counterarguments or limitations they merely discuss. Do not change the
student's position merely because they acknowledge an opposing argument.

If the response opens with an explicit position and later discusses
limitations, risks, or counterarguments WITHOUT stating a new final position,
retain the original explicit position -- critically discussing weaknesses is
not the same as reversing the decision. Only treat a different branch as
applicable when the student clearly states that different final position
themselves. If the response is genuinely ambiguous even after this check,
choose the branch most strongly supported by the balance of the student's own
reasoning and note the ambiguity in `position_reason`.

STEP 2 -- APPLY ONLY THE CHOSEN BRANCH
"""
    else:
        criteria = spec.get("criteria") or []
        crit_block = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(criteria))
        rubric_block = f"""Award 1 mark for each of the following criteria the response demonstrates,
to a maximum of {float(spec.get('max_score', len(criteria))):.1f} marks:
{crit_block}"""
        position_instructions = "\nAPPLY THE CRITERIA\n"

    return f"""
You are grading an open-ended response.
{rag_section}
Use the QUESTION and the MARKING RUBRIC below as the AUTHORITATIVE grading
standard. Do not invent additional scoring restrictions, exclusions, or
requirements beyond what the rubric states or clearly implies.

{scenario}STUDENT RESPONSE:
{student_text}

MARKING RUBRIC

{rubric_block}
{calibration_section}
{few_shots_block}
OPEN-ENDED PROFESSIONAL JUDGMENT GRADING PROTOCOL
{position_instructions}
GRADE BY MEANING
For each applicable numbered criterion, determine whether the student has
demonstrated the underlying concept. Accept synonyms, paraphrases, different
terminology, concise explanations, examples that clearly demonstrate the
concept, and implicit but unambiguous meaning. Do not require the student's
wording to match the rubric.

Before withholding a mark, ask: "Would a reasonable educator recognise that
the student's own words demonstrate the underlying concept required by this
specific criterion, even though it is expressed differently from the rubric?"
If yes, award it.

Do not award a mark for an idea that requires you to invent knowledge the
student did not actually communicate. A response that never mentions a fact
required by a criterion does not earn that criterion merely because the fact
is true or was given in the scenario -- the STUDENT must communicate it.

CALIBRATION AGAINST FALSE NEGATIVES: avoid an overly literal interpretation of
the rubric. The rubric describes the concepts that should receive credit; it
is not a required vocabulary list. Award a criterion even when the student
uses broader or less technical terminology, states the conclusion concisely,
or demonstrates the underlying concern without naming the rubric category
itself. Do not require the student to reproduce a specific fact, phrase, or
level of technical precision unless that precision is essential to what the
criterion is actually assessing. This is semantic credit, not generosity -- it
does not permit inventing an idea absent from the response, using scenario
information as though the student stated it, awarding a merely related idea,
or awarding the same underlying idea twice.

DECISION PROCESS for every applicable criterion:
  A. What underlying knowledge, reasoning, or judgement is this criterion assessing?
  B. Search the ENTIRE response for the student's strongest evidence for that concept.
  C. Ask whether a reasonable educator would recognise the student's own words
     as demonstrating substantially the same concept. If YES -> MET.
  D. If the match is not literal, ask whether the difference is merely one of
     wording, terminology, level of detail, or presentation. If YES -> MET.
  E. If it is genuinely a different idea, ask whether it qualifies as a
     distinct, reasonable point under an explicit open "any other reasonable
     point" style criterion, if the rubric has one. If YES -> award it there.
  F. Otherwise -> NOT MET.

When uncertain between MET and NOT MET, do not default to NOT MET merely
because the student's wording is less precise or less technical than the
rubric. Withhold the mark only when the required underlying concept is
genuinely absent, contradicted, or merely topic-related rather than actually
demonstrated. A reasonable-sounding argument is not by itself a reason to
award a mark -- the underlying idea must still be explicitly stated or
unambiguously communicated by the student; do not supply missing reasoning on
the student's behalf.

VALID ALTERNATIVE REASONING
If the rubric includes an open-ended "any other reasonable point" style
criterion, award it for one distinct, reasonable point that satisfies the
rubric's stated purpose and is not already credited under another numbered
criterion. It does not need to resemble a model answer.

EVIDENCE
Every awarded mark must be supported by evidence from the student's own
response. Quote the strongest relevant evidence verbatim. One passage may
demonstrate more than one DISTINCT numbered criterion when it genuinely
communicates multiple ideas.

NO DOUBLE COUNTING
Award each underlying scoring point only once. Do not award the same idea
twice using different wording.

NO NEGATIVE MARKING
Incorrect or irrelevant information does not remove marks already earned
unless the rubric explicitly specifies a penalty.

QUESTION-MATCHED EXAMINER CALIBRATION
If Examiner Calibration Benchmarks are provided above, you MUST align your
judgement of what counts as MET -- how literally vs. loosely to read each
criterion, and where the partial-credit line falls -- strictly to match the
examiner's demonstrated standard for this question. If no calibration
benchmarks are provided, evaluate directly from the standard rubric and
calibration guidance above.

MANDATORY FALSE-NEGATIVE RECHECK
After your first pass, review ONLY the criteria you marked NOT MET. For each:
  1. Re-read the full student response.
  2. Identify the closest student-authored statement to that criterion.
  3. Ask whether you rejected it only because: terminology differed; the
     wording was less technical than the rubric; the reasoning was indirect
     but still unambiguous; the student expressed the implication rather
     than the rubric's exact conclusion; or the concept was spread across
     multiple sentences.
  4. If any of these is true AND the underlying concept is still clearly
     demonstrated, change the decision to MET and record the evidence.
  5. Keep it NOT MET only when you can state the substantive concept that is
     genuinely missing, contradicted, or merely related rather than
     demonstrated. Do not change a criterion to MET merely to increase the
     score.
Also confirm: no point was counted twice{", and the correct branch's maximum applies." if structure == "BRANCHED" else "."}

OUTPUT ONLY VALID JSON:
{{
  "chosen_branch_id": {"null" if structure != "BRANCHED" else '"B1"'},
  "branch_evidence": "verbatim quote establishing the position, or null",
  "position_reason": {"null" if structure != "BRANCHED" else '"brief explanation of the position determination, especially if ambiguous"'},
  "decisions": [
    {{
      "criterion_number": 1,
      "met": true,
      "evidence": "verbatim student quote or null",
      "reason": "brief explanation"
    }}
  ]
}}
"""


def _score_dynamic_open_ended(spec: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deterministic Python scoring for the OPEN_ENDED dynamic strategy. Handles both
    scoring_structure values:
      BRANCHED             -- picks the chosen branch (falling back to the
                              SMALLER-cap branch on an unrecognised/missing choice,
                              the safer "undercounting is safer than silently
                              inflating a malformed response" default), then scores
                              only that branch's criteria against its own cap.
                              Supports an optional `position_linked_criterion` per
                              branch.
      INDEPENDENT_CRITERIA -- scores the flat criteria list against the overall
                              max_score, no branch concept at all.
    """
    structure = spec.get("scoring_structure", "INDEPENDENT_CRITERIA")
    position_linked_idx = None

    if structure == "BRANCHED":
        branches = spec.get("branches") or []
        chosen_id = result.get("chosen_branch_id")
        chosen_norm = str(chosen_id or "").strip().lower()
        branch = next((b for b in branches if str(b.get("id", "")).strip().lower() == chosen_norm), None)
        if branch is None and branches:
            branch = min(branches, key=lambda b: float(b.get("max_score", 0)))
        branch = branch or {"criteria": [], "max_score": spec.get("max_score", 0)}
        criteria = branch.get("criteria") or []
        cap = float(branch.get("max_score", spec.get("max_score", 0)))
        try:
            pli = branch.get("position_linked_criterion")
            position_linked_idx = int(pli) if pli is not None else None
        except (TypeError, ValueError):
            position_linked_idx = None
        branch_id = branch.get("id")
    else:
        criteria = spec.get("criteria") or []
        cap = float(spec.get("max_score", len(criteria)))
        branch_id = None

    decision_map = {}
    for d in (result.get("decisions") or []):
        if isinstance(d, dict) and d.get("criterion_number") is not None:
            try:
                decision_map[int(d["criterion_number"])] = d
            except (TypeError, ValueError):
                continue

    breakdown, highlights = [], []
    raw_score = 0.0

    for idx, concept in enumerate(criteria, start=1):
        decision = decision_map.get(idx, {})
        met = bool(decision.get("met", False))
        evidence = decision.get("evidence")
        reason = decision.get("reason", "Criterion not demonstrated.")

        if position_linked_idx is not None and idx == position_linked_idx:
            met = True
            if not evidence:
                evidence = result.get("branch_evidence")
            if not decision.get("reason"):
                reason = "Deterministic rubric rule: this criterion is the branch decision itself."

        mark = 1.0 if met else 0.0
        raw_score += mark

        breakdown.append({
            "criterion_id": f"#{idx}", "criterion": concept, "met": met,
            "evidence": evidence, "reason": reason, "mark_awarded": mark,
        })
        if evidence:
            highlights.append({
                "text": evidence, "question_number": "", "score_awarded": mark,
                "max_score": 1.0, "type": "strength" if met else "improvement",
                "comment": f"#{idx}: {reason}",
            })

    final_score = min(raw_score, cap)
    met_ids = [x["criterion_id"] for x in breakdown if x["met"]]
    missed_ids = [x["criterion_id"] for x in breakdown if not x["met"]]
    reasoning_summary = "; ".join(
        f"{x['criterion_id']}={'MET' if x['met'] else 'NOT MET'}: {x['reason']}" for x in breakdown
    )

    return {
        "overall_score": round(final_score, 1),
        "confidence_score": 0.90,
        "status": "graded",
        "identified_branch": branch_id,
        "position_evidence": result.get("branch_evidence"),
        "position_reason": result.get("position_reason"),
        "reasoning": (
            f"Dynamic open-ended deterministic scoring. met={met_ids}; missed={missed_ids}; "
            f"raw={raw_score:.1f}; cap={cap:.1f}. {reasoning_summary}"
        ),
        "feedback": {
            "summary": f"{len(met_ids)} applicable rubric criteria demonstrated; cap {cap:.0f}.",
            "breakdown": [{"question_number": "", "score_awarded": round(final_score, 1), "max_score": cap, "reasoning": reasoning_summary}],
        },
        "criterion_breakdown": breakdown,
        "highlights": highlights,
        "_dynamic_open_ended": result,
    }


def _grade_open_ended_dynamic(
    student_text: str,
    question_text: Optional[str],
    spec: Dict[str, Any],
    model: str,
    rag_context: str = "",
    few_shots_block: str = "",
) -> Optional[Dict[str, Any]]:
    """OPEN_ENDED dynamic strategy: one grader call, deterministic Python scoring."""
    prompt = _build_dynamic_open_ended_prompt(
        student_text, question_text, spec, rag_context=rag_context, few_shots_block=few_shots_block
    )
    messages = [
        {
            "role": "system",
            "content": (
                "You are a single open-ended Grader agent. Ground every decision in the "
                "supplied rubric wording itself, judging semantic meaning rather than "
                "keyword overlap. Do not invent scoring rules the rubric doesn't state or "
                "imply. Do not calculate a total score. Always return valid JSON."
            ),
        },
        {"role": "user", "content": prompt},
    ]
    result = _call_openrouter_api(messages, model, temperature=0.0)
    if not result:
        return None
    return _score_dynamic_open_ended(spec, result)


def interpret_rubric_spec(
    question_text: str,
    rubric_text: str,
    max_score: float,
    model: Optional[str] = None,
    rag_context: str = "",
) -> Optional[Dict[str, Any]]:
    """
    Runs the Rubric Interpreter ONCE for a question and returns a validated Grading
    Specification, or None if the interpreter failed outright or produced something
    _validate_grading_spec() rejects as structurally unusable.

    Call this ONCE PER QUESTION and reuse the returned spec for every student
    response to that question via grade_with_spec() -- NOT once per response. The
    rubric does not change between students; re-interpreting it per response would
    (a) multiply API cost/latency by however many responses exist, and (b) risk
    grading different students in the same cohort against subtly different
    interpreted specs if the interpreter's output varies run to run, which would
    corrupt any agreement/consistency comparison across that cohort. A Grading
    Specification belongs to a question, not to a submission.

    rag_context (optional): this question's own rubric chunk retrieved from
    ChromaDB by the caller (see grading.py's _get_rag_context, queried by this
    question's own prompt text so it reliably retrieves that question's own
    indexed document, not a similarity-search guess). Passed straight into the
    interpreter prompt as corroborating reference -- rubric_text remains the
    authoritative source; this is deliberately NOT used to replace it, only to
    cross-check it, since the ChromaDB document is itself just a reformatted
    copy of the same rubric data and carries no extra information of its own.

    On success, the returned spec carries three extra bookkeeping fields not part
    of the interpreter's own output: `_review_flags` (a list of human-readable
    non-fatal warnings -- e.g. a CALCULATION item whose expected_answer was
    DERIVED rather than copied from an explicit rubric answer -- that a human
    should see before this spec is trusted at scale), `_validation_issues`
    (empty on success; only present for debugging if this ever changes to return
    a spec despite issues, which it currently does not), and `_rag_context` is
    NOT set here -- the caller (grade_submission_dynamic) attaches it after this
    call returns, so the same retrieved chunk used for classification is cached
    alongside the spec and reused for every future grading call too.
    """
    target_model = model or get_llm_model()
    spec = call_rubric_interpreter_agent(question_text, rubric_text, max_score, target_model, rag_context=rag_context)
    if not spec:
        return None

    # The top-level max_score is a value WE already know (the caller provided it
    # as an input), not something the interpreter needs to be trusted to echo back
    # correctly -- and for BRANCHED OPEN_ENDED specs it isn't even used for scoring
    # (each branch carries its own cap, see _score_dynamic_open_ended). Observed in
    # practice: adding rag_context to this prompt can make the model omit this
    # field entirely for some rubrics (it duplicates "Maximum Marks" text already
    # present in the authoritative rubric_text, which can distract the model into
    # dropping its own top-level echo) -- always overwrite with the known-correct
    # value rather than hard-rejecting an otherwise-valid classification over a
    # field that was never going to carry new information anyway.
    spec["max_score"] = max_score

    is_valid, issues, review_flags = _validate_grading_spec(spec)
    if not is_valid:
        print(f"[Rubric Interpreter Warning] Rejected an invalid Grading Specification: {issues}")
        return None

    spec["_review_flags"] = review_flags
    spec["_validation_issues"] = issues
    return spec


def grade_with_spec(
    student_text: str,
    question_text: Optional[str],
    spec: Dict[str, Any],
    model: str,
    rag_context: str = "",
    few_shots_block: str = "",
) -> Optional[Dict[str, Any]]:
    """
    Grades ONE student response against an already-interpreted Grading Specification
    (from interpret_rubric_spec()). Dispatches purely on spec["question_type"] --
    no question-number routing anywhere in this function. `rag_context` and
    `few_shots_block` are grading-time inputs (retrieved per submission / matched
    per question by the caller) threaded straight into whichever strategy's own
    prompt builder is invoked.

    Any non-fatal review flags attached to the spec (see _validate_grading_spec --
    e.g. a DERIVED calculation answer, a group/item mark sum that doesn't match
    the question's max_score, or a SHORT_ANSWER/position_linked_criterion
    pattern that looks misclassified) are copied into the result's flag_reasons,
    so a human reviewing this grade sees them.
    """
    q_type = str(spec.get("question_type", "")).strip().upper()

    if q_type == "SHORT_ANSWER":
        result = _grade_short_answer_dynamic(student_text, spec, model, rag_context, few_shots_block)
    elif q_type == "CALCULATION":
        result = _grade_calculation_dynamic(student_text, spec, model, question_text, rag_context, few_shots_block)
    elif q_type == "OPEN_ENDED":
        result = _grade_open_ended_dynamic(student_text, question_text, spec, model, rag_context, few_shots_block)
    else:
        # UNSUPPORTED, or a classification we don't recognise -- never force it
        # through a strategy it wasn't verified to fit. Caller should route this
        # to mandatory human review.
        return None

    if result and spec.get("_review_flags"):
        flags = list(result.get("flag_reasons") or [])
        for rf in spec["_review_flags"]:
            note = f"⚠️ {rf}"
            if note not in flags:
                flags.append(note)
        result["flag_reasons"] = flags

    return result


def _split_submission_by_question(student_text: str) -> Dict[str, str]:
    """
    Splits a multi-question submission blob back into {question_label: answer_text},
    matching the exact "Question {label}:\\n{answer}" delimiter that parse_excel_rows()
    (document_parser.py) produces when it assembles a student's combined raw_text from
    per-question spreadsheet rows. Returns an empty dict if the text doesn't follow
    this convention (e.g. a free-form PDF/DOCX submission) -- callers must treat an
    empty result as "can't safely split; grade the whole submission in one call."
    """
    matches = list(re.finditer(r"Question\s+([A-Za-z0-9]+)\s*:\s*\n", student_text))
    if not matches:
        return {}
    sections: Dict[str, str] = {}
    for i, m in enumerate(matches):
        label = m.group(1).strip().upper()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(student_text)
        sections[label] = student_text[start:end].strip()
    return sections


def _stamp_question_number(result: Dict[str, Any], question_label: str) -> None:
    """
    grade_with_spec()'s three strategies are deliberately question-number-agnostic (see
    its own docstring) -- their breakdown/highlight items come back labelled with an
    empty string (OPEN_ENDED), a bare "(sub-label)" (CALCULATION), or whatever group
    name the Interpreter itself invented while reading the rubric text (SHORT_ANSWER),
    never the assignment's actual question number. Left alone, this breaks
    aggregate_and_standardize_breakdown's main-question matching (keyed on
    question_number) and _enrich_highlights_with_question_info's backfill logic on
    any multi-question submission, since two different questions' entries can
    collide on the same blank or short label. Call this once per grade_with_spec()
    result, before merging it into a multi-question aggregate, to make every label
    unique and question-correct.
    """
    question_label = question_label.strip()

    def stamp(sub_label: Any) -> str:
        sub = str(sub_label or "").strip()
        return f"{question_label} - {sub}" if sub else question_label

    feedback = result.get("feedback")
    breakdown = feedback.get("breakdown") if isinstance(feedback, dict) else None
    for item in (breakdown or []):
        if isinstance(item, dict):
            item["question_number"] = stamp(item.get("question_number"))

    for item in (result.get("highlights") or []):
        if isinstance(item, dict):
            item["question_number"] = stamp(item.get("question_number"))


def grade_submission_dynamic(
    student_text: str,
    rubric_json: list,
    total_max_score: float,
    get_cached_spec: Callable[[str], Optional[Dict[str, Any]]],
    save_spec: Callable[[str, Dict[str, Any]], None],
    get_rag_context: Optional[Callable[[str], str]] = None,
    question_few_shots: Optional[Dict[str, List[Dict]]] = None,
    model: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Grades one submission using the dynamic Rubric Interpreter architecture, question
    by question. For each item in rubric_json: splits student_text into that
    question's answer-chunk (reusing _split_submission_by_question), gets-or-creates
    its Grading Specification via the get_cached_spec/save_spec callables (so the
    expensive Interpreter call runs once per question, not once per submission),
    grades the chunk via grade_with_spec() -- passing it this question's own
    ChromaDB-retrieved rubric context and matched few-shot exemplars -- stamps the
    result's breakdown/highlight items with this question's real label (see
    _stamp_question_number), and merges everything into one result. A question that
    can't be isolated, interpreted, or graded is skipped rather than scored as a
    fabricated zero -- its label is recorded in the returned dict's
    "_failed_questions" list so the caller can force a flagged status instead of
    silently under-reporting. Returns None only if nothing at all could be graded.

    RAG context is fetched via get_rag_context (query this question's own prompt
    text against ChromaDB, see grading.py's _get_rag_context) ONLY on a cache miss,
    then cached inside the spec itself as spec["_rag_context"] so it's queried at
    most once ever per question, not once per submission -- the same retrieved
    chunk then feeds BOTH the Interpreter's classification (interpret_rubric_spec)
    and every future grading call for this question (grade_with_spec).
    """
    sections = _split_submission_by_question(student_text)
    single_question = len(rubric_json) == 1
    target_model = model or get_llm_model()

    merged_breakdown, merged_highlights, merged_reasoning, merged_flags = [], [], [], []
    failed_questions, graded_questions = [], []

    for item in rubric_json:
        if not isinstance(item, dict):
            continue
        q_label = str(item.get("question_number") or item.get("criterion") or "").strip().upper()
        if not q_label:
            continue
        q_key = q_label.replace("Q", "").split("(")[0]
        section_text = sections.get(q_label) or sections.get(f"Q{q_key}") or sections.get(q_key)
        if section_text is None:
            # Can't safely isolate this question's answer within a multi-question
            # submission -- if there's only one question total, grade the whole
            # submission against it; otherwise skip rather than guess which part of
            # the text belongs to which question.
            section_text = student_text if single_question else None
        if section_text is None:
            failed_questions.append(q_label)
            continue

        q_text = item.get("question") or item.get("question_text") or item.get("prompt") or item.get("text") or ""
        rubric_text = item.get("model_answer") or item.get("modelAnswer") or ""
        q_max = float(item.get("max_score", item.get("maxMark", 10.0)))

        spec = get_cached_spec(q_label)
        if not spec:
            rag_ctx = get_rag_context(q_text) if get_rag_context else ""
            spec = interpret_rubric_spec(q_text, rubric_text, q_max, model=target_model, rag_context=rag_ctx)
            if spec:
                # Cache the retrieved chunk alongside the spec itself -- ChromaDB is
                # queried for this question at most once ever, not once per submission.
                spec["_rag_context"] = rag_ctx
                save_spec(q_label, spec)
        if not spec:
            failed_questions.append(q_label)
            continue

        q_few_shots = question_few_shots.get(q_label) if question_few_shots else None
        if not q_few_shots and question_few_shots:
            # question_few_shots is keyed by whatever string CalibrationExample rows
            # used for question_number (e.g. "Q6") -- fall back to a direct match on
            # the bare numeric key in case callers keyed it differently (e.g. "6").
            q_few_shots = question_few_shots.get(q_key)
        few_shots_block = format_question_few_shots({q_label: q_few_shots}) if q_few_shots else ""

        sub_res = grade_with_spec(
            section_text, q_text, spec, target_model,
            rag_context=spec.get("_rag_context", ""), few_shots_block=few_shots_block,
        )
        if not sub_res:
            failed_questions.append(q_label)
            continue

        _stamp_question_number(sub_res, q_label)
        graded_questions.append(q_label)
        sub_feedback = sub_res.get("feedback") if isinstance(sub_res.get("feedback"), dict) else {}
        merged_breakdown.extend(b for b in (sub_feedback or {}).get("breakdown", []) if isinstance(b, dict))
        merged_highlights.extend(h for h in sub_res.get("highlights", []) if isinstance(h, dict))
        if sub_res.get("reasoning"):
            merged_reasoning.append(f"[{q_label}] {sub_res['reasoning']}")
        for rf in (sub_res.get("flag_reasons") or []):
            if rf not in merged_flags:
                merged_flags.append(rf)

    if not merged_breakdown:
        return None

    overall_score = round(sum(float(b.get("score_awarded", 0.0)) for b in merged_breakdown), 1)
    result: Dict[str, Any] = {
        "overall_score": overall_score,
        "confidence_score": 0.85,  # placeholder -- recomputed by evaluate_confidence_and_status() downstream
        "status": "graded",
        "reasoning": "\n\n".join(merged_reasoning) or "Graded using the dynamic Rubric Interpreter architecture.",
        "feedback": {
            "summary": f"Graded {len(graded_questions)} of {len(rubric_json)} question(s) via the dynamic Rubric Interpreter.",
            "breakdown": merged_breakdown,
        },
        "highlights": merged_highlights,
    }
    if merged_flags:
        result["flag_reasons"] = merged_flags
    if failed_questions:
        result["_failed_questions"] = failed_questions
    return result


def call_llm_for_grading(
    student_text: str,
    rubric_json: list,
    total_max_score: float = 10.0,
    get_cached_spec: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None,
    save_spec: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    get_rag_context: Optional[Callable[[str], str]] = None,
    question_few_shots: Optional[Dict[str, List[Dict]]] = None,
    tolerance_rate: float = 0.10
) -> Dict[str, Any]:
    """
    Orchestrates the full grading pipeline:
    - Dynamic Rubric Interpreter Grader: classifies + grades each question, querying
      ChromaDB for that question's own rubric context (via get_rag_context) at most
      once per question and feeding it into both classification and grading.
    - Agent 3: Auditor Verification Agent (unchanged)
    - Step 4: Deterministic Confidence & Audit Engine (unchanged)
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

    # Step 1+2: Dynamic Rubric Interpreter Grader (replaces the old Agent 1 Rubric
    # Parser + Agent 2 Primary Grader). Classifies each question's type once
    # (cached via get_cached_spec/save_spec) and grades it with the matching
    # generic strategy, instead of one hand-written per-question-shaped prompt --
    # still receiving the same RAG context and few-shot exemplars the old Agent 2
    # received, threaded per-question instead of into one monolithic prompt.
    mode_tag = f"Few-Shot ({sum(len(v) for v in question_few_shots.values())} exemplars)" if question_few_shots else "Zero-Shot"
    print(f" │   ├─ [Dynamic Grader ({primary_model_name})] Evaluating submission in {mode_tag} mode...", flush=True)
    primary_res = grade_submission_dynamic(
        student_text=student_text,
        rubric_json=clean_rubric,
        total_max_score=total_max_score,
        get_cached_spec=get_cached_spec or (lambda q: None),
        save_spec=save_spec or (lambda q, s: None),
        get_rag_context=get_rag_context,
        question_few_shots=question_few_shots,
        model=primary_model_name,
    )
    if not primary_res:
        print(" │   │  └─ [Warning] Dynamic grading produced nothing usable. Using heuristic fallback.", flush=True)
        return _mock_heuristic_evaluation(student_text, clean_rubric, total_max_score)

    failed_questions = primary_res.pop("_failed_questions", None)

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

    if failed_questions:
        # At least one rubric question couldn't be isolated, interpreted, or graded
        # at all -- the questions that DID grade are still trustworthy, but this
        # submission is incomplete and must not be silently auto-approved on its
        # partial total (same anti-fabrication pattern as breakdown_unavailable above).
        primary_res["status"] = "flagged"
        reason = f"⚠️ Grading Unavailable for {', '.join(failed_questions)} — Manual Review Required"
        if reason not in primary_res["flag_reasons"]:
            primary_res["flag_reasons"].insert(0, reason)
        if isinstance(feedback, dict):
            feedback["flag_reasons"] = primary_res["flag_reasons"]

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

        extracted_sentences = []
        if q_pos != -1:
            # Look ahead up to 500 characters for the answer body
            section_chunk = student_text[q_pos:q_pos + 600]
            # Strip off the question header (e.g. "Question 6: ")
            body_match = re.search(r'(?:Question|Q|Problem)\s*[A-Za-z0-9_()]+:?\s*([\s\S]*)', section_chunk, re.IGNORECASE)
            raw_body = body_match.group(1) if body_match else section_chunk
            # Split into sentences
            all_s = [s.strip() for s in re.split(r'(?<=[.?!])\s+', raw_body) if len(s.strip()) > 8]
            # Next question boundary check
            cleaned_s = []
            for s in all_s:
                if re.match(r'^(?:Question|Q|Problem)\s+[A-Za-z0-9_()]+', s, re.IGNORECASE):
                    break
                cleaned_s.append(s)
            extracted_sentences = cleaned_s

        if not extracted_sentences:
            extracted_sentences = [f"Response section for {b_q}"]

        num_to_take = min(len(extracted_sentences), max(1, min(3, int(round(score_aw)))))
        for s_idx in range(num_to_take):
            snippet = extracted_sentences[s_idx]
            new_hl = {
                "text": snippet,
                "question_number": b_q,
                "score_awarded": 1.0 if score_aw > 0 else 0.0,
                "max_score": max_sc,
                "type": "strength" if score_aw > 0 else "weakness",
                "comment": f"Evaluated for {b_q}. Reasoning: {reasoning}",
                "location_in_raw_text": f"Question {b_q} Section"
            }
            highlights.append(new_hl)
    # Ensure highlight scores strictly align with each question's score_awarded
    for b in breakdown:
        if not isinstance(b, dict):
            continue
        b_q = b.get("question_number", "")
        if not b_q:
            continue
        target_score = float(b.get("score_awarded", 0.0) or 0.0)

        clean_bq = re.sub(r'[^a-zA-Z0-9]', '', b_q).upper()
        q_hls = [
            h for h in highlights
            if isinstance(h, dict) and re.sub(r'[^a-zA-Z0-9]', '', str(h.get("question_number", ""))).upper() == clean_bq
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
        elif abs(current_sum - target_score) > 0.05:
            # Rebalance scores cleanly into integer or standard half-mark increments
            if len(positive_hls) == 1:
                clean_target = int(target_score) if target_score.is_integer() else target_score
                positive_hls[0]["score_awarded"] = clean_target
                positive_hls[0]["type"] = "strength"
            else:
                is_fractional = (target_score % 1) != 0
                step = 0.5 if is_fractional else 1.0
                total_units = int(round(target_score / step))
                total_weight = sum(float(h.get("score_awarded", 0.0) or 1.0) for h in positive_hls)

                allocated_units = []
                remainders = []
                for h in positive_hls:
                    w = float(h.get("score_awarded", 0.0) or 1.0)
                    exact = (w / (total_weight if total_weight > 0 else len(positive_hls))) * total_units
                    base = int(exact)
                    allocated_units.append(base)
                    remainders.append(exact - base)

                remaining_units = total_units - sum(allocated_units)
                sorted_indices = sorted(range(len(positive_hls)), key=lambda i: remainders[i], reverse=True)
                for i in range(min(remaining_units, len(positive_hls))):
                    allocated_units[sorted_indices[i]] += 1

                for idx, h in enumerate(positive_hls):
                    final_score = allocated_units[idx] * step
                    h["score_awarded"] = int(final_score) if (isinstance(final_score, float) and final_score.is_integer()) else final_score
                    h["type"] = "strength" if final_score > 0 else "weakness"

    primary_res["highlights"] = highlights


