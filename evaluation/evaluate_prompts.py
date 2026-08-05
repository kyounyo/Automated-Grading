import os
import re
import pandas as pd
import pingouin as pg
import sys
import json

script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.abspath(os.path.join(script_dir, "../ai-pipeline")))

from prompts import PROMPTS

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

# Load environment variables (explicitly from the script's directory)
script_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(dotenv_path=os.path.join(script_dir, '.env'))

client = None
MODEL_NAME = None

api_key = os.getenv("OPENROUTER_API_KEY")
if not api_key:
    print("No OPENROUTER_API_KEY found")
    exit()

client = OpenAI(
    api_key=api_key,
    base_url="https://openrouter.ai/api/v1"
)
MODEL_NAME = "google/gemini-3.1-flash-lite"

def extract_score(text):
    """Extracts the final score by parsing JSON."""
    try:
        clean_text = text.strip()
        # Handle DeepSeek <think> reasoning tags
        think_match = re.search(r'<think>.*?</think>', clean_text, flags=re.DOTALL)
        if think_match:
            clean_text = clean_text.replace(think_match.group(0), "").strip()
            
        if clean_text.startswith("```json"): clean_text = clean_text[7:]
        if clean_text.startswith("```"): clean_text = clean_text[3:]
        if clean_text.endswith("```"): clean_text = clean_text[:-3]
        
        data = json.loads(clean_text)
        return float(data.get("total_score", 0))
    except Exception as e:
        print(f"JSON parsing error: {e}")
        return None

def grade_submission(rubric, question, max_score, student_answer, prompt_template):
    """Calls the LLM to grade the submission based on the prompt template."""
    formatted_prompt = prompt_template.format(
        rubric=rubric,
        question=question,
        max_score=max_score,
        student_answer=student_answer
    )
    
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "You are a helpful grading assistant."},
                {"role": "user", "content": formatted_prompt}
            ],
            temperature=0.0,
            max_tokens=8000
        )
        ai_response_text = response.choices[0].message.content
        if ai_response_text is None:
            print("  [Warning] The model returned an empty response (likely ran out of tokens while reasoning).")
            return None, ""
            
        score = extract_score(ai_response_text)
        return score, ai_response_text
    except Exception as e:
        print(f"Error calling API: {e}")
        return None, str(e)

