import sys, json, time
sys.path.insert(0, r'C:\Users\Owner\OneDrive\Desktop\Final Year Project\Automated-Grading\backend')
from dotenv import load_dotenv
load_dotenv()
from app.services import llm_service as svc
import pandas as pd

df = pd.read_excel('Dataset for prompt.xlsx', sheet_name='Question & Answer Scheme')
df['q_clean'] = df['question_no'].astype(str).str.strip().str.replace('Q','')

model = 'nvidia/nemotron-3-super-120b-a12b'
QUESTIONS = ['6', '8', '9', '22']

results = {}
for q in QUESTIONS:
    row = df[df['q_clean'] == q].iloc[0]
    question_text = row['question']
    rubric_text = row['answer']
    max_score = float(row['max_mark'])
    spec = None
    for attempt in range(3):
        spec = svc.call_rubric_interpreter_agent(question_text, rubric_text, max_score, model)
        if spec:
            break
        print(f"Q{q} attempt {attempt+1} failed, retrying...")
        time.sleep(5)
    if spec:
        is_valid, issues, flags = svc._validate_grading_spec(spec)
        results[q] = {'spec': spec, 'is_valid': is_valid, 'issues': issues, 'review_flags': flags}
        print(f"Q{q} / Nemotron: type={spec.get('question_type')} valid={is_valid} issues={issues} flags={len(flags)}")
    else:
        results[q] = {'spec': None, 'error': 'interpreter call failed after retries'}
        print(f"Q{q} / Nemotron: FAILED")

with open('audit_nemotron_output.json', 'w', encoding='utf-8') as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print("Done -- dumped to audit_nemotron_output.json")
