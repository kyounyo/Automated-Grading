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


# Q22 (Critical Appraisal / Professional Decision-Making) looks like an open-ended
# essay question on the surface, but its rubric actually encodes a POSITION-FIRST +
# BRANCHED-CRITERIA shape: the student's stance (stock vs. don't stock) determines
# which of two mutually exclusive criteria lists -- and which cap -- applies. Grading
# it with a flat "match against the rubric" prompt (no stance step) lets the model
# draw points from both lists or apply the wrong cap on hedging responses, which is
# exactly the kind of run-to-run inconsistency that tanks agreement with a human
# marker who reads the stance first and never considers the other branch. This
# criteria data captures the two branches; _build_position_branched_prompt below is
# the reusable template for any future question with this same shape.

_Q22_STOCK_CRITERIA = [
    "Ok to stock in community pharmacies (matches a stated position of stocking the product)",
    "Approved by the TGA (Therapeutic Goods Administration)",
    "Listed on the Australian Register of Therapeutic Goods (ARTG)",
    "There is some scientific evidence for its effectiveness",
    "There is a pharmacological rationale explained for its effectiveness (e.g. anti-inflammatory / PGD2 mechanism)",
    "Safety risk is minimal",
    "Reasoning for minimal safety risk: already used in oral form by many people, OR topical forms are unlikely to pose a safety risk",
    "Any other reasonable point regarding safety or efficacy that supports stocking the product",
]

_Q22_NOT_STOCK_CRITERIA = [
    "The evidence is only based on a limited number of patients",
    "No evidence is provided for safety",
    "Any other reasonable point regarding lack of safety or efficacy",
]

# Verbatim, unedited copies of the lecturer's own rubric wording, used ONLY by the
# rubric-semantic Q22 mode below. _Q22_STOCK_CRITERIA/_Q22_NOT_STOCK_CRITERIA above
# already carry small added glosses (e.g. "(matches a stated position...)", "(e.g.
# anti-inflammatory / PGD2 mechanism)") written for the older _build_position_branched_prompt
# -- useful annotations, but not what "grade directly from the lecturer's literal rubric,
# no engineered elaboration" is supposed to test. Keep these two lists byte-for-byte
# identical to the lecturer's rubric text; do not add clarifying parentheticals here.
_Q22_STOCK_CRITERIA_VERBATIM = [
    "This is a product that is ok to stock in community pharmacies",
    "It is approved by the TGA",
    "It is listed on the register of therapeutic goods",
    "There is some scientific evidence for its effectiveness",
    "There is a pharmacological rationale explained for its effectiveness",
    "Safety risk is minimal",
    "This is because it is already used in oral form by many people OR topical forms are unlikely to pose a safety risk",
    "Any other reasonable point regarding safety or efficacy",
]

_Q22_NOT_STOCK_CRITERIA_VERBATIM = [
    "The evidence is only based on a limited number of patients",
    "No evidence is provided for safety",
    "Any other reasonable point regarding lack of safety or efficacy",
]


# Q9 (Case-Based Dosing Calculation) is CALCULATION-VERIFY + MULTI-PART-INDEPENDENT:
# each family member is an independent sub-computation worth a "shows correct
# working" mark plus a "states correct whole-number answer" mark. The failure mode
# this guards against (per team findings) is duplicate/inferred marking -- awarding
# the answer mark from a rounding assumption the student never wrote, or awarding
# the same point twice because the model didn't route content to the right person.

_Q9_CALCULATION_ITEMS = [
    # acceptable_working_forms are EXAMPLES to anchor the extractor's judgement of
    # "was any explicit intermediate step shown" -- not a literal string match list.
    # v1 anchored the model too hard on the mg-dose form specifically; a real benchmark
    # run showed a student who wrote "64/10=6.4" (an unrounded-squares equation, valid
    # per the lecturer's own "equations and/or final dose in mg and/or exact number of
    # squares" wording) get marked as "no mg calculation shown" and lose the mark.
    {"label": "Melissa", "acceptable_working_forms": ["64 x 10 = 640", "640mg", "64/10 = 6.4", "6.4 squares"], "expected_final_squares": 6},
    {"label": "Tony", "acceptable_working_forms": ["73 x 10 = 730", "730mg", "73/10 = 7.3", "7.3 squares", "7.2 squares"], "expected_final_squares": 7},
    {"label": "Bella", "acceptable_working_forms": ["39 x 10 = 390", "390mg", "39/10 = 3.9", "3.9 squares"], "expected_final_squares": 4},
    {"label": "Bobby", "acceptable_working_forms": ["23 x 10 = 230", "230mg", "23/10 = 2.3", "2.3 squares"], "expected_final_squares": 2},
]
# Note: the lecturer's own answer key computes Tony's unrounded dose as 730mg / 100mg-
# per-square = 7.3 squares, but the key's worked example literally writes "7.2 squares"
# -- an inconsistency in the source rubric, not something we should silently resolve.
# Both 7.2 and 7.3 are accepted as valid working here rather than penalising a student
# for correctly computing 7.3; confirm with the lecturer which was actually intended.


# ---------------------------------------------------------------------------
# Q22 v8-CALIBRATED SINGLE GRADER: ONE LLM GRADER -> INTERNAL SELF-CHECK ->
#                                   DETERMINISTIC PYTHON SCORING
# ---------------------------------------------------------------------------
#
# Still exactly ONE LLM call, no auditor/second-grader/adjudicator -- see the
# v7 rationale this replaces: benchmarking a single grader model cleanly
# requires that its reported ICC not include a same-model "independent"
# audit pass (that was v6's mistake). v8 keeps that one-call contract and
# only changes grading POLICY:
#   - explicit CLEAR_STOCK / CLEAR_DO_NOT_STOCK / MIXED stance analysis
#     before choosing the branch, instead of a single blunt STOCK/DO_NOT_STOCK
#     question;
#   - concrete MET/NOT_MET boundary examples for S4, S6, S7, N1, N2 (the
#     criteria most prone to over-literal reading);
#   - S6 now explicitly allows the student's own safety CONCLUSION (e.g.
#     "approved safety and quality") to satisfy the criterion, while still
#     refusing to treat TGA/ARTG status alone as an automatic safety judgement.
#
# RESULT (real benchmark, N=15, same dev set used for v4-v7): v8 did not
# meaningfully move the needle -- ICC ~0.53 for Gemini Flash Lite and ~0.52
# for Nemotron, both close to v7's 0.529. Two structurally different models
# converging on the same ceiling across FIVE prompt architectures (v4 direct
# -> v5 extraction+audit -> v6 three-pass -> v7 single-call -> v8 calibrated
# single-call) is itself the signal: this is very unlikely to still be a
# prompt-wording problem. See _grade_q22_extraction_pipeline's docstring for
# what to do instead of a v9 prompt rewrite.
#
# IMPORTANT:
# The semantic boundaries below are rubric-derived calibration rules, not a
# keyword list. Do not keep loosening them just to chase ICC on these same 15
# development responses -- that is overfitting to the sample, not fixing the
# grader. Any further change to `not_sufficient` boundaries (esp. N1/N2)
# should come from lecturer criterion-level confirmation, not from re-reading
# the same disagreements again.

_Q22_STOCK_SPECS = [
    {
        "id": "S1",
        "concept": "Supports stocking the product in a community pharmacy",
        "marks": 1.0,
        "minimum_evidence": "The student's overall recommendation is to stock/sell/recommend the product.",
        "equivalence_rule": "Any clear affirmative stocking recommendation is sufficient.",
        "not_sufficient": "Discussing possible benefits without actually supporting stocking."
    },
    {
        "id": "S2",
        "concept": "Recognises that the product/use is approved by the TGA",
        "marks": 1.0,
        "minimum_evidence": "The student communicates TGA/Therapeutic Goods Administration approval.",
        "equivalence_rule": "Exact wording is unnecessary when Australian therapeutic-goods approval is clearly communicated.",
        "not_sufficient": "A generic claim that the product is legal, regulated, registered, or safe without communicating TGA approval."
    },
    {
        "id": "S3",
        "concept": "Recognises that the product is listed on the Australian Register of Therapeutic Goods (ARTG)",
        "marks": 1.0,
        "minimum_evidence": "The student communicates ARTG/Australian Register of Therapeutic Goods listing or registration.",
        "equivalence_rule": "ARTG and the full register name are equivalent.",
        "not_sufficient": "TGA approval alone unless listing/register status is also communicated."
    },
    {
        "id": "S4",
        "concept": "Recognises scientific evidence supporting effectiveness",
        "marks": 1.0,
        "minimum_evidence": "The student communicates that research, study findings, observed outcomes, clinical evidence, or data provide some support for effectiveness.",
        "equivalence_rule": "The student need not use the words 'scientific evidence' or 'efficacy'. Accept statements such as 'research evidence supports it', 'scientifically proven', 'studies/trials showed benefit', 'clinical evidence supports effectiveness', or another clear evidence-based statement supporting benefit.",
        "not_sufficient": "A bare assertion such as 'it works', 'it should work', or 'I think it is effective' with no communicated research, study, trial, evidence, data, or observed outcome."
    },
    {
        "id": "S5",
        "concept": "Explains a pharmacological rationale for effectiveness",
        "marks": 1.0,
        "minimum_evidence": "The student communicates a pharmacological/mechanistic reason that could explain the hair-growth benefit.",
        "equivalence_rule": "A scientifically valid anti-inflammatory, histamine-related, PGD2-related, or other pharmacological mechanism is acceptable when linked to possible efficacy.",
        "not_sufficient": "Merely naming cetirizine as an antihistamine without communicating why the pharmacology could support effectiveness."
    },
    {
        "id": "S6",
        "concept": "Communicates that safety risk is minimal/low",
        "marks": 1.0,
        "minimum_evidence": "The student communicates a safety conclusion such as safe, relatively safe, low/minimal risk, acceptable safety, favourable tolerability, lower side-effect burden, approved safety, or a clear semantic equivalent.",
        "equivalence_rule": "Do not require the exact phrase 'minimal safety risk'. Statements such as 'safe', 'approved safety and quality', 'acceptable safety profile', 'low risk', or 'fewer/lower side effects' can satisfy this criterion when the student's own wording clearly communicates safety.",
        "not_sufficient": "TGA approval, ARTG listing, registration, legality, or regulation ALONE does not automatically earn S6. However, if the student's own wording explicitly communicates a safety conclusion from that status, such as 'approved safety and quality', S6 may be MET."
    },
    {
        "id": "S7",
        "concept": "Gives the rubric-defined reason for minimal safety risk: established oral use OR topical use unlikely to pose a safety risk",
        "marks": 1.0,
        "minimum_evidence": "The student links safety to established/common oral cetirizine use OR to topical/local administration being unlikely to create substantial safety risk.",
        "equivalence_rule": "Equivalent reasoning about established exposure, tolerability, local administration, low systemic exposure, or low topical risk is acceptable when the safety connection is communicated.",
        "not_sufficient": "A generic statement that the product is safe without the oral-use/topical-risk rationale."
    },
    {
        "id": "S8",
        "concept": "Gives one other distinct reasonable point regarding safety or efficacy supporting stocking",
        "marks": 1.0,
        "minimum_evidence": "One distinct scientifically, clinically, pharmacologically, or pharmaceutically reasonable safety/efficacy point supporting stocking that is not already credited under S2-S7.",
        "equivalence_rule": "This is deliberately open-ended because the lecturer rubric says 'any other reasonable point'. Do not require resemblance to a fixed answer list.",
        "not_sufficient": "A duplicate of an already credited criterion, a purely commercial point, or a vague statement with no distinct safety/efficacy meaning."
    },
]

_Q22_NOT_STOCK_SPECS = [
    {
        "id": "N1",
        "concept": "Recognises that efficacy evidence is based on a limited number of patients",
        "marks": 1.0,
        "minimum_evidence": "The student communicates that the CURRENT efficacy evidence base is limited, for example because patient/sample numbers are small, there are too few participants/studies, or the available evidence is explicitly described as limited/insufficient.",
        "equivalence_rule": "Small sample, few participants, limited patient numbers, too few studies, or an explicitly limited/insufficient current evidence base are acceptable semantic equivalents.",
        "not_sufficient": "A generic 'more research is needed', 'I want to read more papers', or 'more evidence would be useful' statement does NOT earn N1 unless the student clearly communicates that the CURRENT evidence base is limited. Broaden this only after lecturer criterion-level validation."
    },
    {
        "id": "N2",
        "concept": "Recognises that no evidence is provided for safety",
        "marks": 1.0,
        "minimum_evidence": "The student communicates that safety evidence/data is absent, lacking, unknown, not demonstrated, or insufficiently provided.",
        "equivalence_rule": "Accept 'no safety data', 'lack of safety evidence', 'safety has not been established', 'the information does not demonstrate safety', or a clear semantic equivalent.",
        "not_sufficient": "Merely saying the product may be unsafe, asking for more information, or expressing uncertainty does not earn N2 unless a safety-evidence gap is actually communicated."
    },
    {
        "id": "N3",
        "concept": "Gives one other distinct reasonable point regarding lack of safety or efficacy",
        "marks": 1.0,
        "minimum_evidence": "One distinct scientifically/pharmaceutically reasonable safety or efficacy concern supporting not stocking, not already credited as N1/N2.",
        "equivalence_rule": "This is deliberately open-ended because the lecturer rubric says 'any other reasonable point'.",
        "not_sufficient": "A duplicate of N1/N2, a non-safety/non-efficacy concern, or a vague unsupported objection."
    },
]


