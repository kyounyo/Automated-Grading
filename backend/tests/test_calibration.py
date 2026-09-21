import unittest
import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models import Base, Assignment, Submission, CalibrationSet, CalibrationExample, EvaluationLog
from app.services.llm_service import format_question_few_shots


class TestCalibrationWorkflows(unittest.TestCase):

    def setUp(self):
        # Use an in-memory SQLite database for fast, isolated testing
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

        # Create a test assignment
        self.assignment = Assignment(
            id="test-assign-calib",
            title="Distributed Systems Midterm",
            course_code="CS401",
            calibration_enabled=True,
            calibration_sample_size=3,
            rubric_data=[
                {"question_number": "Q6", "text": "Explain CAP theorem", "maxMark": 10.0},
                {"question_number": "Q8", "text": "Two-phase commit protocol", "maxMark": 10.0},
                {"question_number": "Q9", "text": "Raft leader election", "maxMark": 6.0}
            ]
        )
        self.db.add(self.assignment)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(self.engine)

    def test_format_question_few_shots_question_matching(self):
        """Test that exemplars are strictly isolated and formatted by question number."""
        question_few_shots = {
            "Q6": [
                {
                    "student_text": "Consistency and Partition tolerance are preserved.",
                    "examiner_score": 9.5,
                    "max_score": 10.0,
                    "examiner_feedback": "Accurate formal definition of CAP tradeoffs.",
                    "anchor_type": "high",
                    "version": 1
                },
                {
                    "student_text": "Availability means every node always answers.",
                    "examiner_score": 5.0,
                    "max_score": 10.0,
                    "examiner_feedback": "Partial credit: missed network partition context.",
                    "anchor_type": "borderline",
                    "version": 1
                }
            ],
            "Q8": [
                {
                    "student_text": "Phase 1 prepares, Phase 2 commits or aborts.",
                    "examiner_score": 10.0,
                    "max_score": 10.0,
                    "examiner_feedback": "Concise and correct.",
                    "anchor_type": "high",
                    "version": 1
                }
            ]
        }

        output = format_question_few_shots(question_few_shots)
        self.assertIn("EXAMINER CALIBRATION BENCHMARKS FOR QUESTION Q6", output)
        self.assertIn("EXAMINER CALIBRATION BENCHMARKS FOR QUESTION Q8", output)
        self.assertNotIn("FOR QUESTION Q9", output)
        self.assertIn("[Examiner Benchmark Example 1 (High Anchor) - Score: 9.5/10.0]", output)
        self.assertIn("[Examiner Benchmark Example 2 (Borderline Anchor) - Score: 5.0/10.0]", output)
        self.assertIn("Student Response: \"Consistency and Partition tolerance are preserved.\"", output)
        self.assertIn("Examiner Justification: \"Accurate formal definition of CAP tradeoffs.\"", output)

    def test_format_question_few_shots_empty(self):
        """Test that empty or None question_few_shots returns an empty string."""
        self.assertEqual(format_question_few_shots(None), "")
        self.assertEqual(format_question_few_shots({}), "")
        self.assertEqual(format_question_few_shots({"Q6": []}), "")

    def test_question_level_calibration_set_versioning(self):
        """Test question-level CalibrationSet version incrementing independently."""
        # Q6 CalibrationSet
        cs_q6 = CalibrationSet(
            assignment_id=self.assignment.id,
            question_number="Q6",
            version=1,
            is_active=True
        )
        self.db.add(cs_q6)
        self.db.commit()

        ex1 = CalibrationExample(
            assignment_id=self.assignment.id,
            calibration_set_id=cs_q6.id,
            question_number="Q6",
            student_text="Response 1",
            examiner_score=8.0,
            max_score=10.0,
            examiner_feedback="Good explanation",
            anchor_type="borderline",
            version=1
        )
        self.db.add(ex1)
        self.db.commit()

        # Add second example to Q6 -> bumps version to 2
        cs_q6.version += 1
        ex2 = CalibrationExample(
            assignment_id=self.assignment.id,
            calibration_set_id=cs_q6.id,
            question_number="Q6",
            student_text="Response 2",
            examiner_score=10.0,
            max_score=10.0,
            examiner_feedback="Flawless answer",
            anchor_type="high",
            version=cs_q6.version
        )
        self.db.add(ex2)
        self.db.commit()

        # Q8 CalibrationSet is created independently at version 1
        cs_q8 = CalibrationSet(
            assignment_id=self.assignment.id,
            question_number="Q8",
            version=1,
            is_active=True
        )
        self.db.add(cs_q8)
        self.db.commit()

        self.assertEqual(cs_q6.version, 2)
        self.assertEqual(cs_q8.version, 1)
        self.assertEqual(len(cs_q6.examples), 2)
        self.assertEqual(len(cs_q8.examples), 0)

    def test_calibration_subsampling_and_swapping(self):
        """Test initial subsample tagging and manual sample replacement."""
        sub1 = Submission(
            id="sub-1",
            assignment_id=self.assignment.id,
            student_id="STU001",
            student_name="Alice",
            file_name="alice_sub.txt",
            raw_text="Answer 1",
            is_calibration_sample=True
        )
        sub2 = Submission(
            id="sub-2",
            assignment_id=self.assignment.id,
            student_id="STU002",
            student_name="Bob",
            file_name="bob_sub.txt",
            raw_text="Answer 2",
            is_calibration_sample=False
        )
        self.db.add_all([sub1, sub2])
        self.db.commit()

        self.assertTrue(sub1.is_calibration_sample)
        self.assertFalse(sub2.is_calibration_sample)

        # Examiner swaps sub1 out for sub2
        sub1.is_calibration_sample = False
        sub2.is_calibration_sample = True
        self.db.commit()

        self.assertFalse(sub1.is_calibration_sample)
        self.assertTrue(sub2.is_calibration_sample)

    def test_evaluation_log_technical_provenance(self):
        """Test that technical provenance is kept exclusively in EvaluationLog."""
        clean_feedback = {
            "summary": "Demonstrated solid understanding of core concepts.",
            "breakdown": [
                {"question_number": "Q6", "score_awarded": 8.0, "max_score": 10.0, "reasoning": "Clear explanation"}
            ]
        }
        sub = Submission(
            id="sub-eval-test",
            assignment_id=self.assignment.id,
            student_id="STU003",
            student_name="Charlie",
            file_name="charlie_sub.txt",
            score=8.0,
            feedback=clean_feedback
        )
        self.db.add(sub)
        self.db.commit()

        # Provenance exclusively in EvaluationLog
        eval_log = EvaluationLog(
            submission_id=sub.id,
            assignment_id=self.assignment.id,
            question_number="Q6",
            grading_mode="few_shot",
            calibration_version=2,
            calibration_examples_count=3,
            ai_score=8.0,
            confidence_score=0.92,
            latency_seconds=1.85,
            prompt_version="cot_standard-few_shot",
            model_used="google/gemini-3.1-flash-lite"
        )
        self.db.add(eval_log)
        self.db.commit()

        # Verify Submission.feedback has no calibration metadata clutter
        self.assertNotIn("calibration_version", sub.feedback)
        self.assertNotIn("grading_mode", sub.feedback)
        self.assertIn("summary", sub.feedback)

        # Verify EvaluationLog contains full technical audit provenance
        logged = self.db.query(EvaluationLog).filter(EvaluationLog.submission_id == sub.id).first()
        self.assertIsNotNone(logged)
        self.assertEqual(logged.grading_mode, "few_shot")
        self.assertEqual(logged.calibration_version, 2)
        self.assertEqual(logged.calibration_examples_count, 3)

    def test_import_graded_calibration_data(self):
        """Test importing already-graded student submissions from a CSV file."""
        import os
        import tempfile
        from app.services.calibration_importer import import_graded_calibration_data

        csv_content = (
            "Student ID,Student Name,Question,Student Response,Lecturer Score,Max Score,Feedback,Anchor Type\n"
            "STU101,Alice,Q6,Virtual memory enables large processes.,9.0,10.0,Excellent explanation,high\n"
            "STU102,Bob,Q6,Virtual memory moves pages to disk.,5.5,10.0,Partial credit on paging,borderline\n"
            "STU103,Charlie,Q6,Virtual memory is more RAM chips.,1.5,10.0,Fundamental misunderstanding,low\n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
            f.write(csv_content)
            temp_csv = f.name

        try:
            res = import_graded_calibration_data(
                file_path=temp_csv,
                assignment_id=self.assignment.id,
                original_filename="graded_test.csv",
                db=self.db
            )
            self.assertEqual(res["imported_examples_count"], 3)
            self.assertEqual(res["imported_students_count"], 3)
            self.assertIn("Q6", res["questions_updated"])

            # Verify Submissions created
            subs = self.db.query(Submission).filter(Submission.assignment_id == self.assignment.id).all()
            self.assertEqual(len(subs), 3)
            for s in subs:
                self.assertTrue(s.is_calibration_sample)
                self.assertEqual(s.status, "graded")

            # Verify CalibrationExamples created
            examples = self.db.query(CalibrationExample).filter(CalibrationExample.assignment_id == self.assignment.id).all()
            self.assertEqual(len(examples), 3)
            anchors = {ex.anchor_type for ex in examples}
            self.assertSetEqual(anchors, {"high", "borderline", "low"})
        finally:
            if os.path.exists(temp_csv):
                os.remove(temp_csv)

    def test_calibration_and_ungraded_overlap_preservation(self):
        """Verify that uploading ungraded submissions with overlapping student IDs does NOT wipe out calibration marks."""
        import tempfile
        import os
        from app.services.calibration_importer import import_graded_calibration_data
        from app.routes.uploads import clean_student_id

        # 1. Import a calibrated student
        cal_csv = (
            "Student ID,Student Name,Question,Student Response,Lecturer Score,Max Score,Feedback\n"
            "31107494,Jane Doe,Q6,Detailed in situ gelling mechanism.,8.5,10.0,Very good.\n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
            f.write(cal_csv)
            cal_file = f.name

        try:
            import_graded_calibration_data(
                file_path=cal_file,
                assignment_id=self.assignment.id,
                original_filename="cal.csv",
                db=self.db
            )
        finally:
            if os.path.exists(cal_file):
                os.remove(cal_file)

        sub = self.db.query(Submission).filter(
            Submission.assignment_id == self.assignment.id,
            Submission.student_id == "31107494"
        ).first()
        self.assertIsNotNone(sub)
        self.assertEqual(sub.score, 8.5)
        self.assertEqual(sub.status, "graded")
        self.assertTrue(sub.is_calibration_sample)

        # 2. Simulate ungraded bulk upload containing the same student ID (even with .0 or case variation)
        from sqlalchemy import func
        s_id = clean_student_id("31107494.0")
        existing_sub = self.db.query(Submission).filter(
            Submission.assignment_id == self.assignment.id,
            (Submission.student_id == s_id) | (func.lower(Submission.student_id) == s_id.lower())
        ).first()

        self.assertIsNotNone(existing_sub)
        # Verify it identifies the SAME student and retains calibration marks
        self.assertEqual(existing_sub.id, sub.id)
        self.assertEqual(existing_sub.score, 8.5)
        self.assertEqual(existing_sub.status, "graded")
        self.assertTrue(existing_sub.is_calibration_sample)

    def test_exact_user_format_calibration_parsing(self):
        """Test parsing the exact user format:
        ID Number | student_gma | student_nam | question_no | Response | Score
        """
        import tempfile
        import os
        from app.services.calibration_importer import import_graded_calibration_data
        from app.services.flexible_excel_parser import parse_flexible_submissions

        user_cal_csv = (
            "ID Number,student_gma,student_nam,question_no,Response,Score\n"
            "31107494,,,6,A) Advantage: increased solubility,4\n"
            "31109551,,,6,(a) ADVANTAGE: stable at room temp,6\n"
            "31107494,,,8,a) Disagree because precipitation occurs,5\n"
            "31109551,,,8,(a) Lyophilization preserves structure,4\n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
            f.write(user_cal_csv)
            cal_file = f.name

        try:
            res = import_graded_calibration_data(
                file_path=cal_file,
                assignment_id=self.assignment.id,
                original_filename="user_calibration.csv",
                db=self.db
            )
            self.assertEqual(res["imported_examples_count"], 4)
            self.assertEqual(res["imported_students_count"], 2)
        finally:
            if os.path.exists(cal_file):
                os.remove(cal_file)

        # 1. Verify Student 31107494
        sub_1 = self.db.query(Submission).filter(
            Submission.assignment_id == self.assignment.id,
            Submission.student_id == "31107494"
        ).first()
        self.assertIsNotNone(sub_1)
        self.assertEqual(sub_1.score, 9.0)  # 4 + 5 = 9
        self.assertEqual(sub_1.status, "graded")
        self.assertTrue(sub_1.is_calibration_sample)
        self.assertEqual(sub_1.confidence_score, 1.0)
        self.assertIn("Question Q6", sub_1.raw_text)
        self.assertIn("Question Q8", sub_1.raw_text)
        self.assertEqual(len(sub_1.feedback["breakdown"]), 2)

        # 2. Verify Student 31109551
        sub_2 = self.db.query(Submission).filter(
            Submission.assignment_id == self.assignment.id,
            Submission.student_id == "31109551"
        ).first()
        self.assertIsNotNone(sub_2)
        self.assertEqual(sub_2.score, 10.0)  # 6 + 4 = 10
        self.assertEqual(sub_2.status, "graded")
        self.assertTrue(sub_2.is_calibration_sample)

        # 3. Verify Calibration Examples
        q6_examples = self.db.query(CalibrationExample).filter(
            CalibrationExample.assignment_id == self.assignment.id,
            CalibrationExample.question_number == "Q6"
        ).all()
        self.assertEqual(len(q6_examples), 2)
        q6_scores = {ex.examiner_score for ex in q6_examples}
        self.assertEqual(q6_scores, {4.0, 6.0})

        q8_examples = self.db.query(CalibrationExample).filter(
            CalibrationExample.assignment_id == self.assignment.id,
            CalibrationExample.question_number == "Q8"
        ).all()
        self.assertEqual(len(q8_examples), 2)
        q8_scores = {ex.examiner_score for ex in q8_examples}
        self.assertEqual(q8_scores, {5.0, 4.0})

        # 4. Now parse the ungraded dataset with the same format (without Score)
        ungraded_csv = (
            "ID Number,student_gma,student_nam,question_no,Response\n"
            "31107494,,,6,A) Advantage: increased solubility\n"
            "31109551,,,6,(a) ADVANTAGE: stable at room temp\n"
            "31107494,,,8,a) Disagree because precipitation occurs\n"
            "31109551,,,8,(a) Lyophilization preserves structure\n"
            "31101234,,,6,Unrelated response\n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
            f.write(ungraded_csv)
            ungraded_file = f.name

        try:
            parsed_ungraded = parse_flexible_submissions(ungraded_file)
            self.assertEqual(len(parsed_ungraded), 3)  # 3 distinct students
            student_ids = {s["student_id"] for s in parsed_ungraded}
            self.assertEqual(student_ids, {"31107494", "31109551", "31101234"})
        finally:
            if os.path.exists(ungraded_file):
                os.remove(ungraded_file)


if __name__ == "__main__":
    unittest.main()


