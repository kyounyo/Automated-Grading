import os
import re
import json
import time
import urllib.request
from collections import defaultdict, deque
from typing import Dict, Any, Optional, Callable
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
        if not score_m:
            # A missing overall_score after two repair attempts means this response
            # doesn't actually contain a parseable score. Previously this silently
            # became "0.0, status=graded" -- a real Q22 grading run hit exactly this
            # path and a genuine human score of 6 was recorded as an AI score of 0
            # with the model never actually having been "wrong." Raise instead so the
            # caller retries, and so a total failure is reported as a failure (routed
            # to _mock_heuristic_evaluation's flagged-for-review state) rather than a
            # fabricated, confidently-labelled grade.
            raise ValueError("No 'overall_score' field found in LLM response after JSON repair attempts.")

        conf_m = re.search(r'"confidence_score"\s*:\s*([0-9\.]+)', clean_text)
        summary_m = re.search(r'"summary"\s*:\s*"([^"]*)"', clean_text)

        ov_score = float(score_m.group(1))
        conf_score = float(conf_m.group(1)) if conf_m else 0.5
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


# =============================================================================
# DYNAMIC RUBRIC INTERPRETER: question-type routing instead of question-number
# routing, so a NEW question of an already-supported shape needs no code change
# =============================================================================
#
# A Rubric Interpreter LLM call classifies an ARBITRARY question+rubric into one of
# three grading strategies (SHORT_ANSWER / CALCULATION / OPEN_ENDED) and extracts a
# structured "Grading Specification" -- the criteria/items/branches -- directly from
# the rubric text, instead of a developer hand-transcribing them into a Python
# constant. Each strategy then receives that specification as DATA:
# _build_checklist_grading_prompt (SHORT_ANSWER) takes `groups` as a parameter, the
# CALCULATION strategy extracts-then-deterministically-scores against `items`, and
# the OPEN_ENDED strategy grades-by-meaning against `branches`/`criteria` -- the
# actual prompt engineering (semantic-equivalence wording, strictness dial, evidence
# grounding, no-double-counting, false-negative recheck, deterministic Python
# scoring) doesn't know anything about any one specific question's subject matter.
#
# This earlier coexisted with a hardcoded, question-number-routed path (Q6/Q8/Q9/Q22-
# specific prompts and Python constants) for head-to-head ICC benchmarking on a fixed
# 25-response sample per question -- that comparison is what validated this
# architecture before it became the only one. The hardcoded path and that comparison
# harness have since been removed; this is now the sole grading architecture.
#
# GRADING SPECIFICATION schema (the interpreter's output contract):
# {
#   "question_type": "SHORT_ANSWER" | "CALCULATION" | "OPEN_ENDED" | "UNSUPPORTED",
#   "max_score": float,
#
#   # SHORT_ANSWER only -- fed directly into the EXISTING, unmodified
#   # _build_checklist_grading_prompt(student_text, max_score, groups, ...):
#   "groups": [{"group": str, "max_score": float, "criteria": [str, ...]}],
#   "matching_strictness": "meaning" | "explicit",
#   "allow_half_marks": bool,
#
#   # CALCULATION only -- fed into the generic calculation strategy below (a
#   # unit-agnostic generalisation of _build_calculation_extraction_prompt /
#   # _score_calculation_extraction, which hardcode Q9's "chocolate squares" framing):
#   "items": [{
#       "label": str, "expected_answer": float, "tolerance": float,
#       "unit": str, "working_mark": float, "answer_mark": float,
#       "acceptable_working_forms": [str, ...],
#   }],
#
#   # OPEN_ENDED only:
#   "scoring_structure": "BRANCHED" | "INDEPENDENT_CRITERIA",
#   "branches": [{  # when BRANCHED (e.g. Q22's STOCK / DO_NOT_STOCK)
#       "id": str, "condition": str, "max_score": float,
#       "criteria": [str, ...],
#       "position_linked_criterion": int or null,  # generalises Q22's S1 auto-award
#                                                    # rule: 1-based index of a
#                                                    # criterion that IS the branch
#                                                    # decision itself, if the rubric
#                                                    # has one -- null if it doesn't.
#   }],
#   "criteria": [str, ...],  # when INDEPENDENT_CRITERIA (flat list, single cap)
# }
#
# IMPORTANT LIMITATION, stated up front rather than discovered later: "scalable"
# here means "a new question whose rubric fits one of these three shapes needs no
# prompt engineering or code change." It does NOT mean every conceivable assessment
# is covered -- a diagram-labelling or image-based question has no matching
# strategy, which is exactly why "UNSUPPORTED" is a valid classification: route
# that to mandatory human review, don't force it through OPEN_ENDED and hope.