def _build_q22_single_grader_prompt(
    student_text: str,
    question_text: Optional[str] = None,
) -> str:
    """
    Q22 v8 calibrated ONE-call grader.

    Still exactly ONE grader LLM call. The model:
      1) classifies stance as CLEAR_STOCK / CLEAR_DO_NOT_STOCK / MIXED,
      2) resolves the final scoring branch,
      3) evaluates every applicable criterion using semantic boundary examples,
      4) performs an internal false-negative recheck.

    Python, not the LLM, calculates the score.
    """
    scenario = f"QUESTION / SCENARIO:\n{question_text}\n\n" if question_text else ""

    return f"""
You are the SINGLE GRADER for an undergraduate pharmacy open-ended assessment.

This is a ONE-MODEL benchmark.
There is NO auditor, second grader, adjudicator, or second grading call.
Do NOT calculate or report a numerical total. Python will calculate the score.

{scenario}STUDENT RESPONSE:
{student_text}

============================================================
STEP 1 — ANALYSE POSITION BEFORE GRADING
============================================================

First classify the response as ONE of:

CLEAR_STOCK
CLEAR_DO_NOT_STOCK
MIXED

CLEAR_STOCK:
The student's own recommendation is clearly to stock/sell/recommend the product.

CLEAR_DO_NOT_STOCK:
The student's own recommendation is clearly not to stock/sell/recommend it.

MIXED:
The response contains meaningful arguments or apparent recommendations on BOTH
sides, or wording that could cause the branch to be misread.

If MIXED, identify internally:
1. the student's initial recommendation;
2. arguments supporting STOCK;
3. arguments supporting DO_NOT_STOCK;
4. any explicit final conclusion;
5. which position is actually the student's final/overall recommendation.

IMPORTANT POSITION RULES:
- A counterargument is NOT automatically the student's final position.
- Do NOT choose DO_NOT_STOCK merely because the student later writes
  "No because..." while critically discussing the other side.
- If an explicit final recommendation exists, give it greatest weight.
- Otherwise choose the recommendation most clearly presented as the student's
  own decision rather than an argument they are merely considering.

After that analysis, choose exactly one FINAL SCORING BRANCH:
STOCK or DO_NOT_STOCK.

============================================================
STEP 2 — APPLY ONLY THE SELECTED RUBRIC BRANCH
============================================================

If final_position = STOCK, evaluate ALL of these:
{json.dumps(_Q22_STOCK_SPECS, indent=2)}

If final_position = DO_NOT_STOCK, evaluate ALL of these:
{json.dumps(_Q22_NOT_STOCK_SPECS, indent=2)}

============================================================
STEP 3 — CALIBRATED HUMAN-MARKER SEMANTIC MATCHING
============================================================

For every applicable criterion:
1. Identify the MINIMUM underlying concept required.
2. Search the ENTIRE response for evidence.
3. Judge MEANING, not keyword overlap.
4. Decide MET or NOT_MET.
5. For MET, quote the strongest student-authored evidence verbatim.
6. For NOT_MET, briefly identify the missing concept.

Use these boundary examples to calibrate your judgement. They are examples,
NOT exact phrases that must appear.

S4 SCIENTIFIC EVIDENCE
MET examples:
- "research evidence supports it"
- "scientifically proven"
- "studies/trials showed positive results"
- "clinical evidence suggests it is effective"
NOT_MET examples:
- "I think it works"
- "it should be effective"
- a bare efficacy claim with no evidence/research/study meaning

S6 SAFETY CONCLUSION
MET examples:
- "the product is safe"
- "approved safety and quality"
- "the safety risk is low"
- "acceptable safety profile"
- "fewer/lower side effects"
NOT_MET examples:
- "TGA approved" by itself
- "listed on ARTG" by itself
- "regulated" by itself
IMPORTANT: regulatory status alone is not S6, but the student's OWN wording
may communicate a separate safety conclusion from it.

S7 SAFETY RATIONALE
MET examples:
- established/common oral cetirizine use is linked to safety
- topical/local use is linked to low risk
- low systemic exposure from topical use is linked to safety
NOT_MET:
- merely saying "safe" without the oral/topical rationale

N1 LIMITED EVIDENCE BASE
MET examples:
- "small sample"
- "few patients/participants"
- "too few studies"
- "the current evidence is limited/insufficient"
NOT_MET:
- "more research would be useful" with no statement that CURRENT evidence is limited
- "I want to read more papers"

N2 SAFETY-EVIDENCE GAP
MET examples:
- "no safety evidence is provided"
- "safety data is lacking"
- "the evidence does not establish safety"
NOT_MET:
- "it may be unsafe" without identifying an evidence gap
- "I need more information" without identifying an evidence gap

S8 / N3 OPEN ALTERNATIVE
Actively look for ONE distinct scientifically, clinically, pharmacologically,
or pharmaceutically reasonable safety/efficacy point that supports the selected
position and has NOT already been credited.
Do not require resemblance to a model answer.
Do not use it as a generic bonus mark.

GENERAL SEMANTIC RULES:
- Accept synonyms, paraphrases, concise answers, examples, and scientifically
  valid alternative terminology.
- Do NOT require exact rubric wording.
- Do NOT require more precision or explanation than the criterion itself requires.
- An implicit conclusion can count only when it is clearly communicated.
- Do NOT invent knowledge the student did not communicate.
- Do NOT copy facts from the scenario into the student's answer.
- A related keyword alone is insufficient.
- One sentence can support two DIFFERENT criteria only if it genuinely
  communicates two distinct rubric concepts.

============================================================
STEP 4 — NO NEGATIVE MARKING / NO DOUBLE COUNTING
============================================================

Incorrect or irrelevant information elsewhere does not remove a valid mark unless
it directly contradicts the evidence used for that SAME criterion.

Award each distinct criterion at most once.
Do not award the same underlying point twice.

============================================================
STEP 5 — MANDATORY FALSE-NEGATIVE RECHECK
============================================================

Before finalising, revisit EVERY criterion initially marked NOT_MET.

For each, re-read the ENTIRE response and ask:

"Would a reasonable undergraduate pharmacy educator recognise any wording here
as demonstrating the criterion's underlying concept, even though the student
expressed it differently from the rubric?"

Specifically recheck for:
- synonyms;
- paraphrases;
- examples;
- implicit but unambiguous conclusions;
- alternative scientific/pharmacy terminology;
- valid alternative safety/efficacy reasoning.

If YES, change it to MET and quote the evidence.
If it requires inventing an unstated idea, keep NOT_MET.

============================================================
STEP 6 — FINAL CONSISTENCY CHECK
============================================================

Verify:
- position was determined from the FULL response;
- mixed/counterargument wording was handled correctly;
- only the final selected branch was graded;
- every applicable criterion appears exactly once;
- every MET criterion has student-authored evidence;
- semantic equivalents were accepted;
- no criterion was double-counted;
- no fractional marks were invented;
- YOU did not calculate the total score.

OUTPUT ONLY VALID JSON:

{{
  "stance_classification": "CLEAR_STOCK",
  "initial_recommendation": "brief description or null",
  "stock_arguments": ["brief descriptions"],
  "do_not_stock_arguments": ["brief descriptions"],
  "final_recommendation_evidence": "verbatim quote or null",
  "final_position": "STOCK",
  "position_reason": "brief explanation",
  "decisions": [
    {{
      "id": "S1",
      "met": true,
      "evidence": "verbatim student quote or null",
      "reason": "brief criterion-specific explanation"
    }}
  ],
  "false_negative_recheck_completed": true
}}
"""


def _normalise_q22_position(result: Dict[str, Any]) -> str:
    """Parse position without silently converting malformed output to the generous branch."""
    raw = str(result.get("final_position", result.get("position", ""))).strip().upper().replace(" ", "_").replace("'", "")
    if raw in {"DO_NOT_STOCK", "DONT_STOCK", "NOT_STOCK"}:
        return "DO_NOT_STOCK"
    if raw == "STOCK":
        return "STOCK"

    evidence = str(result.get("final_recommendation_evidence") or result.get("position_evidence") or "").lower()
    if any(x in evidence for x in [
        "would not stock", "wouldn't stock", "do not stock",
        "don't stock", "not stock"
    ]):
        return "DO_NOT_STOCK"
    if "stock" in evidence:
        return "STOCK"

    # Do not silently choose the higher-cap branch if malformed.
    return "DO_NOT_STOCK"


