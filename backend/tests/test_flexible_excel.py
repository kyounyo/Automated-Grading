import os
import tempfile
import unittest
import pandas as pd
from app.services.flexible_excel_parser import (
    detect_header_row,
    compute_column_confidence,
    resolve_schema_mapping,
    parse_flexible_rubric,
    parse_flexible_submissions,
    RUBRIC_ALIASES,
    SUBMISSION_ALIASES
)
from app.services.document_parser import parse_excel_rubric, parse_excel_rows


class TestTemplateTolerantExcelParser(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_temp_csv(self, content_str: str) -> str:
        file_path = os.path.join(self.temp_dir.name, f"test_{os.urandom(4).hex()}.csv")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content_str)
        return file_path

    def _create_temp_xlsx(self, df: pd.DataFrame) -> str:
        file_path = os.path.join(self.temp_dir.name, f"test_{os.urandom(4).hex()}.xlsx")
        df.to_excel(file_path, index=False)
        return file_path

    # =========================================================================
    # 1. STANDARD TEMPLATE BACKWARD COMPATIBILITY
    # =========================================================================
    def test_standard_rubric_template(self):
        csv_data = (
            "question_n,question,answer,max_mark\n"
            "1,Explain microservices architecture in detail,Microservices divide applications into discrete services,10\n"
            "2,What is RAG pipeline?,Retrieval Augmented Generation combines search with LLM generation,15\n"
        )
        file_path = self._create_temp_csv(csv_data)
        parsed = parse_excel_rubric(file_path)

        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0]["question_number"], "Q1")
        self.assertEqual(parsed[0]["maxMark"], 10.0)
        self.assertIn("microservices", parsed[0]["text"].lower())
        self.assertEqual(parsed[1]["question_number"], "Q2")
        self.assertEqual(parsed[1]["maxMark"], 15.0)

    def test_standard_submissions_template(self):
        csv_data = (
            "Student_ID,student_name,student_gmail,question_no,Response\n"
            "STU101,Alice Smith,alice@test.edu,Q1,Microservices allow independent deployment and scaling.\n"
            "STU101,Alice Smith,alice@test.edu,Q2,RAG retrieves relevant chunks and feeds them into LLM prompt.\n"
            "STU102,Bob Jones,bob@test.edu,Q1,Monoliths are single codebase while microservices are decentralized.\n"
        )
        file_path = self._create_temp_csv(csv_data)
        parsed = parse_excel_rows(file_path)

        self.assertEqual(len(parsed), 2)
        stu101 = next(p for p in parsed if p["student_id"] == "STU101")
        self.assertEqual(stu101["student_name"], "Alice Smith")
        self.assertEqual(stu101["student_email"], "alice@test.edu")
        self.assertIn("Question Q1:", stu101["text"])
        self.assertIn("Question Q2:", stu101["text"])

    # =========================================================================
    # 2. HEADER DETECTION WITH OFFSET BANNER / METADATA ROWS
    # =========================================================================
    def test_header_detection_with_banner(self):
        csv_data = (
            "Monash University Department of Software Engineering\n"
            "FIT3164 - Advanced Automated Grading Assessment Rubric\n"
            "Semester 2 - 2026 Internal Scheme\n"
            "\n"
            "Item,Prompt,Exemplar,Points\n"
            "Q1,Describe CAP theorem,Consistency Availability Partition Tolerance,10\n"
            "Q2,Explain Two Phase Commit,Coordinator prepares and commits transactions,10\n"
        )
        file_path = self._create_temp_csv(csv_data)
        header_idx = detect_header_row(file_path)
        self.assertEqual(header_idx, 4)

        parsed = parse_excel_rubric(file_path)
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0]["question_number"], "Q1")
        self.assertEqual(parsed[0]["maxMark"], 10.0)
        self.assertIn("CAP theorem", parsed[0]["text"])

    # =========================================================================
    # 3. ALTERNATIVE COLUMN ALIASES (.XLSX & .CSV)
    # =========================================================================
    def test_non_standard_rubric_aliases_xlsx(self):
        df = pd.DataFrame([
            {"Task Label": "1", "Assessment Criteria": "Critique database normalization forms", "Marking Guide": "1NF requires atomic values and 2NF removes partial dependencies", "Allocated Marks": 20},
            {"Task Label": "2", "Assessment Criteria": "Compare B-tree vs LSM-tree indexing", "Marking Guide": "B-trees optimize for reads while LSM optimizes for sequential writes", "Allocated Marks": 25}
        ])
        file_path = self._create_temp_xlsx(df)
        parsed = parse_excel_rubric(file_path)

        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0]["question_number"], "Q1")
        self.assertEqual(parsed[0]["maxMark"], 20.0)
        self.assertIn("database normalization", parsed[0]["text"])
        self.assertEqual(parsed[1]["maxMark"], 25.0)

    def test_non_standard_submission_aliases_csv(self):
        csv_data = (
            "Candidate Index,Candidate Name,Contact Email,Question Number,Student Work\n"
            "23001234,Charlie Brown,charlie@monash.edu,Q1,Database normalization reduces anomalies.\n"
            "23001234,Charlie Brown,charlie@monash.edu,Q2,B-trees use balanced tree node hierarchy.\n"
        )
        file_path = self._create_temp_csv(csv_data)
        parsed = parse_excel_rows(file_path)

        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["student_id"], "23001234")
        self.assertEqual(parsed[0]["student_name"], "Charlie Brown")
        self.assertEqual(parsed[0]["student_email"], "charlie@monash.edu")
        self.assertIn("normalization", parsed[0]["text"])

    # =========================================================================
    # 4. DISAMBIGUATION & WEIGHTAGE VS MAX MARKS
    # =========================================================================
    def test_weightage_percentage_exclusion(self):
        """Percentages (e.g. 20%) should not be accepted as absolute max marks."""
        conf_percent = compute_column_confidence("weightage", ["20%", "30%", "50%"], "max_mark", RUBRIC_ALIASES)
        conf_absolute = compute_column_confidence("marks", ["10", "15", "20"], "max_mark", RUBRIC_ALIASES)
        self.assertGreater(conf_absolute, conf_percent)

    def test_id_vs_question_number_content_disambiguation(self):
        """Matriculation ID (23001234) vs Q-number (Q1, Q2) disambiguation."""
        id_samples = ["23001234", "23001235", "23001236"]
        q_samples = ["Q1", "Q2", "Q3"]

        conf_id_as_stu = compute_column_confidence("identifier", id_samples, "student_id", SUBMISSION_ALIASES)
        conf_id_as_q = compute_column_confidence("identifier", id_samples, "question_number", SUBMISSION_ALIASES)
        self.assertGreater(conf_id_as_stu, conf_id_as_q)

        conf_q_as_q = compute_column_confidence("identifier", q_samples, "question_number", SUBMISSION_ALIASES)
        conf_q_as_stu = compute_column_confidence("identifier", q_samples, "student_id", SUBMISSION_ALIASES)
        self.assertGreater(conf_q_as_q, conf_q_as_stu)

    # =========================================================================
    # 5. REJECTION OF INVALID / NONSENSE SCHEMAS (FALSE AUTOMATIC MAPPING TEST)
    # =========================================================================
    def test_invalid_schema_rejection(self):
        """Random unformatted data without required fields should fail validity."""
        csv_data = (
            "Random_Alpha,Random_Beta,Random_Gamma\n"
            "Apple,Banana,Cherry\n"
            "Dog,Elephant,Fox\n"
        )
        file_path = self._create_temp_csv(csv_data)
        df = pd.read_csv(file_path)
        mapping, conf, is_valid = resolve_schema_mapping(df, "rubric")
        self.assertLess(conf, 0.70)


if __name__ == "__main__":
    unittest.main()
