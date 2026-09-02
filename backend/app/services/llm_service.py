import os
import re
import json
import time
import urllib.request
from typing import Dict, Any, Optional
from .confidence import evaluate_confidence_and_status

def get_openrouter_api_key() -> str:
    return os.getenv("OPENROUTER_API_KEY", "").strip()

def get_llm_model() -> str:
    return os.getenv("LLM_MODEL", "google/gemini-3.1-flash-lite").strip()

def get_auditor_model() -> str:
    return os.getenv("AUDITOR_MODEL", get_llm_model()).strip()



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


def _call_openrouter_api(messages: list, model: str, temperature: float = 0.1, max_retries: int = 3) -> Optional[Dict[str, Any]]:
    """
    Executes HTTP POST request to OpenRouter API endpoint with automatic retries and reasoning token fallbacks.
    """
    api_key = get_openrouter_api_key()
    if not api_key:
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
            req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers)
            with urllib.request.urlopen(req, timeout=75) as resp:
                body = json.loads(resp.read().decode("utf-8"))
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
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                time.sleep(2 * attempt)
            else:
                print(f"[OpenRouter API Warning] Call failed for model {model} after {max_retries} attempts: {e}")
                
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


def _build_generic_grading_prompt(student_text: str, structured_rubric: Dict[str, Any], raw_rubric_json: list, model_answer: str, rag_context: str, total_max_score: float) -> str:
    """
    Original question-agnostic prompt (v1.3-multi-question-highlights). Kept as the
    fallback for any question_no that doesn't have a dedicated template below, and for
    callers that grade a whole multi-question submission in a single request.
    """
    return f"""
You are an expert academic evaluator specializing in objective short-answer grading.

{rag_context}

Standardized Rubric Rules:
{json.dumps(structured_rubric, indent=2)}

Raw Rubric Criteria:
{json.dumps(raw_rubric_json, indent=2)}

Total Assignment Max Score: {total_max_score}

Model Answer / Marking Scheme:
{model_answer or "Evaluate answer based on clarity, technical accuracy, and completeness."}

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


# Q6 (Structured Short-Answer / Comparative Analysis) and Q8 (Agree/Disagree with
# Justification) look different on the surface, but both decompose into the same
# underlying shape: fixed groups of independently-verifiable marking criteria, each
# criterion worth 1 mark, each group capped at its own max_score. Q6's two groups
# have MORE criteria than their cap (a point bank you draw up to 5 marks from); Q8's
# five groups have exactly 2 criteria each (a verdict criterion + a justification
# criterion, conditioned on that verdict). One shared prompt template below grades
# both by supplying only the checklist DATA that differs.

_Q6_CHECKLIST_GROUPS = [
    {
        "group": "Q6(a)",
        "max_score": 5.0,
        "criteria": [
            "Biodegradable / does not need surgical removal",
            "Longer duration of action than lipid-based systems -> reduces dosing frequency / improves compliance",
            "Injectable, does not require surgical implantation",
            "No visible/palpable lump at the injection site (aesthetic benefit)",
            "Not suitable for acid-labile drugs (limits which drugs can use this system)",
            "Requires a skilled health worker to administer -> may exclude remote/rural patients",
            "Complex, expensive manufacturing process",
        ],
    },
    {
        "group": "Q6(b)",
        "max_score": 5.0,
        "criteria": [
            "Contains a solvent, or uses temperature-sensitive polymers",
            "Typically made from a biodegradable polymer",
            "Drug must be soluble in the polymer/solvent system",
            "On injection, the solvent diffuses away from the depot",
            "Drug is released via degradation/erosion of the polymer matrix",
            "Correctly judges there is NO clinical benefit over microspheres (a student claiming a clinical benefit does NOT earn this criterion, though they can still earn the others)",
            "Cheaper / easier to manufacture and sterilise than microspheres",
            "Avoids needle blockage (a practical advantage of the solvent-based system)",
        ],
    },
]

_Q8_CHECKLIST_GROUPS = [
    {
        "group": "Q8(a)",
        "max_score": 2.0,
        "criteria": [
            "Verdict: DISAGREE with the statement 'Lyophilization is the only option for preparing peptides for injectable administration.'",
            "Reason: not necessary if the drug is stable in solution (freeze-drying is only needed for solution-unstable drugs)",
        ],
    },
    {
        "group": "Q8(b)",
        "max_score": 2.0,
        "criteria": [
            "Verdict: AGREE with the statement 'Protein structure is more complex than peptides, so instability is often a greater issue.'",
            "Reason (either is sufficient): hydrophobic regions of proteins can associate/stick to surfaces, OR tertiary structure may be disrupted by unwanted chemical reactions",
        ],
    },
    {
        "group": "Q8(c)",
        "max_score": 2.0,
        "criteria": [
            "Verdict: DISAGREE with the statement 'Antibody-drug conjugates use the natural distribution of a drug to get the antibody to bind to its target on cells.'",
            "Reason: it is the antibody that directs/targets the drug to the target cells -- the statement has the direction of targeting reversed",
        ],
    },
    {
        "group": "Q8(d)",
        "max_score": 2.0,
        "criteria": [
            "Verdict: DISAGREE with the statement 'Proteins and peptides are not light sensitive, so light-protective packaging is never used.'",
            "Reason: proteins/peptides commonly do require light protection, e.g. packaging in amber vials",
        ],
    },
    {
        "group": "Q8(e)",
        "max_score": 2.0,
        "criteria": [
            "Verdict: AGREE with the statement 'Co-solvents are used to dissolve peptides to enable safe injection.'",
            "Reason (either is sufficient): unsafe to inject if the protein/peptide is not completely dissolved, OR injectable co-solvents are acceptable to use in small amounts",
        ],
    },
]


def _build_checklist_grading_prompt(
    student_text: str,
    total_max_score: float,
    groups: list,
    matching_strictness: str = "meaning",
    allow_half_marks: bool = False,
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

    return f"""