def _build_rubric_interpreter_prompt(question_text: str, rubric_text: str, max_score: float) -> str:
    """
    Converts an arbitrary question + rubric into a Grading Specification (see the
    module comment above for the schema). Classifies structure, doesn't just
    reformat text -- this output feeds directly into deterministic Python scoring,
    so it must not invent anything the rubric doesn't actually support.
    """
    return f"""
You are an Academic Rubric Interpreter. Convert the question and marking rubric
below into a structured Grading Specification for an automated grading system.

QUESTION:
{question_text}

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
) -> Optional[Dict[str, Any]]:
    """Runs the Rubric Interpreter and returns a Grading Specification, or None on failure."""
    prompt = _build_rubric_interpreter_prompt(question_text, rubric_text, max_score)
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
        # Mirrors the SHORT_ANSWER group-sum check: each item's own working_mark +
        # answer_mark caps what _score_calculation_extraction_dynamic can award for
        # it, so the total can never exceed the sum of those caps -- but nothing
        # stops that sum from disagreeing with the question's own max_score if the
        # interpreter extracted inconsistent mark values. A student scoring full
        # marks would then still come back short of (or over) max_score.
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
                    # Heuristic safety net: position_linked_criterion was left null, but
                    # check whether a criterion merely restates this branch's own
                    # condition (the exact pattern the interpreter is supposed to catch
                    # and auto-award instead of asking the grader to separately judge
                    # something that's automatically true for this branch).
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
    # Prefer the group caps' own sum over spec["max_score"] when they disagree --
    # this matches what _validate_grading_spec's review_flag already claims
    # ("using the group sum as authoritative") for that exact mismatch. Each
    # group's own cap is what the prompt actually displays and instructs the
    # grader to enforce per-group; the "Total Assignment Max Score" line should
    # agree with that, not silently show a different number the grader never
    # sees broken down anywhere.
    group_sum = sum(float(g.get("max_score", 0)) for g in groups)
    total_max_score = group_sum if group_sum > 0 else float(spec.get("max_score") or 0)
    prompt = _build_checklist_grading_prompt(
        student_text, total_max_score, groups,
        matching_strictness=spec.get("matching_strictness", "meaning"),
        allow_half_marks=bool(spec.get("allow_half_marks", False)),
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
    # from the breakdown instead, the same "Python owns the final number,
    # the LLM only judges each line item" principle already applied to the
    # CALCULATION and OPEN_ENDED strategies. Each group's own score_awarded
    # is also clamped to its own reported max_score as a safety net. Only
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
    student_text: str, items: list, question_text: Optional[str] = None
) -> str:
    """
    Unit-agnostic generalisation of _build_calculation_extraction_prompt(): that
    function's wording is Q9-specific ("chocolate squares", "administration
    instruction"). This version is parameterised by each item's own `unit` instead,
    so it applies to any calculation question (doses in mg, tablet counts, mL,
    dimensionless ratios, etc), while preserving the same extraction-not-scoring
    principle that made Q9 reliable: the LLM only reports what the student wrote,
    Python decides what it's worth.

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

    return f"""
You are extracting evidence from a student's calculation response. Do NOT
calculate, award, or report a score yourself -- you are only identifying what
the student explicitly wrote, for each of {labels}, independently.

{scenario}Reference (for your judgement only -- do not quote this back as if the student wrote it):
{items_block}

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
    same structural guarantee as _score_calculation_extraction: per item the only
    possible outcomes are {0, working_mark, answer_mark, working_mark+answer_mark},
    so an invented scoring category is structurally impossible. Generalised to a
    tolerance-based numeric comparison (default 0 = exact match) instead of Q9's
    integer-squares comparison, and to per-item mark values instead of one uniform
    working/answer mark shared by every item.
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
) -> Optional[Dict[str, Any]]:
    """CALCULATION dynamic strategy: extraction-only LLM call, deterministic Python scoring."""
    items = spec.get("items") or []
    if not items:
        return None
    prompt = _build_calculation_extraction_prompt_dynamic(student_text, items, question_text)
    messages = [
        {"role": "system", "content": "You are a precise evidence-extraction engine for academic grading. Always respond strictly in valid JSON format. Do not calculate or report any score."},
        {"role": "user", "content": prompt},
    ]
    extraction_res = _call_openrouter_api(messages, model, temperature=0.0)
    if not extraction_res:
        return None
    return _score_calculation_extraction_dynamic(extraction_res, items)


def _build_dynamic_open_ended_prompt(student_text: str, question_text: Optional[str], spec: Dict[str, Any]) -> str:
    """
    Generic OPEN_ENDED strategy. Carries over the same grading BEHAVIOUR validated
    on Q22's rubric_semantic prompt (grade by meaning, calibrate against false
    negatives, evidence-grounded, no invented facts, valid alternative reasoning,
    no double counting, mandatory false-negative recheck) but with the criteria/
    branch content supplied by `spec` instead of the hardcoded
    _Q22_STOCK_CRITERIA_VERBATIM/_Q22_NOT_STOCK_CRITERIA_VERBATIM, and without the
    Q22-specific "limited evidence"/"no safety evidence" example boundaries (those
    were specific to that rubric's own concepts, not a generic principle).
    """
    scenario = f"QUESTION / SCENARIO:\n{question_text}\n\n" if question_text else ""
    structure = spec.get("scoring_structure", "INDEPENDENT_CRITERIA")
    calibration_notes = spec.get("calibration_notes")
    calibration_section = (
        f"\nCALIBRATION GUIDANCE FOR THIS RUBRIC:\n{calibration_notes}\n" if calibration_notes else ""
    )

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

This is a ONE-MODEL benchmark. There is NO auditor, second grader, or
adjudicator. Do NOT calculate or report a numerical total -- Python will
calculate the score from your criterion decisions.

Use the QUESTION and the MARKING RUBRIC below as the AUTHORITATIVE grading
standard. Do not invent additional scoring restrictions, exclusions, or
requirements beyond what the rubric states or clearly implies.

{scenario}STUDENT RESPONSE:
{student_text}

MARKING RUBRIC

{rubric_block}
{calibration_section}
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
                              the same safe-default principle _normalise_q22_position
                              uses), then scores only that branch's criteria against
                              its own cap. Supports an optional
                              `position_linked_criterion` per branch, generalising
                              Q22's deterministic S1 auto-award rule.
      INDEPENDENT_CRITERIA -- scores the flat criteria list against the overall
                              max_score, no branch concept at all.
    """
    structure = spec.get("scoring_structure", "INDEPENDENT_CRITERIA")
    position_linked_idx = None

    if structure == "BRANCHED":
        branches = spec.get("branches") or []
        chosen_id = result.get("chosen_branch_id")
        # Case/whitespace-insensitive match: the grading call sees the branch id
        # rendered inline in the prompt and is expected to echo it back exactly,
        # but nothing enforces that -- a casing slip here would otherwise fall
        # through to the smaller-cap fallback below and silently under-score an
        # otherwise-correctly-graded response.
        chosen_norm = str(chosen_id or "").strip().lower()
        branch = next((b for b in branches if str(b.get("id", "")).strip().lower() == chosen_norm), None)
        if branch is None and branches:
            # Safe fallback: smaller-cap branch, mirroring _normalise_q22_position's
            # "undercounting is safer than silently inflating a malformed response" rule.
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
) -> Optional[Dict[str, Any]]:
    """OPEN_ENDED dynamic strategy: one grader call, deterministic Python scoring."""
    prompt = _build_dynamic_open_ended_prompt(student_text, question_text, spec)
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

    On success, the returned spec carries two extra bookkeeping fields not part of
    the interpreter's own output: `_review_flags` (a list of human-readable
    non-fatal warnings -- e.g. a CALCULATION item whose expected_answer was
    DERIVED rather than copied from an explicit rubric answer -- that a human
    should see before this spec is trusted at scale) and `_validation_issues`
    (empty on success; only present for debugging if this ever changes to return
    a spec despite issues, which it currently does not).
    """
    target_model = model or get_llm_model()
    spec = call_rubric_interpreter_agent(question_text, rubric_text, max_score, target_model)
    if not spec:
        return None

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
) -> Optional[Dict[str, Any]]:
    """
    Grades ONE student response against an already-interpreted Grading Specification
    (from interpret_rubric_spec()). Dispatches purely on spec["question_type"] --
    no question-number routing anywhere in this function.

    Any non-fatal review flags attached to the spec (see _validate_grading_spec --
    e.g. a DERIVED calculation answer, a group/item mark sum that doesn't match
    the question's max_score, or a SHORT_ANSWER/position_linked_criterion
    pattern that looks misclassified) are copied into the result's flag_reasons,
    so a human reviewing this grade sees them, the same way the rest of this
    codebase surfaces "AI Grading Unavailable" or "Grading Breakdown Unavailable"
    rather than letting a caveat disappear into a log line.
    """
    q_type = str(spec.get("question_type", "")).strip().upper()

    if q_type == "SHORT_ANSWER":
        result = _grade_short_answer_dynamic(student_text, spec, model)
    elif q_type == "CALCULATION":
        result = _grade_calculation_dynamic(student_text, spec, model, question_text)
    elif q_type == "OPEN_ENDED":
        result = _grade_open_ended_dynamic(student_text, question_text, spec, model)
    else:
        # UNSUPPORTED, or a classification we don't recognise -- never force it
        # through a strategy it wasn't verified to fit. Caller should route this
        # to mandatory human review, the same way _mock_heuristic_evaluation does
        # for other failures.
        return None

    if result and spec.get("_review_flags"):
        flags = list(result.get("flag_reasons") or [])
        for rf in spec["_review_flags"]:
            note = f"⚠️ {rf}"
            if note not in flags:
                flags.append(note)
        result["flag_reasons"] = flags

    return result


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


def _split_submission_by_question(student_text: str) -> Dict[str, str]:
    """
    Splits a multi-question submission blob back into {question_label: answer_text},
    matching the exact "Question {label}:\n{answer}" delimiter that parse_excel_rows()
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
    confidence.py's primary-vs-auditor breakdown matching (keyed on question_number)
    and _enrich_highlights_with_question_info's backfill logic on any multi-question
    submission, since two different questions' entries can collide on the same blank
    or short label. Call this once per grade_with_spec() result, before merging it into
    a multi-question aggregate, to make every label unique and question-correct.
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
    model: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Grades one submission using the dynamic Rubric Interpreter architecture, question
    by question. For each item in rubric_json: splits student_text into that
    question's answer-chunk (reusing _split_submission_by_question), gets-or-creates
    its Grading Specification via the get_cached_spec/save_spec callables (so the
    expensive Interpreter call runs once per question, not once per submission --
    see interpret_rubric_spec's own docstring on why that matters), grades the chunk
    via grade_with_spec(), stamps the result's breakdown/highlight items with this
    question's real label (see _stamp_question_number), and merges everything into
    one result. A question that can't be isolated, interpreted, or graded is skipped
    rather than scored as a fabricated zero -- its label is recorded in the returned
    dict's "_failed_questions" list so the caller can force a flagged status instead
    of silently under-reporting. Returns None only if nothing at all could be graded
    (caller should fall back to _mock_heuristic_evaluation, same as every other total
    failure in this module).
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
            spec = interpret_rubric_spec(q_text, rubric_text, q_max, model=target_model)
            if spec:
                save_spec(q_label, spec)
        if not spec:
            failed_questions.append(q_label)
            continue

        sub_res = grade_with_spec(section_text, q_text, spec, target_model)
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
    total_max_score: float,
    get_cached_spec: Callable[[str], Optional[Dict[str, Any]]],
    save_spec: Callable[[str, Dict[str, Any]], None],
) -> Dict[str, Any]:
    """
    Orchestrates the full grading pipeline for one submission:
    - Primary grading: grade_submission_dynamic() -- the dynamic Rubric Interpreter
      architecture, question by question, with per-assignment spec caching via the
      get_cached_spec/save_spec callables (supplied by grading.py, bound to its own
      db session/Assignment row -- this module has no DB dependency of its own).
    - Agent: Auditor Verification Agent (independent re-grade + comparison)
    - Deterministic Confidence & Status Engine
    """
    if not get_openrouter_api_key():
        print("[LLM Service] OPENROUTER_API_KEY not set. Flagging submission for manual review.")
        return _mock_heuristic_evaluation(student_text, rubric_json, reason="OPENROUTER_API_KEY not configured")

    primary_res = grade_submission_dynamic(student_text, rubric_json, total_max_score, get_cached_spec, save_spec)
    if not primary_res:
        print("[LLM Service Warning] Dynamic grading produced nothing usable. Flagging submission for manual review.")
        return _mock_heuristic_evaluation(student_text, rubric_json, reason="dynamic grading failed for every question")

    failed_questions = primary_res.pop("_failed_questions", None)

    # Ensure feedback dictionary and breakdown list exist
    feedback = primary_res.get("feedback", {})
    if not isinstance(feedback, dict):
        feedback = {"summary": "AI Evaluation completed."}
        primary_res["feedback"] = feedback

    breakdown = feedback.get("breakdown", [])
    breakdown_unavailable = False
    if not breakdown or not isinstance(breakdown, list):
        # Previously this manufactured a per-question breakdown by splitting overall_score
        # proportionally across rubric items -- e.g. an undifferentiated 6/10 could turn
        # into a fabricated "Q6(a)=3.0, Q6(b)=3.0" split that never actually reflects which
        # criteria were met. That destroys criterion-level validity and silently hides a
        # real grading failure from the lecturer. Instead: leave the breakdown honestly
        # empty and force this submission to mandatory human review (below), rather than
        # inventing subquestion marks from a single total.
        breakdown = []
        feedback["breakdown"] = breakdown
        breakdown_unavailable = True

    # Recalculate overall_score as the exact sum of score_awarded across question breakdown items
    if breakdown:
        exact_breakdown_sum = sum(float(item.get("score_awarded", 0.0)) for item in breakdown if isinstance(item, dict))
        primary_res["overall_score"] = round(exact_breakdown_sum, 1)

    # Enrich highlights with question number and position in raw text
    _enrich_highlights_with_question_info(primary_res, student_text)

    # Agent: Auditor Verification Agent
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

    # Preserve any review flags grade_submission_dynamic already attached (e.g. a
    # DERIVED calculation answer warning) -- evaluate_confidence_and_status() below
    # builds its own flag_reasons list from scratch and knows nothing about these.
    pre_existing_flags = list(primary_res.get("flag_reasons") or [])

    # Deterministic Confidence & Decision Engine
    confidence_result = evaluate_confidence_and_status(
        primary_res,
        student_text,
        total_max_score
    )

    primary_res["confidence_score"] = confidence_result["confidence_score"]
    primary_res["status"] = confidence_result["status"]
    combined_flags = list(pre_existing_flags)
    for rf in confidence_result["flag_reasons"]:
        if rf not in combined_flags:
            combined_flags.append(rf)
    primary_res["flag_reasons"] = combined_flags
    primary_res["is_borderline"] = confidence_result["is_borderline"]
    primary_res["is_audit_flagged"] = confidence_result["is_audit_flagged"]
    primary_res["confidence_components"] = confidence_result["confidence_components"]

    if breakdown_unavailable:
        # A missing per-question breakdown means we don't have reliable criterion-level
        # marks even if the aggregate agreement score above looks fine -- override the
        # confidence engine's status here so this can never be silently auto-approved.
        primary_res["status"] = "flagged"
        reason = "⚠️ Grading Breakdown Unavailable — Manual Review Required"
        if reason not in primary_res["flag_reasons"]:
            primary_res["flag_reasons"].insert(0, reason)

    if failed_questions:
        # At least one rubric question couldn't be graded at all (unsplittable
        # submission, Interpreter failure, or grade_with_spec failure) -- the
        # questions that DID grade are still trustworthy, but this submission is
        # incomplete and must not be silently auto-approved on its partial total.
        primary_res["status"] = "flagged"
        reason = f"⚠️ Grading Unavailable for {', '.join(failed_questions)} — Manual Review Required"
        if reason not in primary_res["flag_reasons"]:
            primary_res["flag_reasons"].insert(0, reason)

    return primary_res




def _mock_heuristic_evaluation(student_text: str, rubric_json: list, reason: str = "LLM grading unavailable") -> Dict[str, Any]:
    """
    Fallback used when the LLM cannot be reached at all -- no API key configured, or
    the primary grading agent failed after every retry. This MUST NOT fabricate a
    grade. The previous version scored purely on response length (longer answers
    scored higher regardless of correctness) and even attached a fake
    "multi_agent_audit" entry with auditor_passed=True, so a total API outage would
    silently produce a plausible-looking, fully-audited grade with no actual grading
    having occurred. Instead, return a zero score with zero confidence and a
    "flagged" status so the submission is routed to mandatory human review rather
    than released with an invented mark.
    """
    return {
        "overall_score": 0.0,
        "confidence_score": 0.0,
        "status": "flagged",
        "reasoning": f"Automated grading could not be completed ({reason}). No score was generated; this submission requires manual grading.",
        "feedback": {
            "summary": "AI grading was unavailable for this submission. It has not been graded and requires manual review.",
            "breakdown": []
        },
        "highlights": [],
        "flag_reasons": ["⚠️ AI Grading Unavailable — Manual Review Required"]
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


