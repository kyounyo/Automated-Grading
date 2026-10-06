import sys, json, time
sys.path.insert(0, r'C:\Users\Owner\OneDrive\Desktop\Final Year Project\Automated-Grading\backend')
from dotenv import load_dotenv
load_dotenv()
from app.services import llm_service as svc
import pandas as pd

df = pd.read_excel('Dataset for prompt.xlsx', sheet_name='Question & Answer Scheme')
df['q_clean'] = df['question_no'].astype(str).str.strip().str.replace('Q','')
row = df[df['q_clean']=='9'].iloc[0]
question_text = row['question']
rubric_text = row['answer']
max_score = float(row['max_mark'])

model = 'nvidia/nemotron-3-super-120b-a12b'

spec = None
for attempt in range(3):
    spec = svc.interpret_rubric_spec(question_text, rubric_text, max_score, model=model)
    if spec:
        break
    time.sleep(5)

print('--- ITEMS (as given to the extraction prompt) ---')
for it in spec['items']:
    print(repr(it['label']))

student_text = ("Pyrantel chocolate squares: 1 square=10kg. Melissa (30 years old and weighs 64kg) : "
                 "64kg requires 6 squares. (64/10=6.4) Tony, Melissa's husband (32 years old and weighs 73kg) : "
                 "73kg requires 7 squares. (73/10=7.3) Bella, their first child (12 years old, weighs 39kg) : "
                 "39kg requires 4 squares. (39/10=3.9) approximated to 4 squares. Bobby, their youngest child "
                 "(7 years old, weighs 23kg) : 23kg requires 2 squares. (23/10=2.3)")

prompt = svc._build_calculation_extraction_prompt_dynamic(student_text, spec['items'], question_text)
messages = [
    {"role": "system", "content": "You are a precise evidence-extraction engine for academic grading. Always respond strictly in valid JSON format. Do not calculate or report any score."},
    {"role": "user", "content": prompt},
]
extraction_res = None
for attempt in range(3):
    extraction_res = svc._call_openrouter_api(messages, model, temperature=0.0)
    if extraction_res:
        break
    time.sleep(5)

print()
print('--- RAW EXTRACTION RESULT (labels as returned by the extraction call) ---')
for e in extraction_res.get('extractions', []):
    print(json.dumps(e, ensure_ascii=False))