def main():
    print("Loading datasets...")
    # Read the dataset (relative to this script's directory)
    dataset_path = os.path.join(script_dir, "Dataset for prompt.xlsx")
    
    try:
        df_questions = pd.read_excel(dataset_path, sheet_name="Question & Answer Scheme")
        df_responses = pd.read_excel(dataset_path, sheet_name="Response")
        df_questions.columns = df_questions.columns.str.strip()
        df_responses.columns = df_responses.columns.str.strip()
    except Exception as e:
        print(f"Could not read dataset: {e}")
        return

    # ----- ADJUSTABLE TEST SETTING -----
    # Set this to the number of students you want to test per question (e.g., 5)
    # Set to None if you want to run the full dataset.
    STUDENTS_PER_QUESTION = 8
    if STUDENTS_PER_QUESTION:
        df_responses = df_responses.groupby('question_no').head(STUDENTS_PER_QUESTION).copy()

    # Dictionary to store all the parsed grades for ICC comparison later
    results_data = []
    json_outputs_data = []
    graded_response_ids = set()
    
    if os.path.exists(os.path.join(script_dir, "raw_grading_results.csv")):
        existing_df = pd.read_csv(os.path.join(script_dir, "raw_grading_results.csv"))
        results_data = existing_df.to_dict('records')
        graded_response_ids = set(existing_df['response_id'].tolist())
        print(f"Resuming progress: Found {len(set(existing_df[existing_df['rater'] != 'Human']['response_id']))} already graded AI responses.")

    print(f"Evaluating {len(df_responses)} responses with chain_of_thought strategy...")
    
    for index, row in df_responses.iterrows():
        response_id = row['ID Number']
        # Convert to string and remove any 'Q' prefix to safely match both dataset styles
        question_no = str(row['question_no']).strip().replace('Q', '')

        student_answer = row['Response']
        human_grade = float(row['grade'])
        
        # Get the corresponding question and rubric
        # We also convert the question_no in the df_questions to string and strip 'Q'
        matched_questions = df_questions[df_questions['question_no'].astype(str).str.strip().str.replace('Q', '') == question_no]
        if matched_questions.empty:
            print(f"  [Warning] Question {question_no} not found in Question sheet. Skipping response {response_id}.")
            continue
            
        q_row = matched_questions.iloc[0]
        question_text = q_row['question']
        rubric = q_row['answer']
        max_score = q_row['max_mark']
        
        # Store human grade
        results_data.append({
            'response_id': response_id,
            'rater': 'Human',
            'score': human_grade
        })
        
        break_outer = False
        # Test each prompting strategy
        for strategy, prompt_template in PROMPTS.items():
            print(f"Grading response {response_id} with {strategy}...")
            ai_score, ai_text = grade_submission(
                rubric=rubric,
                question=question_text,
                max_score=max_score,
                student_answer=student_answer,
                prompt_template=prompt_template
            )
            
            # Save the JSON details for review
            try:
                clean_text = str(ai_text).strip()
                think_match = re.search(r'<think>.*?</think>', clean_text, flags=re.DOTALL)
                if think_match:
                    clean_text = clean_text.replace(think_match.group(0), "").strip()
                    
                if clean_text.startswith("```json"): clean_text = clean_text[7:]
                if clean_text.startswith("```"): clean_text = clean_text[3:]
                if clean_text.endswith("```"): clean_text = clean_text[:-3]
                parsed_json = json.loads(clean_text)
                
                # Try to extract the separate reasoning field if OpenRouter parsed it
                # Note: ai_text doesn't have it, but we could pass it if we wanted to.
                # For now, just save the parsed evaluation.
                
                json_outputs_data.append({
                    "response_id": response_id,
                    "question_no": question_no,
                    "strategy": strategy,
                    "human_score": human_grade,
                    "ai_evaluation": parsed_json
                })
            except Exception as e:
                pass

            # If the AI failed to format properly, we might get None
            if ai_score is None:
                print(f"  [Warning] Failed to extract score for {strategy}. Raw text: {str(ai_text)[:100]}...")
                if "429" in str(ai_text) or "rate limit" in str(ai_text).lower() or "too many requests" in str(ai_text).lower():
                    print("Rate limit reached. Stopping evaluation.")
                    break_outer = True
                    break
                ai_score = 0.0 # Defaulting to 0 for statistical completeness, though not ideal
                
            results_data.append({
                'response_id': response_id,
                'rater': f'AI_{strategy}',
                'score': float(ai_score)
            })

        if break_outer:
            break

        # Save raw results continuously to avoid losing data on API crash
        df_results = pd.DataFrame(results_data)
        df_results.to_csv("raw_grading_results.csv", index=False)
        
    df_results = pd.DataFrame(results_data)
    print("\nSaved raw grades to raw_grading_results.csv")

    with open(os.path.join(script_dir, "ai_json_responses32(M).json"), "w") as f:
        json.dump(json_outputs_data, f, indent=4)
    print("Saved detailed AI reasoning to ai_json_responses.json")

    # Calculate ICC for each AI strategy against the Human
    print("\n--- Intraclass Correlation Coefficient (ICC) Results ---")
    
    strategies = [s for s in PROMPTS.keys()]
    icc_summary = []
    
    for strategy in strategies:
        # Filter data for just Human and this AI Strategy
        df_comparison = df_results[df_results['rater'].isin(['Human', f'AI_{strategy}'])]
        
        # Calculate ICC using pingouin
        # ICC2: Two-way random effects, absolute agreement
        try:
            icc = pg.intraclass_corr(
                data=df_comparison, 
                targets='response_id', 
                raters='rater', 
                ratings='score'
            )
            # Get the ICC(A,1) (Two-way random, absolute agreement, single rater) value
            icc_value = icc.set_index('Type').loc['ICC(A,1)', 'ICC']
            icc_summary.append({'Strategy': strategy, 'ICC': icc_value})
            print(f"{strategy.upper()} ICC: {icc_value:.4f}")
        except Exception as e:
            print(f"Could not calculate ICC for {strategy}: {e}")
            
    # Save ICC Summary
    df_icc_summary = pd.DataFrame(icc_summary)
    df_icc_summary.to_csv(os.path.join(script_dir, "icc_summary_results.csv"), index=False)
    print("\nSaved ICC Summary to icc_summary_results.csv")

if __name__ == "__main__":
    if not client:
        print("Please set your API KEY in the .env file before running.")
    else:
        main()
