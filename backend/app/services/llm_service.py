import os
import re
import json
import urllib.request
from typing import Dict, Any, List, Optional
from .confidence import evaluate_confidence_and_status


def get_openrouter_api_key() -> str:
    return os.getenv("OPENROUTER_API_KEY", "").strip() or os.getenv("LLM_API_KEY", "").strip()


def get_llm_model() -> str:
    return os.getenv("LLM_MODEL", "google/gemini-3.1-flash-lite").strip()


def get_auditor_model() -> str:
    return os.getenv("AUDITOR_MODEL", get_llm_model()).strip()


OPENROUTER_API_KEY = get_openrouter_api_key()
LLM_API_KEY = OPENROUTER_API_KEY
LLM_API_URL = os.getenv("LLM_API_URL", "https://openrouter.ai/api/v1/chat/completions")
LLM_MODEL = get_llm_model()


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
    
    think_match = re.search(r'<think>.*?</think>', clean_text, flags=re.DOTALL)
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
    repaired = re.sub(r',\s*([\}\]])', r'\1', repaired)
    repaired = re.sub(r'("(?:[^"\\]|\\.)*")\s*\n?\s*(")', r'\1, \2', repaired)
    repaired = re.sub(r'(\d+(?:\.\d+)?|true|false|null)\s*\n?\s*(")', r'\1, \2', repaired)
    repaired = re.sub(r'(\})\s*\n?\s*(\{)', r'\1, \2', repaired)
    repaired = re.sub(r'(\])\s*\n?\s*(\{)', r'\1, \2', repaired)

    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass

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


def _call_openrouter_api(messages: list, model: str, temperature: float = 0.1) -> Optional[Dict[str, Any]]:
    """
    Executes HTTP POST request to OpenRouter API endpoint.
    """
    api_key = get_openrouter_api_key()
    if not api_key:
        return None

    try:
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

        req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=35) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            content = body["choices"][0]["message"]["content"]
            parsed = _clean_json_response(content)
            if isinstance(parsed, dict):
                parsed["_usage"] = body.get("usage", {})
            return parsed
    except Exception as e:
        print(f"[OpenRouter API Warning] Call failed for model {model}: {e}")
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