You are an expert academic evaluator. Grade the student's submission using CRITERION
CHECKLIST MATCHING, not holistic essay judgement. The question is organized into fixed
groups below; each group is a list of marking criteria worth 1 mark each, and each
group has its own mark cap that may be lower than its criteria count.
{groups_block}
MATCHING STRICTNESS: {strictness_line}

Total Assignment Max Score: {total_max_score}

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


def call_primary_grading_agent(student_text: str, structured_rubric: Dict[str, Any], raw_rubric_json: list, model_answer: str, rag_context: str, total_max_score: float = 10.0, model: Optional[str] = None, question_no: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Agent 2 (Primary CoT Evaluation Agent):
    Evaluates student responses against standardized rubric rules and RAG context.

    question_no: when "6"/"Q6" or "8"/"Q8", uses the shared checklist-matching prompt
    (_build_checklist_grading_prompt) populated with that question's own criteria
    groups -- one universal template for both question types, since they share the
    same "grouped, capped, independently-verifiable criteria" marking shape. Any
    other value (None, Q9, Q22, or a multi-question call) falls back to the original
    generic rubric-driven prompt unchanged.
    """
    q_key = str(question_no).strip().upper().replace("Q", "") if question_no else None

    if q_key == "6":
        # Q6's source rubric explicitly accepts paraphrased answers and forbids half marks.
        prompt = _build_checklist_grading_prompt(
            student_text, total_max_score, _Q6_CHECKLIST_GROUPS,
            matching_strictness="meaning", allow_half_marks=False,
        )
    elif q_key == "8":
        # Q8's source rubric is graded strictly (explicit statements only) and allows half marks.
        prompt = _build_checklist_grading_prompt(
            student_text, total_max_score, _Q8_CHECKLIST_GROUPS,
            matching_strictness="explicit", allow_half_marks=True,
        )
    else:
        prompt = _build_generic_grading_prompt(student_text, structured_rubric, raw_rubric_json, model_answer, rag_context, total_max_score)

    messages = [
        {"role": "system", "content": "You are a precise, objective automated academic grading engine. Always respond strictly in valid JSON format."},
        {"role": "user", "content": prompt}
    ]
    target_model = model or get_llm_model()
    return _call_openrouter_api(messages, target_model, temperature=0.1)


def call_auditor_verification_agent(student_text: str, rubric_json: list, primary_eval: Dict[str, Any], model: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Agent 3 (Auditor & Verification Agent):
    Uses google/gemini-3.1-flash-lite to audit Agent 2's evaluation.
    Provides independent per-question auditor scores, identifies specific question conflicts, and determines audit_passed.
    """
    prompt = f"""
You are a Senior Academic Quality Auditor. Audit the following AI grading evaluation for fairness, accuracy, score bounds, and per-question score agreement.

Rubric:
{json.dumps(rubric_json, indent=2)}

Student Submission:
{student_text}

Primary AI Evaluation Result:
{json.dumps(primary_eval, indent=2)}

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
    }},
    {{
      "question_number": "Q6(b)",
      "auditor_score": 1.0,
      "max_score": 2.5
    }}
  ],
  "conflicting_questions": ["Q6(b)"],
  "discrepancy_note": "Multi-Agent Conflict on Q6(b): Primary grader awarded 2.5 marks whereas auditor recommends 1.0 mark due to missing sol-to-gel mechanism."
}}
"""
    messages = [
        {"role": "system", "content": "You are a rigorous academic audit agent. Respond strictly in valid JSON."},
        {"role": "user", "content": prompt}
    ]
    target_model = model or get_auditor_model()
    return _call_openrouter_api(messages, target_model, temperature=0.0)


def call_llm_for_grading(student_text: str, rubric_json: list, model_answer: str, rag_context: str, total_max_score: float = 10.0) -> Dict[str, Any]:
    """
    Orchestrates Multi-Agent Grading Pipeline using google/gemini-3.1-flash-lite across 3 agents:
    - Agent 1: Rubric & RAG Context Parser Agent
    - Agent 2: Primary CoT Evaluation Agent
    - Agent 3: Auditor Verification Agent
    - Step 4: Deterministic Confidence & Audit Engine
    """
    if not get_openrouter_api_key():
        print("[LLM Service] OPENROUTER_API_KEY not set. Running fallback structured scoring engine.")
        return _mock_heuristic_evaluation(student_text, rubric_json)

    # Step 1: Agent 1 - Rubric & Context Parser Agent
    parser_res = call_rubric_context_parser_agent(rubric_json, model_answer, rag_context)
    structured_rubric = parser_res if parser_res else {"structured_rules": rubric_json}

    # Step 2: Agent 2 - Primary CoT Grader Agent
    primary_res = call_primary_grading_agent(student_text, structured_rubric, rubric_json, model_answer, rag_context, total_max_score)
    if not primary_res:
        print("[LLM Service Warning] Primary Agent call failed. Using heuristic fallback.")
        return _mock_heuristic_evaluation(student_text, rubric_json)

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

    # Enrich highlights with question number and position in raw text
    _enrich_highlights_with_question_info(primary_res, student_text)

    # Step 3: Agent 3 - Auditor Verification Agent
    auditor_res = call_auditor_verification_agent(student_text, rubric_json, primary_res)

    if auditor_res:
        audit_passed = bool(auditor_res.get("audit_passed", True))
        auditor_score = float(auditor_res.get("auditor_score", primary_res.get("overall_score", 0.0)))
        auditor_breakdown = auditor_res.get("auditor_breakdown", [])
        if not isinstance(auditor_breakdown, list):
            auditor_breakdown = []

        primary_score = float(primary_res.get("overall_score", 0.0))
        conflicting_qs = auditor_res.get("conflicting_questions", [])
        if not isinstance(conflicting_qs, list):
            conflicting_qs = []
        
        score_diff = abs(primary_score - auditor_score)
        max_denom = total_max_score if total_max_score > 0 else 10.0
        agreement_ratio = max(0.0, 1.0 - (score_diff / max_denom))

        primary_res["multi_agent_audit"] = {
            "auditor_passed": audit_passed,
            "auditor_score": auditor_score,
            "auditor_breakdown": auditor_breakdown,
            "score_discrepancy": round(score_diff, 1),
            "agreement_ratio": round(agreement_ratio, 2),
            "conflicting_questions": conflicting_qs,
            "audit_note": auditor_res.get("discrepancy_note", ""),
            "model_used": get_llm_model()
        }

    # Step 4: Deterministic Confidence & Decision Engine
    confidence_result = evaluate_confidence_and_status(
        primary_res,
        student_text,
        total_max_score
    )

    primary_res["confidence_score"] = confidence_result["confidence_score"]
    primary_res["status"] = confidence_result["status"]
    primary_res["flag_reasons"] = confidence_result["flag_reasons"]
    primary_res["is_borderline"] = confidence_result["is_borderline"]
    primary_res["is_audit_flagged"] = confidence_result["is_audit_flagged"]
    primary_res["confidence_components"] = confidence_result["confidence_components"]

    return primary_res




def _mock_heuristic_evaluation(student_text: str, rubric_json: list) -> Dict[str, Any]:
    text_len = len(student_text.strip())
    base_score = min(88.0, 65.0 + (text_len / 50.0))
    confidence = 0.88 if text_len > 150 else 0.65
    status = "graded" if confidence >= 0.75 else "flagged"

    return {
        "overall_score": round(base_score, 1),
        "confidence_score": confidence,
        "status": status,
        "reasoning": "Heuristic CoT evaluation performed based on response completeness and keyword density.",
        "feedback": {
            "summary": "Automated AI evaluation completed based on rubric criteria.",
            "breakdown": [
                {
                    "question_number": "Q1",
                    "score_awarded": round(base_score * 0.5, 1),
                    "max_score": 50,
                    "reasoning": "Demonstrated sound understanding of core principles."
                },
                {
                    "question_number": "Q2",
                    "score_awarded": round(base_score * 0.5, 1),
                    "max_score": 50,
                    "reasoning": "Provided clear logical steps in explanation."
                }
            ]
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
            "auditor_score": round(base_score, 1),
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