def _score_q22_single_grader(result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deterministic Q22 scoring.

    The LLM owns semantic criterion classification. Python owns: branch
    selection normalisation, criterion validation, mark conversion, total,
    and branch cap. No second LLM call occurs here.
    """
    position = _normalise_q22_position(result)
    specs = _Q22_STOCK_SPECS if position == "STOCK" else _Q22_NOT_STOCK_SPECS
    cap = 6.0 if position == "STOCK" else 3.0

    decision_map = {
        str(d.get("id")): d
        for d in (result.get("decisions") or [])
        if isinstance(d, dict) and d.get("id")
    }

    breakdown = []
    highlights = []
    raw_score = 0.0

    for spec in specs:
        cid = spec["id"]
        decision = decision_map.get(cid, {})

        met = bool(decision.get("met", False))
        evidence = decision.get("evidence")
        reason = decision.get("reason", "Criterion not demonstrated.")

        # S1 follows directly from a clear STOCK recommendation. Keeping this
        # deterministic avoids the contradictory state: position=STOCK but S1=False.
        if cid == "S1" and position == "STOCK":
            met = True
            if not evidence:
                evidence = result.get("final_recommendation_evidence") or result.get("position_evidence")
            if not decision.get("reason"):
                reason = (
                    "Deterministic rubric rule: the student's STOCK recommendation "
                    "satisfies the stock-position criterion."
                )

        mark = float(spec.get("marks", 1.0)) if met else 0.0
        raw_score += mark

        breakdown.append({
            "criterion_id": cid,
            "criterion": spec["concept"],
            "met": met,
            "evidence": evidence,
            "reason": reason,
            "mark_awarded": mark,
        })

        if evidence:
            highlights.append({
                "text": evidence,
                "question_number": "Q22",
                "score_awarded": mark,
                "max_score": 1.0,
                "type": "strength" if met else "improvement",
                "comment": f"{cid}: {reason}",
            })

    final_score = min(raw_score, cap)
    met_ids = [x["criterion_id"] for x in breakdown if x["met"]]
    missed_ids = [x["criterion_id"] for x in breakdown if not x["met"]]

    reasoning_summary = "; ".join(
        f"{x['criterion_id']}={'MET' if x['met'] else 'NOT MET'}: {x['reason']}"
        for x in breakdown
    )

    return {
        "overall_score": round(final_score, 1),
        "confidence_score": 0.90,
        "status": "graded",
        "identified_position": "STOCK" if position == "STOCK" else "DO NOT STOCK",
        "position_evidence": result.get("final_recommendation_evidence") or result.get("position_evidence"),
        "stance_classification": result.get("stance_classification"),
        "reasoning": (
            f"Q22 v8 calibrated single-grader deterministic scoring. "
            f"met={met_ids}; missed={missed_ids}; "
            f"raw={raw_score:.1f}; cap={cap:.1f}. "
            f"{reasoning_summary}"
        ),
        "feedback": {
            "summary": (
                f"Q22 single-grader evaluation: {len(met_ids)} applicable "
                f"rubric criteria demonstrated; branch cap {cap:.0f}."
            ),
            "breakdown": [{
                "question_number": "Q22",
                "score_awarded": round(final_score, 1),
                "max_score": cap,
                "reasoning": reasoning_summary,
            }],
        },
        "criterion_breakdown": breakdown,
        "highlights": highlights,

        # Preserve the raw single-grader output for later criterion-level analysis
        # and for a future auditor-model pass to review.
        "_q22_single_grader": result,
    }


def _grade_q22_extraction_pipeline(
    student_text: str,
    question_text: Optional[str],
    model: str,
) -> Optional[Dict[str, Any]]:
    """
    Q22 v8-CALIBRATED SINGLE-GRADER benchmark pipeline.

    EXACTLY ONE LLM grading call: full response -> position -> all applicable
    criterion decisions -> internal false-negative self-check -> structured JSON.
    Then deterministic Python scoring.

    There is intentionally NO auditor, second grader, adjudicator, or second
    semantic LLM call in this benchmark. A separate auditor model can be added
    later (see call_auditor_verification_agent) without changing this grader's
    contract.

    STOP-AND-RECONSIDER NOTE (read before writing a v9 prompt):
    v4 through v8 -- five architecturally different prompts, including two
    different underlying models (Gemini Flash Lite and Nemotron) on v7/v8 --
    have all landed in the same ~0.32-0.53 ICC band on this 15-response dev
    set, without ever approaching the 0.79 lecturer-prompt benchmark. Two
    different models converging on nearly the same ceiling (v8: ICC ~0.53
    Gemini, ~0.52 Nemotron) is itself evidence that the bottleneck is not
    "this particular model reads the prompt too strictly" -- if it were, a
    different model with different training should have moved the number
    much more than 0.01. The two most likely explanations left are (1) the
    8/3-criterion decomposition doesn't actually span how the human scored
    (a human total of 6/6 may reflect a holistic judgement call, not a
    checklist of exactly 6 named facts), or (2) N=15 is too small for these
    ICC deltas to mean much run-to-run. Before writing a v9 prompt: get the
    lecturer (or a second team member) to criterion-code these same 15
    responses (which of S1-S8/N1-N3 they believe were actually demonstrated)
    so criterion-level precision/recall against a real ground truth can be
    measured directly, instead of continuing to infer rubric intent from the
    aggregate ICC alone.
    """
    prompt = _build_q22_single_grader_prompt(
        student_text=student_text,
        question_text=question_text,
    )

    messages = [
        {
            "role": "system",
            "content": (
                "You are the single undergraduate pharmacy Grader agent. "
                "Apply the supplied rubric as a reasonable human pharmacy educator would. "
                "Judge semantic meaning rather than keyword overlap, use the supplied "
                "boundary examples to calibrate MET versus NOT_MET, analyse mixed positions "
                "carefully, and perform the false-negative recheck before returning final "
                "criterion decisions. Do not calculate a total score. Always return valid JSON."
            ),
        },
        {"role": "user", "content": prompt},
    ]

    # ONE and only one Q22 grader-model call.
    result = _call_openrouter_api(
        messages,
        model,
        temperature=0.0,
    )

    if not result:
        return None

    return _score_q22_single_grader(result)


# ---------------------------------------------------------------------------
# Q22 RUBRIC-SEMANTIC: raw lecturer rubric wording, no engineered S1-S8/N1-N3
# specs -- controlled A/B counterpart to v8
# ---------------------------------------------------------------------------
#
# Why this exists: real batch-session data (both Gemini and Nemotron) shows
# the ~0.5 ICC ceiling is NOT mainly a semantic-recognition problem. Inspecting
# the actual largest disagreements: response 32842716 (human=6) argues purely
# from an "evidence-based practice" framing -- clinical expertise, patient
# preference, and the two cited studies -- and never mentions TGA, ARTG,
# safety, or mechanism at all. v8 correctly scored what's actually there (S1,
# S4 = 2/6) because those other criteria genuinely aren't addressed. Response
# 33646376 (human=4) is even thinner -- a near-content-free "EBP" recitation
# with no scenario-specific detail -- yet the human awarded 4/6. Response
# 33640297 (human=6) argues "Yes because... No because..." without
# committing to one side; v8's DO_NOT_STOCK branch call was internally
# consistent and scored a flawless 3/3 (all of N1/N2/N3), the DO_NOT_STOCK
# branch's maximum -- but the human's 6 is only reachable under the STOCK
# cap. None of these are S1-S8 wording problems: no amount of rephrasing
# `not_sufficient` boundary examples recovers marks for content the student
# never wrote, or lets Python exceed a 3.0 cap the lecturer's own rubric
# imposes on that branch.
#
# So this is a genuinely different hypothesis, not another wording pass: does
# grading directly from the lecturer's own numbered rubric bullets (no
# manufactured `minimum_evidence`/`equivalence_rule`/`not_sufficient`
# elaboration layer) change the outcome? Held constant vs v8: same 15
# responses, same models, temperature 0, same Python-owned scoring/cap, same
# batch-session vs per-response harness paths. Changed: the ONLY criteria
# text the model sees is _Q22_STOCK_CRITERIA/_Q22_NOT_STOCK_CRITERIA (the
# lecturer's literal bullets already defined above), inside a protocol
# closely mirroring the lecturer's own reference prompt's structure
# (determine position -> grade only that branch -> semantic equivalence ->
# valid alternative reasoning for the open "any other reasonable point"
# item -> evidence -> no double counting -> no negative marking -> recheck).
#
# EXPECTATION TO TEST, NOT ASSUME: given the three cases above, this change
# is unlikely by itself to close the gap -- 32842716 and 33646376 don't fail
# because the criteria wording was too strict, they fail because the content
# needed to earn those marks simply isn't in the response, under ANY
# reasonable reading of "It is approved by the TGA" or "There is a
# pharmacological rationale explained." If rubric-semantic scores these two
# the same way v8 did, that's itself a useful (negative) result: it would
# mean the lecturer is not grading strictly against this written rubric for
# at least some scripts, which no prompt rewrite can fix -- see the
# STOP-AND-RECONSIDER note on _grade_q22_extraction_pipeline for what to do
# instead (get lecturer confirmation on these specific disagreements).

def _build_q22_rubric_semantic_prompt(student_text: str, question_text: Optional[str] = None) -> str:
    """Single-call rubric-semantic grader. Embeds one student response inline."""
    scenario = f"QUESTION / SCENARIO:\n{question_text}\n\n" if question_text else ""
    return (
        _q22_rubric_semantic_protocol_header()
        + f"{scenario}STUDENT RESPONSE:\n{student_text}\n\n"
        + _q22_rubric_semantic_protocol_body()
    )


def _build_q22_rubric_semantic_batch_instructions(question_text: Optional[str]) -> str:
    """Session-level rubric-semantic instructions with no embedded student text."""
    scenario = f"QUESTION / SCENARIO:\n{question_text}\n\n" if question_text else ""
    return (
        _q22_rubric_semantic_protocol_header()
        + "BATCH GRADING NOTICE:\n"
          "You will grade MULTIPLE student responses to this SAME question, one at "
          "a time, within this one continuous conversation. Use everything you have "
          "already seen in this session -- every prior response and every decision "
          "you have already made -- to keep ONE consistent internal standard across "
          "the whole batch, the way a human marker calibrates while marking a stack "
          "of scripts. Do not go back and revise a decision you already returned for "
          "an earlier response.\n\n"
        + scenario
        + _q22_rubric_semantic_protocol_body()
        + "\nI will send you one student response at a time. Periodically I will "
          "resend these full instructions as a reminder -- continue applying them "
          "exactly. Confirm you understand by waiting for the first student "
          "response; do not output anything until then.\n"
    )


def _q22_rubric_semantic_protocol_header() -> str:
    return """
You are grading an open-ended response from an undergraduate pharmacy student.

This is a ONE-MODEL benchmark. There is NO auditor, second grader, or
adjudicator. Do NOT calculate or report a numerical total -- Python will
calculate the score from your criterion decisions.

Use the QUESTION and the MARKING RUBRIC below as the AUTHORITATIVE grading
standard. Do not invent additional scoring restrictions, exclusions, or
requirements beyond what the rubric states or clearly implies.

"""


def _q22_rubric_semantic_protocol_body() -> str:
    stock_lines = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(_Q22_STOCK_CRITERIA_VERBATIM))
    not_stock_lines = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(_Q22_NOT_STOCK_CRITERIA_VERBATIM))
    return f"""MARKING RUBRIC

If the student's overall decision is to STOCK the product, award 1 mark for
each of the following, to a maximum of 6 marks:
{stock_lines}

If the student's overall decision is NOT to stock the product, award 1 mark
for each of the following, to a maximum of 3 marks:
{not_stock_lines}

OPEN-ENDED PROFESSIONAL JUDGMENT GRADING PROTOCOL

1. IDENTIFY THE STUDENT'S DECISION
Determine the student's overall answer, recommendation, position, or
professional decision from the response as a whole. When the response
discusses arguments on both sides, distinguish between the student's own
final position and counterarguments or limitations they merely discuss. Do
not change the student's position merely because they acknowledge an
opposing argument.

POSITION RESOLUTION: if the response opens with an explicit recommendation
and later discusses limitations, risks, or counterarguments WITHOUT stating a
new final recommendation, retain the original explicit recommendation --
critically discussing weaknesses in the evidence is not the same as reversing
the decision. Only treat the position as the opposite branch when the student
clearly states that different final recommendation themselves. If the
response is genuinely ambiguous even after this check (no explicit final
recommendation either way), choose the position most strongly supported by
the balance of the student's own reasoning and note the ambiguity in
`position_reason`.

2. APPLY THE APPLICABLE RUBRIC
Identify the numbered criteria above that apply to the student's chosen
position. Follow the mark values and maximum score stated exactly. Grade
ONLY the applicable branch's numbered list -- never combine marks from both.

3. GRADE BY MEANING
For each applicable numbered criterion, determine whether the student has
demonstrated the underlying concept. Accept synonyms, paraphrases, different
terminology, concise explanations, examples that clearly demonstrate the
concept, and implicit but unambiguous meaning. Do not require the student's
wording to match the rubric.

Before withholding a mark, ask: "Would a reasonable pharmacy educator
recognise that the student's own words demonstrate the underlying concept
required by this specific criterion, even though it is expressed differently
from the rubric?" If yes, award it.

Do not award a mark for an idea that requires you to invent knowledge the
student did not actually communicate. A response that never mentions a fact
required by a criterion (e.g. regulatory approval, a safety conclusion, a
mechanism) does not earn that criterion merely because the fact is true or
was given in the scenario -- the STUDENT must communicate it.

CALIBRATION AGAINST FALSE NEGATIVES: for this open-ended professional-
judgement question, avoid an overly literal interpretation of the rubric. The
rubric describes the concepts that should receive credit; it is not a
required vocabulary list. Award a criterion even when the student uses
broader or less technical terminology, states the conclusion concisely,
communicates it through an explanation rather than the rubric's exact
wording, or demonstrates the underlying concern without naming the rubric
category itself. Do not require the student to reproduce a specific fact,
phrase, or level of technical precision unless that precision is essential to
what the criterion is actually assessing. This is semantic credit, not
generosity -- it does not permit inventing an idea absent from the response,
using scenario information as though the student stated it, awarding a
merely related idea, or awarding the same underlying idea twice.

DECISION PROCESS for every applicable criterion:
  A. What underlying knowledge, reasoning, safety/efficacy judgement, or
     professional concern is this criterion assessing?
  B. Search the ENTIRE response for the student's strongest evidence for that
     underlying concept.
  C. Ask whether a reasonable pharmacy educator would recognise the
     student's own words as demonstrating substantially the same concept.
     If YES -> MET.
  D. If the match is not literal, ask whether the difference is merely one
     of wording, terminology, level of detail, or presentation. If YES -> MET.
  E. If it is genuinely a different idea, ask whether it qualifies as a
     distinct scientifically or professionally reasonable point under the
     rubric's "any other reasonable point" criterion (see rule 4 below).
     If YES -> award that open-ended criterion.
  F. Otherwise -> NOT MET.

When uncertain between MET and NOT MET, do not default to NOT MET merely
because the student's wording is less precise or less technical than the
rubric. Withhold the mark only when the required underlying concept is
genuinely absent, contradicted, or merely topic-related rather than actually
demonstrated. A reasonable-sounding argument is not by itself a reason to
award a mark -- the underlying idea must still be explicitly stated or
unambiguously communicated by the student; do not supply missing reasoning on
the student's behalf.

CONCEPTUAL EQUIVALENCE EXAMPLES (defining the boundary of a rubric concept,
not an exhaustive answer key):

Rubric concept: "The evidence is only based on a limited number of patients."
A student does not need the exact phrase "limited number of patients" if
their response clearly communicates that the CURRENT evidence base is too
limited, too small, too preliminary, or insufficient to justify confidence in
efficacy. A generic statement such as "more research is always good" does
NOT earn this criterion unless it communicates a limitation of the evidence
actually presented in this case.

Rubric concept: "No evidence is provided for safety."
Accept semantically equivalent reasoning when the student clearly
communicates that safety has not been established, that the available
information is insufficient to judge safety, that relevant safety/side-effect
information is missing or unclear, or that further safety evidence is
required before the product can be considered adequately supported. Do not
require the literal phrase "no safety evidence." Do not award this criterion
for a generic statement that all medicines may carry some risk unless the
response communicates an actual deficiency in the available safety evidence.

4. VALID ALTERNATIVE REASONING
The rubric's "any other reasonable point" criterion is genuinely open-ended.
Award it for one distinct, scientifically, clinically, pharmacologically, or
pharmaceutically reasonable point that satisfies the rubric's stated purpose
and is not already credited under another numbered criterion. It does not
need to resemble a model answer.

5. EVIDENCE
Every awarded mark must be supported by evidence from the student's own
response. Quote the strongest relevant evidence verbatim. One passage may
demonstrate more than one DISTINCT numbered criterion when it genuinely
communicates multiple ideas.

6. NO DOUBLE COUNTING
Award each underlying scoring point only once. Do not award the same idea
twice using different wording.

7. NO NEGATIVE MARKING
Incorrect or irrelevant information does not remove marks already earned
unless the rubric explicitly specifies a penalty.

8. MANDATORY FALSE-NEGATIVE RECHECK
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
Also confirm: no point was counted twice, and the correct branch's maximum
applies.

OUTPUT ONLY VALID JSON:
{{
  "final_position": "STOCK",
  "final_recommendation_evidence": "verbatim quote establishing the recommendation, or null",
  "position_reason": "brief explanation of the position determination, especially if ambiguous",
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


def _score_q22_rubric_semantic(result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deterministic Q22 scoring for the rubric-semantic mode. Mirrors
    _score_q22_single_grader's contract exactly (Python owns branch
    normalisation, mark conversion, total, and cap) but keys criteria by
    their 1-based position in _Q22_STOCK_CRITERIA_VERBATIM/
    _Q22_NOT_STOCK_CRITERIA_VERBATIM instead of the engineered S1-S8/N1-N3
    ids, since these are the lecturer's literal numbered bullets with no
    synthetic id scheme.

    Criterion #1 of the STOCK list ("ok to stock in community pharmacies")
    is deterministic, exactly mirroring the lecturer's own reference prompt:
    "Award 1 mark if the student agrees to stock the product -- agreeing to
    stock the product matches [criterion 1]." The DO_NOT_STOCK list has no
    equivalent auto-award item (the lecturer's rubric doesn't give one).
    """
    position = _normalise_q22_position(result)
    specs = _Q22_STOCK_CRITERIA_VERBATIM if position == "STOCK" else _Q22_NOT_STOCK_CRITERIA_VERBATIM
    cap = 6.0 if position == "STOCK" else 3.0

    decision_map = {}
    for d in (result.get("decisions") or []):
        if isinstance(d, dict) and d.get("criterion_number") is not None:
            try:
                decision_map[int(d["criterion_number"])] = d
            except (TypeError, ValueError):
                continue

    breakdown = []
    highlights = []
    raw_score = 0.0

    for idx, concept in enumerate(specs, start=1):
        decision = decision_map.get(idx, {})
        met = bool(decision.get("met", False))
        evidence = decision.get("evidence")
        reason = decision.get("reason", "Criterion not demonstrated.")

        if idx == 1 and position == "STOCK":
            met = True
            if not evidence:
                evidence = result.get("final_recommendation_evidence") or result.get("position_evidence")
            if not decision.get("reason"):
                reason = (
                    "Deterministic rubric rule: the student's STOCK recommendation "
                    "satisfies criterion 1 (ok to stock in community pharmacies)."
                )

        mark = 1.0 if met else 0.0
        raw_score += mark

        breakdown.append({
            "criterion_id": f"#{idx}",
            "criterion": concept,
            "met": met,
            "evidence": evidence,
            "reason": reason,
            "mark_awarded": mark,
        })

        if evidence:
            highlights.append({
                "text": evidence,
                "question_number": "Q22",
                "score_awarded": mark,
                "max_score": 1.0,
                "type": "strength" if met else "improvement",
                "comment": f"#{idx}: {reason}",
            })

    final_score = min(raw_score, cap)
    met_ids = [x["criterion_id"] for x in breakdown if x["met"]]
    missed_ids = [x["criterion_id"] for x in breakdown if not x["met"]]

    reasoning_summary = "; ".join(
        f"{x['criterion_id']}={'MET' if x['met'] else 'NOT MET'}: {x['reason']}"
        for x in breakdown
    )

    return {
        "overall_score": round(final_score, 1),
        "confidence_score": 0.90,
        "status": "graded",
        "identified_position": "STOCK" if position == "STOCK" else "DO NOT STOCK",
        "position_evidence": result.get("final_recommendation_evidence") or result.get("position_evidence"),
        "reasoning": (
            f"Q22 rubric-semantic deterministic scoring. "
            f"met={met_ids}; missed={missed_ids}; "
            f"raw={raw_score:.1f}; cap={cap:.1f}. "
            f"{reasoning_summary}"
        ),
        "feedback": {
            "summary": (
                f"Q22 rubric-semantic evaluation: {len(met_ids)} applicable "
                f"rubric criteria demonstrated; branch cap {cap:.0f}."
            ),
            "breakdown": [{
                "question_number": "Q22",
                "score_awarded": round(final_score, 1),
                "max_score": cap,
                "reasoning": reasoning_summary,
            }],
        },
        "criterion_breakdown": breakdown,
        "highlights": highlights,
        "_q22_rubric_semantic": result,
    }


def _grade_q22_rubric_semantic_pipeline(
    student_text: str,
    question_text: Optional[str],
    model: str,
) -> Optional[Dict[str, Any]]:
    """
    Q22 RUBRIC-SEMANTIC single-call pipeline -- the controlled A/B counterpart
    to v8 (_grade_q22_extraction_pipeline). Same one-call, no-auditor
    structure and the same deterministic Python scoring; the only variable
    changed is that the model reasons directly from the lecturer's literal
    rubric bullets instead of the manually engineered S1-S8/N1-N3 specs.
    """
    prompt = _build_q22_rubric_semantic_prompt(student_text, question_text)
    messages = [
        {
            "role": "system",
            "content": (
                "You are the single undergraduate pharmacy Grader agent. Ground every "
                "decision in the supplied rubric wording itself, judging semantic meaning "
                "rather than keyword overlap. Do not invent scoring rules the rubric doesn't "
                "state or imply. Do not calculate a total score. Always return valid JSON."
            ),
        },
        {"role": "user", "content": prompt},
    ]
    result = _call_openrouter_api(messages, model, temperature=0.0)
    if not result:
        return None
    return _score_q22_rubric_semantic(result)


# ---------------------------------------------------------------------------
# Q22 BATCH-SESSION EXPERIMENT: same v8 criteria + Python scoring, graded
# within ONE continuous conversation across the whole response set
# ---------------------------------------------------------------------------
#
# Why this exists: v4 through v8 all grade each response in a fresh, stateless
# API call with zero visibility into any other response, and all five landed
# in the same ~0.32-0.53 ICC band regardless of criterion wording or which
# model was used. Two externally-cited reference prompts that reportedly hit
# ~0.7 ICC on this same question share a structural trait ours doesn't have:
# they grade every response for a batch inside ONE continuous conversation
# (see prompt 1's step 1 -> step 2..N -> periodic instruction refresh), so the
# model has already seen prior responses (and its own prior gradings) before
# judging the next one. ICC specifically rewards agreement with the human's
# relative calibration across the sample -- a marker (human or AI) with no
# visibility into the cohort's actual spread of answers has no way to
# replicate that, no matter how well-worded the per-criterion instructions are.
#
# This experiment isolates exactly that ONE variable. It deliberately reuses
# v8's exact criteria specs (_Q22_STOCK_SPECS/_Q22_NOT_STOCK_SPECS), the same
# STEP 1-6 grading method, and the same Python-side deterministic scoring
# (_score_q22_single_grader) -- the only thing that changes is that all
# responses in the batch are graded inside one growing conversation instead
# of N independent calls. This is NOT wired into call_primary_grading_agent's
# per-response production routing (grade_with_backend_agent in
# run_experiment_suite.py grades one response at a time); it's a standalone
# entry point the evaluation harness calls once per model for the whole batch.

def _build_q22_batch_session_instructions(question_text: Optional[str]) -> str:
    """
    Persistent session instructions sent ONCE, before any student response.
    Identical grading method/criteria to _build_q22_single_grader_prompt, with
    the per-response student text removed (it arrives per-turn instead) and a
    batch-calibration instruction added at the top.
    """
    scenario = f"QUESTION / SCENARIO:\n{question_text}\n\n" if question_text else ""

    return f"""
You are the SINGLE GRADER for an undergraduate pharmacy open-ended assessment.

This is a ONE-MODEL benchmark. There is NO auditor, second grader, or
adjudicator. Do NOT calculate or report a numerical total -- Python will
calculate the score from your criterion decisions.

BATCH GRADING NOTICE:
You will grade MULTIPLE student responses to this SAME question, one at a
time, within this one continuous conversation. Use everything you have
already seen in this session -- every prior response and every decision you
have already made -- to keep ONE consistent internal standard for what counts
as clearly demonstrating each criterion across the whole batch. If a later
response makes you realise an earlier judgement call was too strict or too
lenient relative to the rest of the batch, apply that lesson to how you judge
every subsequent borderline case, the way a human marker calibrates while
marking a stack of scripts. Do not go back and revise a decision you already
returned for an earlier response.

{scenario}============================================================
STEP 1 — ANALYSE POSITION BEFORE GRADING
============================================================

For EACH response, first classify it as ONE of:

CLEAR_STOCK
CLEAR_DO_NOT_STOCK
MIXED

CLEAR_STOCK:
The student's own recommendation is clearly to stock/sell/recommend the product.

CLEAR_DO_NOT_STOCK:
The student's own recommendation is clearly not to stock/sell/recommend it.

MIXED:
The response contains meaningful arguments or apparent recommendations on BOTH
sides, or wording that could cause the branch to be misread.

If MIXED, identify internally:
1. the student's initial recommendation;
2. arguments supporting STOCK;
3. arguments supporting DO_NOT_STOCK;
4. any explicit final conclusion;
5. which position is actually the student's final/overall recommendation.

IMPORTANT POSITION RULES:
- A counterargument is NOT automatically the student's final position.
- Do NOT choose DO_NOT_STOCK merely because the student later writes
  "No because..." while critically discussing the other side.
- If an explicit final recommendation exists, give it greatest weight.
- Otherwise choose the recommendation most clearly presented as the student's
  own decision rather than an argument they are merely considering.

After that analysis, choose exactly one FINAL SCORING BRANCH:
STOCK or DO_NOT_STOCK.

============================================================
STEP 2 — APPLY ONLY THE SELECTED RUBRIC BRANCH
============================================================

If final_position = STOCK, evaluate ALL of these:
{json.dumps(_Q22_STOCK_SPECS, indent=2)}

If final_position = DO_NOT_STOCK, evaluate ALL of these:
{json.dumps(_Q22_NOT_STOCK_SPECS, indent=2)}

============================================================
STEP 3 — CALIBRATED HUMAN-MARKER SEMANTIC MATCHING
============================================================

For every applicable criterion:
1. Identify the MINIMUM underlying concept required.
2. Search the ENTIRE response for evidence.
3. Judge MEANING, not keyword overlap.
4. Decide MET or NOT_MET.
5. For MET, quote the strongest student-authored evidence verbatim.
6. For NOT_MET, briefly identify the missing concept.

Use these boundary examples to calibrate your judgement. They are examples,
NOT exact phrases that must appear.

S4 SCIENTIFIC EVIDENCE
MET examples: "research evidence supports it"; "scientifically proven";
"studies/trials showed positive results"; "clinical evidence suggests it is
effective".
NOT_MET examples: "I think it works"; "it should be effective"; a bare
efficacy claim with no evidence/research/study meaning.

S6 SAFETY CONCLUSION
MET examples: "the product is safe"; "approved safety and quality"; "the
safety risk is low"; "acceptable safety profile"; "fewer/lower side effects".
NOT_MET examples: "TGA approved" by itself; "listed on ARTG" by itself;
"regulated" by itself.
IMPORTANT: regulatory status alone is not S6, but the student's OWN wording
may communicate a separate safety conclusion from it.

S7 SAFETY RATIONALE
MET examples: established/common oral cetirizine use is linked to safety;
topical/local use is linked to low risk; low systemic exposure from topical
use is linked to safety.
NOT_MET: merely saying "safe" without the oral/topical rationale.

N1 LIMITED EVIDENCE BASE
MET examples: "small sample"; "few patients/participants"; "too few studies";
"the current evidence is limited/insufficient".
NOT_MET: "more research would be useful" with no statement that CURRENT
evidence is limited; "I want to read more papers".

N2 SAFETY-EVIDENCE GAP
MET examples: "no safety evidence is provided"; "safety data is lacking";
"the evidence does not establish safety".
NOT_MET: "it may be unsafe" without identifying an evidence gap; "I need more
information" without identifying an evidence gap.

S8 / N3 OPEN ALTERNATIVE
Actively look for ONE distinct scientifically, clinically, pharmacologically,
or pharmaceutically reasonable safety/efficacy point that supports the selected
position and has NOT already been credited. Do not require resemblance to a
model answer. Do not use it as a generic bonus mark.

GENERAL SEMANTIC RULES:
- Accept synonyms, paraphrases, concise answers, examples, and scientifically
  valid alternative terminology.
- Do NOT require exact rubric wording.
- Do NOT require more precision or explanation than the criterion itself requires.
- An implicit conclusion can count only when it is clearly communicated.
- Do NOT invent knowledge the student did not communicate.
- Do NOT copy facts from the scenario into the student's answer.
- A related keyword alone is insufficient.
- One sentence can support two DIFFERENT criteria only if it genuinely
  communicates two distinct rubric concepts.

============================================================
STEP 4 — NO NEGATIVE MARKING / NO DOUBLE COUNTING
============================================================

Incorrect or irrelevant information elsewhere does not remove a valid mark unless
it directly contradicts the evidence used for that SAME criterion.

Award each distinct criterion at most once. Do not award the same underlying
point twice.

============================================================
STEP 5 — MANDATORY FALSE-NEGATIVE RECHECK
============================================================

Before finalising each response, revisit EVERY criterion initially marked
NOT_MET and re-read the ENTIRE response, checking for synonyms, paraphrases,
examples, implicit but unambiguous conclusions, alternative terminology, or
valid alternative reasoning a reasonable human educator would accept. If YES,
change it to MET and quote the evidence. If it requires inventing an unstated
idea, keep NOT_MET.

============================================================
STEP 6 — OUTPUT FORMAT
============================================================

For EACH student response I send you, reply with ONLY this JSON object for
THAT response (no extra commentary, no markdown fences):

{{
  "stance_classification": "CLEAR_STOCK",
  "final_recommendation_evidence": "verbatim quote or null",
  "final_position": "STOCK",
  "position_reason": "brief explanation",
  "decisions": [
    {{
      "id": "S1",
      "met": true,
      "evidence": "verbatim student quote or null",
      "reason": "brief criterion-specific explanation"
    }}
  ],
  "false_negative_recheck_completed": true
}}

I will send you one student response at a time. Periodically I will resend
these full instructions as a reminder -- continue applying them exactly.
Confirm you understand by waiting for the first student response; do not
output anything until then.
"""


def grade_q22_batch_session(
    responses: list,
    question_text: Optional[str],
    model: str,
    refresh_every: int = 15,
    mode: str = "v8",
) -> list:
    """
    Grades a batch of Q22 responses inside ONE continuous conversation instead
    of N independent stateless calls -- see the module comment above for why
    (testing whether cohort-relative calibration, not criterion wording, is
    what's been capping ICC at ~0.5 across v4-v8). Criteria and per-criterion
    method are held IDENTICAL to the corresponding single-call prompt for the
    chosen `mode`; only the batching structure changes, to isolate that one
    variable.

    `mode`:
      "v8"              -> engineered S1-S8/N1-N3 specs (_build_q22_batch_session_instructions,
                           _score_q22_single_grader).
      "rubric_semantic" -> lecturer's literal numbered rubric bullets, no engineered
                           boundary examples, and an explicit refusal to credit facts the
                           student never stated (_build_q22_rubric_semantic_batch_instructions,
                           _score_q22_rubric_semantic).

    `responses` is a list of {"id": ..., "student_text": ...} dicts, in the
    order they should be graded. Returns a list of dicts in the same order,
    each either a full scorer result (with "id" added) or
    {"id": ..., "overall_score": None, "status": "failed"} if that turn's API
    call failed -- callers must exclude failures from metrics rather than
    treat them as a real 0, consistent with the rest of this codebase's
    "never fabricate a grade" rule.

    Cost/latency note: unlike per-response grading, the conversation grows on
    every turn (all prior responses + all prior JSON replies are resent each
    call), so total token cost is O(n^2) in the number of responses rather
    than O(n). This is an experimental harness path, not a production one.
    """
    if mode == "rubric_semantic":
        instructions = _build_q22_rubric_semantic_batch_instructions(question_text)
        scorer = _score_q22_rubric_semantic
    else:
        instructions = _build_q22_batch_session_instructions(question_text)
        scorer = _score_q22_single_grader

    messages = [
        {
            "role": "system",
            "content": (
                "You are the single undergraduate pharmacy Grader agent, grading a batch "
                "of responses to the same question inside one continuous session. Apply the "
                "rubric as a reasonable human pharmacy educator would, judging semantic "
                "meaning rather than keyword overlap, and keep a consistent standard across "
                "the whole batch. Do not calculate a total score. Reply only with the JSON "
                "object requested for each response."
            ),
        },
        {"role": "user", "content": instructions},
    ]

    results = []
    total = len(responses)
    for i, resp in enumerate(responses):
        if i > 0 and refresh_every and i % refresh_every == 0:
            # Periodic instruction refresh, mirroring the cited reference prompt's
            # step 4 -- guards against long-session instruction drift once batches
            # grow past this session's dev-set size of 15.
            messages.append({
                "role": "user",
                "content": (
                    "Before continuing, here are the full instructions again as a reminder:\n\n"
                    + instructions
                ),
            })

        messages.append({
            "role": "user",
            "content": (
                f"STUDENT RESPONSE {i + 1} of {total} (id={resp['id']}):\n"
                f"{resp['student_text']}\n\n"
                "Grade this response now using the rubric and instructions above. "
                "Return ONLY the JSON object for this response."
            ),
        })

        result = _call_openrouter_api(messages, model, temperature=0.0)

        if not result:
            # Keep the conversation well-formed for subsequent turns even though this
            # turn failed -- never fabricate a score for it.
            messages.append({
                "role": "assistant",
                "content": json.dumps({"error": "grading_failed_for_this_response"}),
            })
            results.append({"id": resp["id"], "overall_score": None, "status": "failed"})
            continue

        # Echo the assistant's own JSON decision back into the conversation so later
        # turns can see it as their own prior grading, the way the cited reference
        # prompt's transcript does.
        result_for_context = {k: v for k, v in result.items() if k != "_usage"}
        messages.append({"role": "assistant", "content": json.dumps(result_for_context)})

        scored = scorer(result)
        scored["id"] = resp["id"]
        results.append(scored)

    return results


def _build_position_branched_prompt(
    student_text: str,
    total_max_score: float,
    question_number: str,
    position_a_name: str,
    position_a_criteria: list,
    position_a_cap: float,
    position_b_name: str,
    position_b_criteria: list,
    position_b_cap: float,
    question_text: Optional[str] = None,
) -> str:
    """
    Reusable POSITION-FIRST + BRANCHED-CRITERIA template for any question whose
    rubric provides two mutually exclusive criteria lists keyed to a stated stance
    (agree/disagree, would/wouldn't, yes/no, stock/don't-stock). Not specific to Q22
    -- any future professional-judgement scenario question with this same rubric
    shape should reuse this function with its own criteria lists and caps.

    The model MUST identify the student's position before scoring anything, then
    score ONLY the matching branch's criteria against its own cap -- the other
    branch's criteria and cap do not apply to this response at all. Skipping this
    stance-identification step (grading both branches as one flat list) is what
    causes inconsistent, non-reproducible scores on hedging or mixed responses.

    v2: fixed a ~0.30-0.45 ICC collapse (vs 0.79 baseline) caused by missing
    scenario context and overly strict matching language.

    v3: removed a "weigh the argument as a whole" holistic-bonus step added in v2
    -- the lecturer's rubric is explicitly enumerative ("1 mark for each of the
    following"), not holistic, and a holistic override let the model award marks
    with no specific criterion basis. Replaced with a criterion-level
    missed-criterion recheck instead.

    v4 (post v3 re-benchmark, ICC=0.374, mean error -1.4): v3 was STILL
    systematically under-marking. Root-caused against real benchmark data to two
    things: (1) v3's Step 3 only applied full semantic-equivalence generosity to
    the "any other reasonable point" catch-all criterion, while criteria 1-7 were
    matched more literally against their specific named target -- a response could
    clearly satisfy a criterion's substance while being marked NOT MET because it
    didn't map cleanly onto one specific numbered item; (2) a response containing
    both a stated position AND a counter-argument (e.g. "Yes because X... but
    no because Y...") could get its branch misclassified, since v3 had no explicit
    guidance to weigh the OVERALL recommendation over the mere presence of a
    counterargument -- confirmed against a real case where a human-scored-6 STOCK
    response was branched as DO NOT STOCK and capped at 3.

    v4 restructures the evaluation section (previously one STEP 3 bullet list)
    into the separately-numbered CONCEPTUAL EQUIVALENCE / DISTINGUISH EQUIVALENT
    FROM RELATED / VALID ALTERNATIVE ANSWERS sections used by the team's original
    human-marker-style open-ended protocol (validated on this exact question by
    an independent test), on the hypothesis that giving semantic-equivalence
    reasoning its own dedicated, repeated emphasis produces more consistent
    generosity across ALL criteria than bundling it into one instruction among
    several in a single step. It also adds an explicit "determine the actual
    overall recommendation, don't auto-switch position on a mere counterargument"
    rule to fix the branch-misclassification case above. The branch-first
    structure, JSON schema, no-double-counting rule, and "no holistic bonus"
    constraint from v3 are all preserved unchanged.

    IMPORTANT CAVEAT (carry this into the report, don't just report the ICC delta):
    a more generous matcher can raise agreement with the human benchmark by
    inferring plausible-but-unstated connections (e.g. treating "TGA approved"
    as also implying "safety risk is minimal") that are not literally supported
    by the rubric text. If v4's ICC rises substantially, verify it against MAE/
    bias AND spot-check a few individual criterion decisions against the rubric
    -- distinguish "agreement improved because under-marking was fixed" from
    "agreement improved because the grader now over-infers, coincidentally in the
    same direction the human already leans." If ICC still sits around 0.35-0.45
    after this change, stop tuning the prompt: the remaining gap is very likely a
    benchmark/rubric calibration issue (some human-awarded 6/6 scores cannot be
    reconstructed from 6-8 explicit criteria even generously interpreted), which
    needs the lecturer to criterion-code the largest disagreements, not another
    prompt rewrite.
    """
    a_lines = "\n".join(f"    {i + 1}. {c}" for i, c in enumerate(position_a_criteria))
    b_lines = "\n".join(f"    {i + 1}. {c}" for i, c in enumerate(position_b_criteria))
    scenario_block = f"QUESTION / SCENARIO:\n{question_text}\n\n" if question_text else ""

    return f"""
You are grading an open-ended response from an undergraduate pharmacy student.
Grade the response against the provided question and marking rubric.

{scenario_block}Student Response:
{student_text}

MARKING RUBRIC

First determine whether the student supports:
(A) {position_a_name}
or
(B) {position_b_name}.

If position = {position_a_name}, use these criteria only
(1 mark each; maximum {position_a_cap:.1f}):
{a_lines}

If position = {position_b_name}, use these criteria only
(1 mark each; maximum {position_b_cap:.1f}):
{b_lines}

OPEN-ENDED GRADING PROTOCOL

1. RUBRIC-BASED EVALUATION

Break the applicable marking branch into distinct scoring criteria and evaluate
each criterion independently.

For each criterion:
1. Identify the knowledge, reasoning, mechanism, or justification that the
   criterion is assessing.
2. Identify relevant evidence in the student's response.
3. Decide whether the evidence demonstrates the required criterion.
4. Award 1 mark if the criterion is demonstrated.
5. Withhold the mark if the criterion is not demonstrated.

The rubric defines the expected knowledge and scoring points. Use it as the
primary basis for grading.

POSITION RULE:
Determine the student's overall position before scoring criteria. Use ONLY the
criteria belonging to that position. Do not combine marks from both branches.
A clear statement such as "I would stock", "yes", "I would not stock", or "no"
is strong position evidence. If the response discusses arguments on both sides,
determine the student's actual overall recommendation from the full response
rather than treating the presence of a counterargument as an automatic change
of position. If genuinely ambiguous, choose the position most strongly supported
by the student's overall recommendation and explain the choice.

For {position_a_name}, explicitly choosing to stock the product itself satisfies
the criterion "Ok to stock in community pharmacies" and earns 1 mark.

2. CONCEPTUAL EQUIVALENCE

Do not require the student's wording to exactly match the rubric.

Award a mark when the student's response demonstrates the same underlying
knowledge or concept required by the rubric criterion, even if the student uses
different wording, synonyms, terminology, examples, or sentence structure.

The student does not need to reproduce the specific wording or keywords used in
the rubric if the intended concept is clearly demonstrated.

Before withholding a mark because the wording differs from the rubric, consider
whether a reasonable human pharmacy educator would recognise the response as
demonstrating the same required concept.

Do not require extra detail beyond what the criterion itself requires.

Do not award a mark when the response is only generally related to the topic,
mentions a relevant keyword without demonstrating the required concept, or does
not address what the criterion is testing.

3. DISTINGUISH EQUIVALENT ANSWERS FROM RELATED ANSWERS

An answer should receive the mark when a reasonable pharmacy educator would
recognise that the student has demonstrated the knowledge required by the
criterion.

However, being related to the topic is not sufficient.

Do not award the mark when the response:
- only mentions a related concept or keyword;
- gives a vague statement without demonstrating the required knowledge;
- does not address what the criterion is testing;
- contains incorrect or directly contradictory information for that criterion; or
- requires an assumption that the student did not communicate.

Do not use an unrelated error elsewhere in the response as negative marking.

4. VALID ALTERNATIVE ANSWERS

The rubric may provide examples rather than an exhaustive list of all acceptable
responses.

Accept an alternative answer when it is scientifically, clinically,
pharmacologically, or pharmaceutically valid AND clearly fulfils the intended
scoring criterion.

If the rubric explicitly states "any other reasonable point", treat that as an
open criterion. Award its 1 mark for one distinct, reasonable safety or efficacy
point supporting the student's selected position that has not already been
credited under another criterion.

Examples of wording that may qualify must still be judged in context. A student
may discuss patient benefit, treatment choice, comparative tolerability,
practical safety, quality/safety implications, limitations of the evidence, or
another defensible safety/efficacy consideration without using the rubric's
exact words.

Do not award a mark merely because an alternative answer is plausible or
generally relevant to the topic.

5. EVIDENCE-BASED GRADING

For every awarded criterion, identify the specific evidence from the student's
response that supports the mark.

Quote the student's response verbatim.

Use only information actually stated or clearly communicated by the student.
Do not copy facts from the question/scenario into the student's answer and then
award them as though the student stated them.

6. PARTIAL CREDIT

Follow the marking structure exactly. For this rubric, each satisfied criterion
is worth 1 mark. Do NOT award 0.5 marks or invent fractional marks.

7. NO DOUBLE COUNTING

Award each scoring criterion only once.

A student's statement may support multiple marks only when it clearly satisfies
separate scoring criteria in the rubric.

Do not award multiple marks for different wording of the same idea.

8. ACCURACY AND RELEVANCE

Award marks only for responses that are relevant to the question and factually
accurate.

If a response contains both correct and incorrect information, award marks for
the scoring criteria that are correctly demonstrated unless the incorrect
statement directly contradicts the evidence used for that same criterion.

9. HUMAN-MARKER PERSPECTIVE

Apply the rubric as a reasonable human pharmacy educator would.

Do not penalise a student simply because their answer differs in wording,
structure, terminology, or level of detail from the rubric.

Focus on whether the student has demonstrated the knowledge or reasoning being
assessed.

For every criterion initially judged NOT MET, perform a second pass over the
ENTIRE response specifically looking for a paraphrase, synonym, implication,
example, or valid alternative that a reasonable human marker would accept.
This is a false-negative check, not permission to invent missing knowledge.

10. MAXIMUM SCORE

The score must equal the sum of individually awarded criteria from the selected
branch.

Maximum for {position_a_name}: {position_a_cap:.1f}.
Maximum for {position_b_name}: {position_b_cap:.1f}.
Overall assignment maximum: {total_max_score}.

Do not add holistic bonus marks and do not subtract marks unless the rubric
explicitly specifies a penalty.

11. FINAL VERIFICATION

Before returning the final score, verify that:
- the student's position was determined from their full response;
- only the matching branch was used;
- every awarded mark corresponds to one rubric criterion;
- the student's own evidence demonstrates that criterion;
- valid paraphrases and equivalent terminology were accepted;
- valid alternative answers were considered where the rubric permits them;
- merely related or vague answers were not awarded;
- no scoring point was counted twice;
- no unsupported knowledge was copied from the scenario into the student answer;
- every initially missed criterion received the second-pass human-marker check;
- no fractional marks were used; and
- the arithmetic and branch cap are correct.

OUTPUT FORMAT
Respond ONLY in valid JSON matching this schema:
{{
  "overall_score": 0.0,
  "confidence_score": 0.90,
  "status": "graded",
  "identified_position": "{position_a_name}",
  "position_evidence": "verbatim quote establishing the student's position",
  "reasoning": "Criterion-by-criterion evaluation. For each applicable criterion state MET or NOT MET, quote evidence for MET criteria, and explain semantic-equivalence or alternative-answer decisions.",
  "feedback": {{
    "summary": "Concise rubric-aligned summary.",
    "breakdown": [
      {{
        "question_number": "{question_number}",
        "score_awarded": 0.0,
        "max_score": {max(position_a_cap, position_b_cap):.1f},
        "reasoning": "List the applicable criteria awarded and missed."
      }}
    ]
  }},
  "highlights": [
    {{
      "text": "Exact quote copied verbatim from student submission",
      "question_number": "{question_number}",
      "score_awarded": 0.0,
      "max_score": {max(position_a_cap, position_b_cap):.1f},
      "type": "strength",
      "comment": "Criterion supported by this evidence."
    }}
  ]
}}
"""


def _build_calculation_grading_prompt(
    student_text: str,
    total_max_score: float,
    question_number: str,
    items: list,
    working_mark_each: float,
    answer_mark_each: float,
) -> str:
    """
    SUPERSEDED for Q9 by _build_calculation_extraction_prompt() + Python-side
    _score_calculation_extraction() below. A real benchmark run showed this
    free-form version letting the LLM self-report a total that included an invented
    scoring category outside the rubric (Gemini returned "0 + 1 + 1 + 0 + 1.5 (for
    general logic/rounding attempt) = 3.5" -- there is no such category in the
    lecturer's marking scheme). Any question with a closed, small scoring space per
    sub-item (here: 0/0.5/1.0/1.5 per person) should have the LLM extract evidence
    only and have Python compute the mark, which makes an invented category
    structurally impossible rather than merely instructed against. Left here (and
    still routable) in case a future calculation question's scoring space is too
    unstructured for that pattern to fit cleanly.

    Reusable CALCULATION-VERIFY + MULTI-PART-INDEPENDENT template for any question
    with N independent sub-computations, each worth a "shows correct working" mark
    plus a "states the correct final answer" mark. Not specific to Q9 -- any future
    dosing/calculation question with this shape should reuse this function with its
    own `items` list.

    Guards against the two failure modes the team identified: (1) inferring/rounding
    on the student's behalf when awarding the answer mark, and (2) awarding the same
    point twice, or to the wrong person, when responses aren't clearly labelled.
    """
    items_block = "\n".join(
        f"    - {it['label']}: correct working example \"{it['working_hint']}\"; "
        f"correct final answer is EXACTLY \"{it['expected_answer']}\" (no other value is acceptable)"
        for it in items
    )
    per_item_total = working_mark_each + answer_mark_each
    total_cap = per_item_total * len(items)
    labels = ", ".join(it["label"] for it in items)

    return f"""
You are an expert academic evaluator grading a dosing/calculation response from an
undergraduate pharmacy student.

Total Assignment Max Score: {total_max_score}

Student Submission:
{student_text}

This question has {len(items)} independent sub-computations, one per person:
{items_block}

STEP 1 -- ROUTE CONTENT BY PERSON
Locate the student's calculation/answer for each of {labels} by name, not by
position or order in the response. Each person is scored completely independently
-- do not let a mistake for one person affect another person's score.

STEP 2 -- WORKING MARK ({working_mark_each:.2g} marks per person)
Award the working mark for a person ONLY if the student EXPLICITLY shows correct
working for that person -- an equation, an intermediate dose value (e.g. in mg),
and/or the exact unrounded value, matching the correct working shown above. A bare
final answer with no working shown does NOT earn this mark.

STEP 3 -- FINAL-ANSWER MARK ({answer_mark_each:.2g} marks per person)
Award the final-answer mark for a person ONLY if the student states EXACTLY the
correct final answer shown above for that person. Do not accept a different value,
even if close. Award this mark independently of whether Step 2's working mark was
also awarded.

STEP 4 -- NO INFERENCE, NO DOUBLE COUNTING
Do not award marks based on your own deductions (e.g. rounding the student's number
for them) -- score only what the student explicitly wrote. Do not award a mark
twice for the same person's same point restated in different words. Do not award
marks for anything outside the calculation itself (e.g. administration/counselling
advice) unless explicitly instructed otherwise for this question.

STEP 5 -- VERIFY BEFORE FINALIZING
Before returning your result, confirm:
- Every person ({labels}) was scored independently against their own correct
  values above, not against another person's values.
- No working mark was awarded without an explicit quoted working.
- No answer mark was awarded for a value that isn't an exact match.
- The total does not exceed {total_cap:.2g} marks.
- Every awarded mark has a verbatim quote as evidence.

OUTPUT FORMAT (Respond ONLY in valid JSON matching this schema):
{{
  "overall_score": 0.0,
  "confidence_score": 0.90,
  "status": "graded",
  "reasoning": "Person-by-person: quote the relevant student text, state whether the working mark and answer mark were each met or missed, then sum.",
  "feedback": {{
    "summary": "One-sentence overview of which people's calculations were correct and which were not.",
    "breakdown": [
      {{"question_number": "{question_number} ({items[0]['label']})", "score_awarded": 0.0, "max_score": {per_item_total:.2g}, "reasoning": "Working mark and answer mark outcome for this person, with supporting quotes."}}
    ]
  }},
  "highlights": [
    {{"text": "Exact quote copied verbatim from student submission", "question_number": "{question_number} ({items[0]['label']})", "score_awarded": 0.0, "max_score": {per_item_total:.2g}, "type": "strength", "comment": "Which mark(s) this quote earns or misses."}}
  ]
}}
"""


def _build_calculation_extraction_prompt(student_text: str, items: list) -> str:
    """
    Evidence-EXTRACTION-only prompt for CALCULATION-VERIFY questions -- the LLM is
    deliberately never asked to compute or report a score. It only identifies, per
    person: (1) whether ANY explicit intermediate working was shown, and (2) the
    exact whole-number final answer stated. _score_calculation_extraction() then
    computes the mark in Python. This exists because a real benchmark run showed the
    free-form scoring version (_build_calculation_grading_prompt) let the LLM invent
    a scoring category the rubric doesn't have -- structurally impossible here, since
    Python, not the LLM, decides what a given boolean/number is worth.
    """
    items_block = "\n".join(
        f"    - {it['label']}: correct final answer is EXACTLY {it['expected_final_squares']} whole squares "
        f"(examples of acceptable working for this person: {', '.join(it['acceptable_working_forms'])})"
        for it in items
    )
    labels = ", ".join(it["label"] for it in items)

    return f"""
You are extracting evidence from a pharmacy student's dosing-calculation response.
Do NOT calculate, award, or report a score yourself -- you are only identifying
what the student explicitly wrote, for each of {labels}, independently.

Reference (for your judgement only -- do not quote this back as if the student wrote it):
{items_block}

Student Submission:
{student_text}

For EACH person, extract exactly two fields from the student's own text:

1. "working_shown": true if the student explicitly wrote ANY intermediate
   calculation step for this person -- an equation (e.g. "64 x 10 = 640"), the dose
   in milligrams (e.g. "640mg"), or the exact unrounded square value (e.g. "6.4
   squares"). ANY ONE of these forms is sufficient; the student does not need to
   show all of them. A bare final rounded whole-number answer with NONE of these
   shown does NOT count -- set this to false in that case. Do not infer or assume
   working that was not actually written.

2. "final_squares": the exact whole number of squares the student's final
   ADMINISTRATION INSTRUCTION recommends giving this person, as an integer, or null
   if it isn't a clean whole number. Do not round or infer this yourself.

   IMPORTANT: the correct answer is a clean whole number of squares with NO cutting
   or halving. If the student's final instruction involves cutting, halving, or
   otherwise splitting a square -- e.g. "6 full squares plus a half", "6 and a HALF
   chocolate squares", "6.5 squares", "cut one square in half" -- this is NOT a
   match for the whole-number answer, even though a whole number like "6" appears
   somewhere in that instruction. In that case set final_squares to null (or to the
   student's literal total including the fraction, e.g. 6.5, which will correctly
   fail to match the required integer) -- do not simplify "6 full + a half" down to
   just "6". Route content to the correct person by name, not by position/order.

Do not award marks, compute totals, apply any cap, or invent any additional
category beyond these two fields -- scoring is handled separately from this
extraction.

OUTPUT FORMAT (Respond ONLY in valid JSON matching this schema):
{{
  "extractions": [
    {{"label": "{items[0]['label']}", "working_shown": true, "working_quote": "verbatim quote, or null if working_shown is false", "final_squares": {items[0]['expected_final_squares']}}}
  ],
  "reasoning": "Brief note per person on what evidence was found and why."
}}
"""


def _score_calculation_extraction(
    extraction_res: Dict[str, Any],
    items: list,
    working_mark_each: float,
    answer_mark_each: float,
) -> Dict[str, Any]:
    """
    Deterministically computes the calculation score from the LLM's evidence
    extraction. The LLM identifies what the student wrote; this function decides
    what that evidence is worth. Per person, the only possible outcomes are
    {{0, working_mark_each, answer_mark_each, working_mark_each + answer_mark_each}}
    -- it is structurally impossible for this to produce an invented scoring
    category (e.g. the fabricated "1.5 for general logic/rounding attempt" a real
    benchmark run showed an LLM self-reporting under the old free-form prompt).
    """
    extractions = {
        str(e.get("label", "")).strip().lower(): e
        for e in (extraction_res.get("extractions") or [])
        if isinstance(e, dict)
    }
    per_item_total = working_mark_each + answer_mark_each
    breakdown, highlights = [], []
    total = 0.0

    for it in items:
        e = extractions.get(it["label"].strip().lower(), {})
        working_shown = bool(e.get("working_shown", False))
        final_squares = e.get("final_squares")
        try:
            # Compare as float WITHOUT truncating to int first. A cut/halved answer
            # like 6.5 must correctly fail to match an expected integer of 6 -- int(6.5)
            # truncates to 6 and would silently re-introduce the exact "6 full + a half
            # square" bug the extraction prompt now explicitly guards against.
            final_squares_val = float(final_squares) if final_squares is not None else None
        except (TypeError, ValueError):
            final_squares_val = None

        working_mark = working_mark_each if working_shown else 0.0
        answer_mark = answer_mark_each if final_squares_val == float(it["expected_final_squares"]) else 0.0
        final_squares_int = int(final_squares_val) if (final_squares_val is not None and final_squares_val.is_integer()) else final_squares_val
        person_total = working_mark + answer_mark
        total += person_total

        reasoning = (
            f"Working {'shown' if working_shown else 'NOT shown'} "
            f"({'+' if working_shown else '+0/'}{working_mark_each:.2g} marks); "
            f"final answer extracted as {final_squares_int if final_squares_int is not None else 'none given'} "
            f"squares vs. expected {it['expected_final_squares']} "
            f"({'+' if answer_mark == answer_mark_each else '+0/'}{answer_mark_each:.2g} marks)."
        )
        breakdown.append({
            "question_number": f"Q9 ({it['label']})",
            "score_awarded": round(person_total, 2),
            "max_score": per_item_total,
            "reasoning": reasoning,
        })
        quote = e.get("working_quote")
        if quote:
            highlights.append({
                "text": quote,
                "question_number": f"Q9 ({it['label']})",
                "score_awarded": round(person_total, 2),
                "max_score": per_item_total,
                "type": "strength" if person_total > 0 else "improvement",
                "comment": reasoning,
            })

    return {
        "overall_score": round(total, 2),
        "confidence_score": 0.9,
        "status": "graded",
        "reasoning": extraction_res.get("reasoning", "Deterministically scored in Python from extracted per-person evidence."),
        "feedback": {
            "summary": f"Deterministic calculation scoring across {len(items)} independent sub-computations.",
            "breakdown": breakdown,
        },
        "highlights": highlights,
    }


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
# Why this exists: every specialized template above (_build_checklist_grading_prompt,
# _build_calculation_extraction_prompt/_score_calculation_extraction, and the Q22
# rubric_semantic protocol) is already a genuinely reusable GRADING STRATEGY -- the
# actual prompt engineering (semantic-equivalence wording, strictness dial, evidence
# grounding, no-double-counting, false-negative recheck, deterministic Python
# scoring) doesn't know anything about polymer microspheres or cetirizine. What ISN'T
# reusable is (a) the CONTENT those strategies are fed -- _Q6_CHECKLIST_GROUPS,
# _Q8_CHECKLIST_GROUPS, _Q9_CALCULATION_ITEMS, _Q22_STOCK_CRITERIA_VERBATIM are all
# hand-written Python constants specific to these four benchmark questions -- and
# (b) the routing in call_primary_grading_agent(), which dispatches on the literal
# string "6"/"8"/"9"/"22" rather than on what kind of rubric the question actually
# has. A new Q31 that is structurally identical to Q9 (show working, verify a
# calculated answer) currently falls through to the unspecialized generic prompt,
# not to the calculation strategy that gave Q9 its 0.989 ICC.
#
# This section adds a parallel path that closes that gap: a Rubric Interpreter LLM
# call classifies an ARBITRARY question+rubric into one of the three supported
# grading strategies and extracts a structured "Grading Specification" -- the
# criteria/items/branches -- directly from the rubric text, instead of a developer
# hand-transcribing them into a Python constant. The three existing strategies then
# receive that specification as DATA, exactly the way _build_checklist_grading_prompt
# already accepted `groups` as a parameter rather than importing _Q6_CHECKLIST_GROUPS
# directly -- that function required almost no changes at all to become reusable.
#
# This is deliberately a PARALLEL path, not a replacement. call_primary_grading_agent
# and every _Q6/_Q8/_Q9/_Q22_* constant above are completely unchanged and still
# fully functional -- Q6/Q8/Q9/Q22 keep using the hand-tuned, already-validated
# routing and data exactly as before. The dynamic path is reached only through
# grade_with_dynamic_rubric_interpreter() below, so it can be benchmarked head-to-head
# against the existing hardcoded results on the SAME 25-response sets before anyone
# relies on it. See that function's docstring for why this comparison is essential:
# the interpreter is a new LLM call and therefore a new source of error (misclassified
# question type, mis-extracted criteria, or -- for CALCULATION -- an incorrectly
# derived expected numeric answer where Q9's hardcoded items were human-verified).
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
    module comment above for the schema). This is an expansion of the existing
    call_rubric_context_parser_agent() idea -- classify structure, don't just
    reformat text -- but the two are independent; this one's output feeds directly
    into deterministic Python scoring, so it must not invent anything the rubric
    doesn't actually support.
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
- label: how the rubric/question identifies this sub-part (a name, a letter, etc).
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
  wording). Set position_linked_criterion to the 1-based index of a criterion in
  that branch's list that is ITSELF the position/decision statement (e.g. a
  criterion that just says "this is a reasonable position to take"), if one
  exists -- otherwise null.
- If INDEPENDENT_CRITERIA: a single flat criteria list (the rubric's own wording)
  and use the overall max_score.

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
  "criteria": ["criterion text"]
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
    total_max_score = float(spec.get("max_score") or sum(float(g.get("max_score", 0)) for g in groups))
    prompt = _build_checklist_grading_prompt(
        student_text, total_max_score, groups,
        matching_strictness=spec.get("matching_strictness", "meaning"),
        allow_half_marks=bool(spec.get("allow_half_marks", False)),
    )
    messages = [
        {"role": "system", "content": "You are a precise, objective automated academic grading engine. Always respond strictly in valid JSON format."},
        {"role": "user", "content": prompt},
    ]
    return _call_openrouter_api(messages, model, temperature=0.1)


def _build_calculation_extraction_prompt_dynamic(student_text: str, items: list) -> str:
    """
    Unit-agnostic generalisation of _build_calculation_extraction_prompt(): that
    function's wording is Q9-specific ("chocolate squares", "administration
    instruction"). This version is parameterised by each item's own `unit` instead,
    so it applies to any calculation question (doses in mg, tablet counts, mL,
    dimensionless ratios, etc), while preserving the same extraction-not-scoring
    principle that made Q9 reliable: the LLM only reports what the student wrote,
    Python decides what it's worth.
    """
    items_block = "\n".join(
        f"    - {it['label']}: correct final answer is EXACTLY {it['expected_answer']}"
        f"{' ' + it['unit'] if it.get('unit') else ''}"
        + (f" (tolerance +/- {it['tolerance']})" if it.get("tolerance") else "")
        + (f" (examples of acceptable working: {', '.join(it['acceptable_working_forms'])})" if it.get("acceptable_working_forms") else "")
        for it in items
    )
    labels = ", ".join(it["label"] for it in items)

    return f"""
You are extracting evidence from a student's calculation response. Do NOT
calculate, award, or report a score yourself -- you are only identifying what
the student explicitly wrote, for each of {labels}, independently.

Reference (for your judgement only -- do not quote this back as if the student wrote it):
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
    extractions = {
        str(e.get("label", "")).strip().lower(): e
        for e in (extraction_res.get("extractions") or [])
        if isinstance(e, dict)
    }
    breakdown, highlights = [], []
    total = 0.0

    for it in items:
        e = extractions.get(str(it["label"]).strip().lower(), {})
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
) -> Optional[Dict[str, Any]]:
    """CALCULATION dynamic strategy: extraction-only LLM call, deterministic Python scoring."""
    items = spec.get("items") or []
    if not items:
        return None
    prompt = _build_calculation_extraction_prompt_dynamic(student_text, items)
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
student's position merely because they acknowledge an opposing argument. If
the response opens with an explicit position and later discusses limitations
WITHOUT stating a new final position, retain the original explicit position.
Only treat a different branch as applicable when the student clearly states
that different final position themselves. If genuinely ambiguous, choose the
branch most strongly supported by the balance of the student's own reasoning.

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
identify the closest student-authored statement to that criterion; ask whether
you rejected it only because terminology differed, the wording was less
technical, the reasoning was indirect but still unambiguous, the student
expressed the implication rather than the rubric's exact conclusion, or the
concept was spread across multiple sentences; if so and the underlying concept
is still clearly demonstrated, change the decision to MET. Keep it NOT MET
only when you can state the substantive concept that is genuinely missing.
Do not change a criterion to MET merely to increase the score.

OUTPUT ONLY VALID JSON:
{{
  "chosen_branch_id": {"null" if structure != "BRANCHED" else '"B1"'},
  "branch_evidence": "verbatim quote establishing the position, or null",
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
        branch = next((b for b in branches if str(b.get("id")) == str(chosen_id)), None)
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

    Any non-fatal review flags attached to the spec (see interpret_rubric_spec's
    docstring -- currently just DERIVED calculation answers) are copied into the
    result's flag_reasons, so a human reviewing this grade sees them, the same way
    the rest of this codebase surfaces "AI Grading Unavailable" or "Grading
    Breakdown Unavailable" rather than letting a caveat disappear into a log line.
    """
    q_type = str(spec.get("question_type", "")).strip().upper()

    if q_type == "SHORT_ANSWER":
        result = _grade_short_answer_dynamic(student_text, spec, model)
    elif q_type == "CALCULATION":
        result = _grade_calculation_dynamic(student_text, spec, model)
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


def grade_with_dynamic_rubric_interpreter(
    student_text: str,
    question_text: str,
    rubric_text: str,
    max_score: float,
    model: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Convenience wrapper: interpret_rubric_spec() + grade_with_spec() in one call,
    for grading a SINGLE response. This is the "new question, same shape, zero
    code change" path -- call this instead of call_primary_grading_agent() to
    grade a question purely from its own text and rubric, with no question-number
    routing at all.

    DO NOT use this in a loop over multiple responses to the SAME question -- it
    re-runs the Rubric Interpreter every call. For a batch (e.g. an entire cohort's
    answers to one question), call interpret_rubric_spec() once and then
    grade_with_spec() per response instead; see interpret_rubric_spec's docstring
    for why re-interpreting per response is a real correctness risk, not just a
    cost one.

    IMPORTANT -- validate before trusting: this introduces the Rubric Interpreter
    as a genuinely new source of error that the hardcoded Q6/Q8/Q9/Q22 paths never
    had -- a misclassified question_type, a mis-extracted criterion, or (for
    CALCULATION) an incorrectly derived expected_answer where Q9's hardcoded items
    were a human-verified answer key. Before relying on this for any question,
    benchmark it against the existing hardcoded results on the SAME response set:
    run this path for Q6/Q8/Q9/Q22 (ignoring their question numbers entirely,
    feeding only their question text + raw rubric text) and compare ICC/MAE/bias
    against results_Gemini_3.1_Flash_Lite.csv etc. If it doesn't reproduce
    comparable agreement on questions we already have ground truth for, it should
    not be trusted on genuinely new questions where we have no such check.
    """
    target_model = model or get_llm_model()
    spec = interpret_rubric_spec(question_text, rubric_text, max_score, target_model)
    if not spec:
        return None
    return grade_with_spec(student_text, question_text, spec, target_model)


def call_primary_grading_agent(student_text: str, structured_rubric: Dict[str, Any], raw_rubric_json: list, model_answer: str, rag_context: str, total_max_score: float = 10.0, model: Optional[str] = None, question_no: Optional[str] = None, question_text: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Agent 2 (Primary CoT Evaluation Agent):
    Evaluates student responses against standardized rubric rules and RAG context.

    question_no routes to one of four reusable, tag-composed templates instead of
    one bespoke prompt per question -- each question's rubric shape determines which
    template applies:
      "6"  -> _build_checklist_grading_prompt  (CHECKLIST-POOL + MULTI-PART-INDEPENDENT)
      "8"  -> _build_checklist_grading_prompt  (POSITION-FIRST-per-item + MULTI-PART-INDEPENDENT,
              modelled as an explicit-strictness checklist since each of its 5 items is an
              independent verdict+reason pair, not a branching pair)
      "9"  -> _build_calculation_extraction_prompt + _score_calculation_extraction
              (CALCULATION-VERIFY + MULTI-PART-INDEPENDENT, scored deterministically in
              Python from an LLM evidence extraction -- see that function's docstring
              for why: the LLM is not trusted to self-report a score in a closed
              per-person scoring space, since a benchmark run showed it inventing a
              scoring category the rubric doesn't have)
      "22" -> Q22 v8-calibrated-single-grader pipeline: ONE grader LLM call
              (CLEAR_STOCK/CLEAR_DO_NOT_STOCK/MIXED stance analysis + all
              criterion decisions against calibrated MET/NOT_MET boundary
              examples + a mandatory internal false-negative self-check, all
              within that one generation) -> deterministic Python scoring.
              Deliberately a single call with no second-model audit pass, so
              this benchmarks the grader model alone. See
              _grade_q22_extraction_pipeline's docstring for the "stop
              rewriting the prompt" note: v4-v8 have all plateaued around
              ICC 0.32-0.53 on two different underlying models, which points
              at a rubric/ground-truth gap rather than a prompt-wording one.
              _build_position_branched_prompt below is kept for
              reference/reuse but no longer routed to)
    Any other value (None, or a multi-question call) falls back to the original
    generic rubric-driven prompt unchanged.
    """
    q_key = str(question_no).strip().upper().replace("Q", "") if question_no else None

    if q_key == "22":
        target_model = model or get_llm_model()
        # Q22_GRADING_MODE (default "v8"): controlled A/B switch across two Q22
        # grading policies, both sharing the same one-call/no-auditor architecture
        # and deterministic Python scoring:
        #   "v8"              -> engineered S1-S8/N1-N3 specs.
        #   "rubric_semantic" -> lecturer's literal rubric bullets; explicitly
        #                        refuses to credit a fact the student never stated.
        q22_mode = os.getenv("Q22_GRADING_MODE", "v8").strip().lower()
        if q22_mode == "rubric_semantic":
            return _grade_q22_rubric_semantic_pipeline(student_text, question_text, target_model)
        # Default: Q22 v8-calibrated-single-grader. ONE LLM call handles stance
        # analysis + all criterion decisions + its own internal self-check;
        # Python alone converts decisions into marks and applies the branch cap.
        # No second-model audit call here.
        return _grade_q22_extraction_pipeline(student_text, question_text, target_model)

    if q_key == "9":
        # Extraction-only call: the LLM never reports a score for Q9, so it returns
        # early here rather than falling through to the shared prompt+API-call block
        # below (which is for templates where the LLM does report overall_score).
        extraction_prompt = _build_calculation_extraction_prompt(student_text, _Q9_CALCULATION_ITEMS)
        messages = [
            {"role": "system", "content": "You are a precise evidence-extraction engine for academic grading. Always respond strictly in valid JSON format. Do not calculate or report any score."},
            {"role": "user", "content": extraction_prompt}
        ]
        target_model = model or get_llm_model()
        extraction_res = _call_openrouter_api(messages, target_model, temperature=0.0)
        if not extraction_res:
            return None
        return _score_calculation_extraction(extraction_res, _Q9_CALCULATION_ITEMS, working_mark_each=0.5, answer_mark_each=1.0)

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


_SPECIALIZED_QUESTION_KEYS = {"6", "8", "9", "22"}


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


def _grade_primary_per_question(
    student_text: str,
    structured_rubric: Dict[str, Any],
    rubric_json: list,
    model_answer: str,
    rag_context: str,
    total_max_score: float,
) -> Optional[Dict[str, Any]]:
    """
    Opt-in alternative to a single whole-submission call. A submission graded via
    run_grading_pipeline is one student's ENTIRE assignment response (all questions
    concatenated), whereas the specialized Q6/Q8/Q9/Q22 templates are built to grade
    ONE question at a time -- passing question_no into a single whole-submission call
    would not actually make sense. This splits the submission back into per-question
    sections, sends each specialized question through its own dedicated template, and
    batches every remaining (non-specialized) question into one generic call -- then
    merges everything into one primary_res dict so the rest of the pipeline (auditor,
    confidence engine, breakdown handling) is unaffected and unaware of the split.

    Cost/latency note: this trades one API call per submission for up to
    (specialized questions present) + 1 calls. Gated behind ENABLE_PER_QUESTION_PROMPTS
    in call_llm_for_grading because that can meaningfully affect both API cost and
    NFR-01 (30 submissions / 10 minutes), especially with slower models like Nemotron.

    Returns None (never partial/fabricated data) if the submission can't be split, if
    no rubric item actually maps to a specialized template, or if every sub-call
    failed -- callers should fall back to the existing single-call path in each case.
    """
    sections = _split_submission_by_question(student_text)
    if not sections:
        return None

    specialized_items = []
    generic_items = []
    generic_text_parts = []
    for item in rubric_json:
        if not isinstance(item, dict):
            continue
        q_label = str(item.get("question_number") or item.get("criterion") or "").strip().upper()
        q_key = q_label.replace("Q", "").split("(")[0]
        section_text = sections.get(q_label) or sections.get(f"Q{q_key}") or sections.get(q_key)
        if q_key in _SPECIALIZED_QUESTION_KEYS and section_text is not None:
            specialized_items.append((q_key, q_label, section_text, item))
        else:
            generic_items.append(item)
            if section_text is not None:
                generic_text_parts.append(f"Question {q_label}:\n{section_text}")

    if not specialized_items:
        return None

    merged_breakdown, merged_highlights, merged_reasoning = [], [], []

    for q_key, q_label, section_text, rubric_item in specialized_items:
        q_max = float(rubric_item.get("max_score", rubric_item.get("maxMark", 10.0)))
        q_text = rubric_item.get("question") or rubric_item.get("question_text") or rubric_item.get("prompt")
        sub_res = call_primary_grading_agent(
            section_text, structured_rubric, [rubric_item], model_answer, rag_context,
            total_max_score=q_max, question_no=q_key, question_text=q_text,
        )
        if not sub_res:
            continue  # missing sub-grade -- an empty merged_breakdown below is caught by breakdown_unavailable handling
        sub_feedback = sub_res.get("feedback") if isinstance(sub_res.get("feedback"), dict) else {}
        merged_breakdown.extend(b for b in (sub_feedback or {}).get("breakdown", []) if isinstance(b, dict))
        merged_highlights.extend(h for h in sub_res.get("highlights", []) if isinstance(h, dict))
        if sub_res.get("reasoning"):
            merged_reasoning.append(f"[{q_label}] {sub_res['reasoning']}")

    if generic_items:
        generic_text = "\n\n".join(generic_text_parts) if generic_text_parts else student_text
        generic_max = sum(float(it.get("max_score", it.get("maxMark", 5.0))) for it in generic_items)
        generic_res = call_primary_grading_agent(
            generic_text, structured_rubric, generic_items, model_answer, rag_context,
            total_max_score=generic_max,
        )
        if generic_res:
            generic_feedback = generic_res.get("feedback") if isinstance(generic_res.get("feedback"), dict) else {}
            merged_breakdown.extend(b for b in (generic_feedback or {}).get("breakdown", []) if isinstance(b, dict))
            merged_highlights.extend(h for h in generic_res.get("highlights", []) if isinstance(h, dict))
            if generic_res.get("reasoning"):
                merged_reasoning.append(f"[other questions] {generic_res['reasoning']}")

    if not merged_breakdown:
        return None

    overall_score = round(sum(float(b.get("score_awarded", 0.0)) for b in merged_breakdown), 1)
    return {
        "overall_score": overall_score,
        "confidence_score": 0.85,  # placeholder -- recomputed by evaluate_confidence_and_status() downstream
        "status": "graded",
        "reasoning": "\n\n".join(merged_reasoning) or "Graded per-question using specialized templates.",
        "feedback": {
            "summary": f"Graded across {len(specialized_items)} specialized-template question(s) and {len(generic_items)} generic question(s).",
            "breakdown": merged_breakdown,
        },
        "highlights": merged_highlights,
    }


def call_llm_for_grading(student_text: str, rubric_json: list, model_answer: str, rag_context: str, total_max_score: float = 10.0) -> Dict[str, Any]:
    """
    Orchestrates Multi-Agent Grading Pipeline using google/gemini-3.1-flash-lite across 3 agents:
    - Agent 1: Rubric & RAG Context Parser Agent
    - Agent 2: Primary CoT Evaluation Agent
    - Agent 3: Auditor Verification Agent
    - Step 4: Deterministic Confidence & Audit Engine
    """
    if not get_openrouter_api_key():
        print("[LLM Service] OPENROUTER_API_KEY not set. Flagging submission for manual review.")
        return _mock_heuristic_evaluation(student_text, rubric_json, reason="OPENROUTER_API_KEY not configured")

    # Step 1: Agent 1 - Rubric & Context Parser Agent
    parser_res = call_rubric_context_parser_agent(rubric_json, model_answer, rag_context)
    structured_rubric = parser_res if parser_res else {"structured_rules": rubric_json}

    # Step 2: Agent 2 - Primary CoT Grader Agent
    # ENABLE_PER_QUESTION_PROMPTS (default off): splits a multi-question submission and
    # routes Q6/Q8/Q9/Q22 through their specialized templates instead of the single
    # generic whole-submission prompt. Off by default because it trades 1 API call per
    # submission for up to N -- turn on deliberately once you've weighed the cost/latency
    # impact against the ICC gain (see _grade_primary_per_question's docstring).
    primary_res = None
    if os.getenv("ENABLE_PER_QUESTION_PROMPTS", "false").strip().lower() in ("1", "true", "yes"):
        primary_res = _grade_primary_per_question(student_text, structured_rubric, rubric_json, model_answer, rag_context, total_max_score)
    if not primary_res:
        primary_res = call_primary_grading_agent(student_text, structured_rubric, rubric_json, model_answer, rag_context, total_max_score)
    if not primary_res:
        print("[LLM Service Warning] Primary Agent call failed after all retries. Flagging submission for manual review.")
        return _mock_heuristic_evaluation(student_text, rubric_json, reason="primary grading agent failed after all retries")

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

    if breakdown_unavailable:
        # A missing per-question breakdown means we don't have reliable criterion-level
        # marks even if the aggregate agreement score above looks fine -- override the
        # confidence engine's status here so this can never be silently auto-approved.
        primary_res["status"] = "flagged"
        flags = primary_res.get("flag_reasons")
        flags = list(flags) if isinstance(flags, list) else []
        reason = "⚠️ Grading Breakdown Unavailable — Manual Review Required"
        if reason not in flags:
            flags.insert(0, reason)
        primary_res["flag_reasons"] = flags

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


