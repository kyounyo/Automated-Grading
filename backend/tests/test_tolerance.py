import unittest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models import Base, Assignment, Submission
from app.services.confidence import evaluate_discrepancy, evaluate_confidence_and_status
from app.routes.assignments import ALLOWED_TOLERANCES


class TestToleranceEngine(unittest.TestCase):

    def test_evaluate_discrepancy_zero_tolerance(self):
        """0% Strict tolerance: strictly 0 difference permitted."""
        # Exact match passes
        res_zero = evaluate_discrepancy(primary_score=8.0, auditor_score=8.0, max_score=10.0, tolerance_rate=0.0)
        self.assertFalse(res_zero["is_conflict"])
        self.assertEqual(res_zero["allowed_difference"], 0.0)
        self.assertEqual(res_zero["difference"], 0.0)

        # Delta = 0.1 must trigger conflict (not 0.5 or 0.49)
        res_diff = evaluate_discrepancy(primary_score=8.1, auditor_score=8.0, max_score=10.0, tolerance_rate=0.0)
        self.assertTrue(res_diff["is_conflict"])
        self.assertEqual(res_diff["allowed_difference"], 0.0)
        self.assertAlmostEqual(res_diff["difference"], 0.1, places=3)

    def test_evaluate_discrepancy_ten_percent(self):
        """10% Balanced tolerance on 10-mark question: Delta <= 1.0 passes, Delta = 1.01 flags."""
        # Delta = 1.0 passes
        res_pass = evaluate_discrepancy(primary_score=7.0, auditor_score=8.0, max_score=10.0, tolerance_rate=0.10)
        self.assertFalse(res_pass["is_conflict"])
        self.assertEqual(res_pass["allowed_difference"], 1.0)
        self.assertEqual(res_pass["difference"], 1.0)

        # Delta = 1.01 triggers conflict
        res_fail = evaluate_discrepancy(primary_score=6.99, auditor_score=8.0, max_score=10.0, tolerance_rate=0.10)
        self.assertTrue(res_fail["is_conflict"])

    def test_evaluate_discrepancy_twenty_percent(self):
        """20% High automation tolerance on 10-mark question: Delta <= 2.0 passes, Delta = 2.01 flags."""
        # Delta = 2.0 passes
        res_pass = evaluate_discrepancy(primary_score=6.0, auditor_score=8.0, max_score=10.0, tolerance_rate=0.20)
        self.assertFalse(res_pass["is_conflict"])
        self.assertEqual(res_pass["allowed_difference"], 2.0)
        self.assertEqual(res_pass["difference"], 2.0)

        # Delta = 2.01 triggers conflict
        res_fail = evaluate_discrepancy(primary_score=5.99, auditor_score=8.0, max_score=10.0, tolerance_rate=0.20)
        self.assertTrue(res_fail["is_conflict"])

    def test_evaluate_discrepancy_absolute_two_mark_cap(self):
        """Absolute 2.0-mark cap test: 10% of 25 is 2.5, but capped at 2.0 marks."""
        # Delta = 2.0 passes
        res_pass = evaluate_discrepancy(primary_score=18.0, auditor_score=20.0, max_score=25.0, tolerance_rate=0.10, absolute_cap=2.0)
        self.assertFalse(res_pass["is_conflict"])
        self.assertEqual(res_pass["allowed_difference"], 2.0)
        self.assertTrue(res_pass["absolute_cap_applied"])

        # Delta = 2.01 triggers conflict
        res_fail = evaluate_discrepancy(primary_score=17.99, auditor_score=20.0, max_score=25.0, tolerance_rate=0.10, absolute_cap=2.0)
        self.assertTrue(res_fail["is_conflict"])

        # Delta = 2.5 (uncapped 10%) triggers conflict due to 2.0 cap
        res_cap_fail = evaluate_discrepancy(primary_score=17.5, auditor_score=20.0, max_score=25.0, tolerance_rate=0.10, absolute_cap=2.0)
        self.assertTrue(res_cap_fail["is_conflict"])
        self.assertTrue(res_cap_fail["absolute_cap_applied"])

    def test_identical_and_zero_scores(self):
        """Identical scores (7 vs 7) and zeros (0 vs 0) must pass across all tolerances."""
        for tol in [0.0, 0.10, 0.20]:
            res_seven = evaluate_discrepancy(primary_score=7.0, auditor_score=7.0, max_score=10.0, tolerance_rate=tol)
            self.assertFalse(res_seven["is_conflict"])

            res_zero = evaluate_discrepancy(primary_score=0.0, auditor_score=0.0, max_score=10.0, tolerance_rate=tol)
            self.assertFalse(res_zero["is_conflict"])

    def test_decimal_scores(self):
        """Test realistic partial decimal point scoring."""
        # 6.5 vs 7.5 (Delta = 1.0) on 10 pts with 10% tolerance -> passes
        res_dec_pass = evaluate_discrepancy(primary_score=6.5, auditor_score=7.5, max_score=10.0, tolerance_rate=0.10)
        self.assertFalse(res_dec_pass["is_conflict"])

        # 6.4 vs 7.5 (Delta = 1.1) on 10 pts with 10% tolerance -> fails
        res_dec_fail = evaluate_discrepancy(primary_score=6.4, auditor_score=7.5, max_score=10.0, tolerance_rate=0.10)
        self.assertTrue(res_dec_fail["is_conflict"])

    def test_evaluate_confidence_and_status_audit_trail(self):
        """Ensures evaluate_confidence_and_status outputs full discrepancy_audit trail."""
        llm_result = {
            "overall_score": 18.0,
            "feedback": {
                "breakdown": [
                    {"question_number": "Q6", "score_awarded": 9.0, "max_score": 10.0},
                    {"question_number": "Q8", "score_awarded": 9.0, "max_score": 10.0}
                ]
            },
            "multi_agent_audit": {
                "auditor_passed": True,
                "auditor_score": 17.5,
                "score_discrepancy": 0.5,
                "auditor_breakdown": [
                    {"question_number": "Q6", "auditor_score": 9.0},
                    {"question_number": "Q8", "auditor_score": 8.5}
                ]
            }
        }
        raw_text = (
            "Detailed scientific response explaining polymer microspheres and protein stability. "
            "The microsphere structure provides controlled release over time and degrades safely in vivo without needing surgical removal. "
            "Protein tertiary structures are stabilized by formulation buffers to prevent aggregation and loss of therapeutic efficacy."
        )
        
        # Test 10% tolerance: Delta is 0.5 on Q8 (allowed 1.0), so status is graded
        conf_res = evaluate_confidence_and_status(
            llm_result=llm_result,
            raw_text=raw_text,
            total_max_score=20.0,
            tolerance_rate=0.10
        )
        self.assertEqual(conf_res["status"], "graded")
        self.assertIn("discrepancy_audit", conf_res)
        audit = conf_res["discrepancy_audit"]
        self.assertEqual(audit["tolerance_rate"], 0.10)
        self.assertEqual(audit["resolution_status"], "reconciled_auto_approved")
        self.assertEqual(len(audit["conflicting_questions"]), 0)

        # Test 0% tolerance: Delta is 0.5 on Q8 (allowed 0.0), so status must be flagged
        conf_res_zero = evaluate_confidence_and_status(
            llm_result=llm_result,
            raw_text=raw_text,
            total_max_score=20.0,
            tolerance_rate=0.0
        )
        self.assertEqual(conf_res_zero["status"], "flagged")
        audit_zero = conf_res_zero["discrepancy_audit"]
        self.assertEqual(audit_zero["tolerance_rate"], 0.0)
        self.assertEqual(audit_zero["resolution_status"], "escalated_lecturer_review")
        self.assertTrue(len(audit_zero["conflicting_questions"]) > 0)
        self.assertTrue(any("Multi-Agent Discrepancy" in r for r in conf_res_zero["flag_reasons"]))