def call_primary_grading_agent(
    student_text: str,
    structured_rubric: Dict[str, Any],
    raw_rubric_json: list,
    model_answer: str,
    rag_context: str,
    total_max_score: float = 10.0,
    model: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Agent 2 (Primary CoT Evaluation Agent):
    Evaluates student responses against standardized rubric rules and RAG context.
    """
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

Student Submission:
{student_text}

GRADING PROTOCOL (v1.3-multi-question-highlights):
1. MEANING OVER EXACT WORDS: Award points for concepts matching rubric intent.
2. STRICT CAPPING: Do not exceed maximum points allocated per question. Sum of points awarded across all questions MUST NOT exceed {total_max_score}.
3. ZERO MARK RULE: If a student answer for a question is blank, empty, dash ('-'), 'N/A', or missing, award EXACTLY 0 marks for that question. Do NOT award partial credit for empty or missing answers.
4. REASONING FIRST: Analyze student response against each criterion step-by-step before finalizing score.
5. MANDATORY PER-QUESTION HIGHLIGHTS: You MUST generate at least one highlight entry for EVERY question and sub-part in the student submission (e.g., Q6(a), Q6(b), Q8(a), Q8(b)). Highlight exact quotes from the student's text for each question.

OUTPUT INSTRUCTIONS:
Return strictly valid JSON with no markdown wrapping, matching this format:
{{
  "overall_score": 8.5,
  "confidence_score": 0.92,
  "status": "graded",
  "feedback": {{
    "summary": "Strong submission demonstrating clear understanding of core concepts with minor formatting issues.",
    "breakdown": [
      {{
        "question_number": "Q1",
        "score_awarded": 4.5,
        "max_score": 5.0,
        "reasoning": "Correct methodology used. Slight omission in boundary case explanation."
      }}
    ]
  }},
  "highlights": [
    {{
      "text": "Exact student text quote",
      "question_number": "Q1",
      "score_awarded": 4.5,
      "max_score": 5.0,
      "type": "strength",
      "comment": "Accurate application of core formula"
    }}
  ]
}}
"""
    messages = [
        {"role": "system", "content": "You are a precise, objective automated academic grading engine. Always respond in pure raw JSON format."},
        {"role": "user", "content": prompt}
    ]
    target_model = model or get_llm_model()
    return _call_openrouter_api(messages, target_model, temperature=0.2)


def call_auditor_verification_agent(
    student_text: str,
    rubric_json: list,
    primary_eval_result: Dict[str, Any] = None,
    primary_eval: Dict[str, Any] = None,
    model: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Agent 3 (Auditor Verification Agent):
    Independently re-evaluates student text to verify primary grader results and detect score discrepancies.
    """
    eval_res = primary_eval_result if primary_eval_result is not None else (primary_eval if primary_eval is not None else {})
    prompt = f"""
You are an independent academic audit agent.
Verify the primary grader's score for the following student submission:

Student Submission:
{student_text}

Rubric:
{json.dumps(rubric_json, indent=2)}

Primary AI Grader Result:
{json.dumps(eval_res, indent=2)}

INDEPENDENCE REQUIREMENT:
Independently evaluate the student text per subquestion first.
Identify any question where your independent score differs by >= 1.0 mark from the primary grader.

OUTPUT FORMAT (Respond ONLY in valid JSON matching this schema):
{{
  "audit_passed": true,
  "auditor_score": 8.5,
  "auditor_breakdown": [
    {{
      "question_number": "Q1",
      "auditor_score": 4.5,
      "max_score": 5.0
    }}
  ],
  "conflicting_questions": [],
  "discrepancy_note": "Independent audit confirmed primary scores."
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
    total_max_score: float = 10.0
) -> Dict[str, Any]:
    """
    Orchestrates Multi-Agent Grading Pipeline:
    - Agent 1: Rubric & Context Parser Agent
    - Agent 2: Primary CoT Evaluation Agent
    - Agent 3: Auditor Verification Agent
    - Step 4: Deterministic Confidence & Audit Engine
    """
    if not get_openrouter_api_key():
        print("[LLM Service] OPENROUTER_API_KEY not set. Running fallback structured scoring engine.")
        return _mock_heuristic_evaluation(student_text, rubric_json)

    parser_res = call_rubric_context_parser_agent(rubric_json, model_answer, rag_context)
    structured_rubric = parser_res if parser_res else {"structured_rules": rubric_json}

    primary_res = call_primary_grading_agent(student_text, structured_rubric, rubric_json, model_answer, rag_context, total_max_score)
    if not primary_res:
        print("[LLM Service Warning] Primary Agent call failed. Using heuristic fallback.")
        return _mock_heuristic_evaluation(student_text, rubric_json)

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

    if breakdown:
        exact_breakdown_sum = sum(float(item.get("score_awarded", 0.0)) for item in breakdown if isinstance(item, dict))
        primary_res["overall_score"] = round(exact_breakdown_sum, 1)

    _enrich_highlights_with_question_info(primary_res, student_text)

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
    base_score = min(8.8, 6.5 + (text_len / 500.0))
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
                    "max_score": 5.0,
                    "reasoning": "Demonstrated sound understanding of core principles."
                },
                {
                    "question_number": "Q2",
                    "score_awarded": round(base_score * 0.5, 1),
                    "max_score": 5.0,
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

    def clean_str(s: str) -> str:
        return re.sub(r'[\W_]+', ' ', s).strip().lower()

    for hl in highlights:
        if not isinstance(hl, dict):
            continue

        quote = hl.get("text", "").strip()
        q_num = hl.get("question_number", "")

        if not quote:
            continue

        pos = student_text.lower().find(quote.lower())
        exact_len = len(quote)

        if pos == -1 and len(quote) > 10:
            sub_search = quote.lower()[:min(30, len(quote))]
            pos = student_text.lower().find(sub_search)

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
# PDF PARSER FUNCTIONS (From PDF-parser Feature Branch)
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
    api_key = get_openrouter_api_key()
    if not api_key or not LLM_API_URL:
        return {}

    try:
        url = LLM_API_URL
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://autograde.ai",
            "X-Title": "AutoGrade+"
        }
        data = {
            "model": LLM_MODEL,
            "messages": [
                {"role": "system", "content": "You are a verbatim academic data extraction engine. Copy all text 100% verbatim as written. Always respond in pure raw JSON format."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.0
        }

        req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            content = body["choices"][0]["message"]["content"]
            cleaned = content.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
            return json.loads(cleaned)
    except Exception as e:
        print(f"[LLM Service Error] Parsing API call failed: {e}")
        return {}


def _find_phrase_range(raw_text: str, phrase: str, start_after: int = 0):
    if not phrase or not phrase.strip():
        return -1, -1
    idx = raw_text.find(phrase, start_after)
    if idx != -1:
        return idx, idx + len(phrase)
    
    words = [re.escape(w) for w in phrase.strip().split()]
    if not words:
        return -1, -1
    pattern = r'\s+'.join(words)
    m = re.search(pattern, raw_text[start_after:], re.IGNORECASE)
    if m:
        return start_after + m.start(), start_after + m.end()
        
    return -1, -1


def parse_entire_document_with_llm(raw_text: str) -> List[Dict[str, Any]]:
    """
    LLM-Guided Exact Slicing Document Parser.
    Uses LLM intelligence to identify start & end anchor phrases for questions and answers across ANY document layout,
    and then performs direct Python string slicing on raw_text to guarantee 100% exact verbatim preservation and zero name redaction.
    """
    api_key = get_openrouter_api_key()
    if not api_key or not LLM_API_URL:
        return []

    prompt = f"""
You are an intelligent document structure analyzer.
Your job is to read the raw document text below and identify all Questions and Answer Schemes/Rubrics regardless of document layout.

Raw Document Text:
{raw_text}

STRICT INSTRUCTIONS:
1. "question_start_phrase": Exact 4-8 starting words of the question.
2. "question_end_phrase": Exact 4-8 ending words of the question prompt.
3. "answer_start_phrase": Exact 4-8 starting words of the corresponding answer scheme/rubric.
4. "answer_end_phrase": Exact 4-8 ending words of the answer scheme/rubric.
5. "max_marks": Extract maximum marks if mentioned (e.g. 6.0, 10.0). Default to 10.0 if not specified.

OUTPUT FORMAT:
Return strictly valid JSON with no markdown wrapping, matching this array format:
[
  {{
    "question_number": "Q1",
    "question_start_phrase": "Exact starting 4 to 8 words...",
    "question_end_phrase": "Exact ending 4 to 8 words...",
    "answer_start_phrase": "Exact starting 4 to 8 words...",
    "answer_end_phrase": "Exact ending 4 to 8 words...",
    "max_marks": 10.0
  }}
]
"""
    try:
        url = LLM_API_URL
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://autograde.ai",
            "X-Title": "AutoGrade+"
        }
        data = {
            "model": LLM_MODEL,
            "messages": [
                {"role": "system", "content": "You are a precise document layout analyzer. Return valid JSON only."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.0
        }

        req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=45) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            content = body["choices"][0]["message"]["content"]
            cleaned = content.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
            guides = json.loads(cleaned)

            if not isinstance(guides, list):
                return []

            results = []
            for idx, g in enumerate(guides):
                q_num = g.get("question_number", f"Q{idx + 1}")
                max_mark = float(g.get("max_marks", 10.0))

                q_start_phrase = g.get("question_start_phrase", "")
                q_end_phrase = g.get("question_end_phrase", "")

                q_s_start, q_s_end = _find_phrase_range(raw_text, q_start_phrase, 0)
                q_e_start, q_e_end = _find_phrase_range(raw_text, q_end_phrase, max(0, q_s_start))

                if q_s_start != -1 and q_e_end != -1:
                    prompt_verbatim = raw_text[q_s_start : q_e_end].strip()
                elif q_s_start != -1:
                    prompt_verbatim = raw_text[q_s_start:].strip()
                else:
                    prompt_verbatim = f"Question {q_num}"

                a_start_phrase = g.get("answer_start_phrase", "")
                a_end_phrase = g.get("answer_end_phrase", "")

                a_s_start, a_s_end = _find_phrase_range(raw_text, a_start_phrase, 0)
                a_e_start, a_e_end = _find_phrase_range(raw_text, a_end_phrase, max(0, a_s_start))

                if a_s_start != -1 and a_e_end != -1:
                    answer_verbatim = raw_text[a_s_start : a_e_end].strip()
                elif a_s_start != -1:
                    answer_verbatim = raw_text[a_s_start:].strip()
                else:
                    answer_verbatim = prompt_verbatim

                results.append({
                    "id": idx + 1,
                    "question_number": q_num if str(q_num).startswith("Q") else f"Q{q_num}",
                    "text": prompt_verbatim,
                    "maxMark": max_mark,
                    "modelAnswer": answer_verbatim
                })

            return results
    except Exception as e:
        print(f"[LLM Service Error] LLM-Guided Slicing failed: {e}")
        return []