class TestToleranceAssignmentLifecycle(unittest.TestCase):

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

    def test_allowed_tolerances_set(self):
        """Confirms discrete allowed tolerances."""
        self.assertEqual(ALLOWED_TOLERANCES, {0.0, 0.10, 0.20})

    def test_assignment_model_default(self):
        """Assignment defaults to 0.10 tolerance."""
        assign = Assignment(
            id="test-assign-tol",
            title="Pharmaceutics",
            course_code="PHAR201"
        )
        self.db.add(assign)
        self.db.commit()
        self.db.refresh(assign)
        self.assertEqual(assign.tolerance_rate, 0.10)
        self.assertIsNone(assign.grading_started_at)

    def test_tolerance_unlocked_when_submissions_uploaded_pending(self):
        """Tolerance CAN be changed when submissions are uploaded but grading has not started."""
        assign = Assignment(
            id="test-assign-pending-subs",
            title="Biopharmaceutics",
            course_code="PHA301",
            tolerance_rate=0.10,
            grading_started_at=None
        )
        self.db.add(assign)
        # Add 50 uploaded pending submissions
        for i in range(50):
            sub = Submission(
                id=f"sub-{i}",
                assignment_id=assign.id,
                student_id=f"stu-{i}",
                file_name=f"paper_{i}.pdf",
                status="pending"
            )
            self.db.add(sub)
        self.db.commit()

        # Check lock condition
        has_grading_commenced = (assign.grading_started_at is not None) or (
            self.db.query(Submission).filter(
                Submission.assignment_id == assign.id,
                Submission.status.in_(["graded", "flagged", "grading", "extracting_answers"])
            ).count() > 0
        )
        self.assertFalse(has_grading_commenced)

        # Lecturer changes tolerance to 0% before grading starts -> permitted
        assign.tolerance_rate = 0.0
        self.db.commit()
        self.assertEqual(assign.tolerance_rate, 0.0)

    def test_tolerance_adjustable_by_lecturer_after_grading(self):
        """Tolerance remains adjustable by lecturer anytime for iterative review/re-grading."""
        import datetime
        assign = Assignment(
            id="test-assign-adjustable",
            title="Biopharmaceutics",
            course_code="PHA301",
            tolerance_rate=0.10,
            grading_started_at=datetime.datetime.utcnow()
        )
        self.db.add(assign)
        sub = Submission(
            id="sub-graded-1",
            assignment_id=assign.id,
            student_id="stu-1",
            file_name="paper.pdf",
            status="graded"
        )
        self.db.add(sub)
        self.db.commit()

        # Lecturer can adjust tolerance anytime (e.g. to 0.20)
        assign.tolerance_rate = 0.20
        self.db.commit()
        self.assertEqual(assign.tolerance_rate, 0.20)


if __name__ == '__main__':
    unittest.main()
