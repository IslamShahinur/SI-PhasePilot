"""
tests/test_workflow.py — table-driven tests for workflow.py functions.
"""
import pytest
from workflow import (
    task_name_for_attempt,
    review_name_for_attempt,
    all_task_names,
    all_review_names,
    can_pick_task,
    can_pick_review,
    next_phase_status,
    can_mark_completed,
    can_mark_review,
    can_new_phase,
    recommendation,
    MAX_ATTEMPT_NO,
)


# ===== SECTION: Attempt ladder =====

class TestAttemptLadder:
    def test_task_name_for_attempt(self):
        cases = [
            (0, "No Task"),
            (1, "Re-Fix-1"),
            (2, "Re-Fix-2"),
            (3, "Re-Fix-3"),
        ]
        for attempt_no, expected in cases:
            assert task_name_for_attempt(attempt_no) == expected

    def test_task_name_for_attempt_invalid(self):
        with pytest.raises(ValueError):
            task_name_for_attempt(-1)
        with pytest.raises(ValueError):
            task_name_for_attempt(4)

    def test_review_name_for_attempt(self):
        cases = [
            (0, "(none)"),
            (1, "Review-2"),
            (2, "Review-3"),
            (3, "Final Review"),
        ]
        for attempt_no, expected in cases:
            assert review_name_for_attempt(attempt_no) == expected

    def test_review_name_for_attempt_invalid(self):
        with pytest.raises(ValueError):
            review_name_for_attempt(-1)
        with pytest.raises(ValueError):
            review_name_for_attempt(4)

    def test_all_task_names(self):
        expected = ["No Task", "Coding", "Re-Fix-1", "Re-Fix-2", "Re-Fix-3"]
        assert all_task_names() == expected

    def test_all_review_names(self):
        expected = ["(none)", "Review-1", "Review-2", "Review-3", "Final Review"]
        assert all_review_names() == expected


# ===== SECTION: can_pick_task =====

class TestCanPickTask:
    # Re-Fix-1 locked until Review-1 failed
    def test_re_fix_1_locked_until_review_1_failed(self):
        # Review-1 not reviewed -> cannot pick Re-Fix-1
        assert can_pick_task(1, {0: "not_reviewed"}) is False
        assert can_pick_task(1, {}) is False  # no review record = not_reviewed

        # Review-1 passed -> cannot pick Re-Fix-1
        assert can_pick_task(1, {0: "passed"}) is False

        # Review-1 failed -> CAN pick Re-Fix-1
        assert can_pick_task(1, {0: "failed"}) is True

    def test_coding_allowed_when_no_review(self):
        # attempt_no=0 (Coding) allowed when Review-1 not reviewed
        assert can_pick_task(0, {0: "not_reviewed"}) is True
        assert can_pick_task(0, {}) is True

    def test_coding_not_allowed_after_review_decided(self):
        # Coding not allowed if Review-1 already passed or failed
        assert can_pick_task(0, {0: "passed"}) is False
        assert can_pick_task(0, {0: "failed"}) is False

    def test_re_fix_2_locked_until_review_2_failed(self):
        assert can_pick_task(2, {1: "not_reviewed"}) is False
        assert can_pick_task(2, {1: "passed"}) is False
        assert can_pick_task(2, {1: "failed"}) is True

    def test_re_fix_3_locked_until_review_3_failed(self):
        assert can_pick_task(3, {2: "not_reviewed"}) is False
        assert can_pick_task(3, {2: "passed"}) is False
        assert can_pick_task(3, {2: "failed"}) is True

    def test_invalid_attempt_no(self):
        assert can_pick_task(-1, {}) is False
        assert can_pick_task(4, {}) is False


# ===== SECTION: can_pick_review =====

class TestCanPickReview:
    def test_review_allowed_when_coder_report_exists(self):
        assert can_pick_review(1, {1: True}) is True
        assert can_pick_review(2, {2: True}) is True
        assert can_pick_review(3, {3: True}) is True

    def test_review_not_allowed_without_coder_report(self):
        assert can_pick_review(1, {1: False}) is False
        assert can_pick_review(1, {}) is False
        assert can_pick_review(2, {}) is False
        assert can_pick_review(3, {}) is False

    def test_invalid_attempt_no(self):
        assert can_pick_review(0, {}) is False
        assert can_pick_review(-1, {}) is False
        assert can_pick_review(4, {}) is False


# ===== SECTION: next_phase_status =====

class TestNextPhaseStatus:
    def test_save_command(self):
        cases = [
            ("awaiting_task", "coding_in_progress"),
            ("coding_in_progress", "coding_in_progress"),
            ("coding_completed", "coding_completed"),
            ("cleared", "cleared"),
        ]
        for current, expected in cases:
            assert next_phase_status("save_command", current) == expected

    def test_completed(self):
        cases = [
            ("coding_in_progress", "coding_completed"),
            ("awaiting_task", "awaiting_task"),
            ("coding_completed", "coding_completed"),
            ("cleared", "cleared"),
        ]
        for current, expected in cases:
            assert next_phase_status("completed", current) == expected

    def test_review_passed(self):
        cases = [
            ("coding_completed", "cleared"),
            ("awaiting_task", "awaiting_task"),
            ("coding_in_progress", "coding_in_progress"),
            ("cleared", "cleared"),
        ]
        for current, expected in cases:
            assert next_phase_status("review_passed", current) == expected

    def test_review_failed(self):
        cases = [
            ("coding_completed", "coding_completed"),
            ("awaiting_task", "awaiting_task"),
            ("coding_in_progress", "coding_in_progress"),
            ("cleared", "cleared"),
        ]
        for current, expected in cases:
            assert next_phase_status("review_failed", current) == expected

    def test_manual_set_never_sets_or_leaves_cleared(self):
        # cleared stays cleared
        assert next_phase_status("manual_set", "cleared") == "cleared"
        # other statuses can be set manually (caller validates target)
        assert next_phase_status("manual_set", "awaiting_task") == "awaiting_task"
        assert next_phase_status("manual_set", "coding_in_progress") == "coding_in_progress"
        assert next_phase_status("manual_set", "coding_completed") == "coding_completed"


# ===== SECTION: can_mark_completed =====

class TestCanMarkCompleted:
    def test_enabled_when_has_report_and_not_cleared(self):
        assert can_mark_completed("coding_in_progress", True) is True
        assert can_mark_completed("awaiting_task", True) is True
        assert can_mark_completed("coding_completed", True) is True

    def test_disabled_when_no_report(self):
        assert can_mark_completed("coding_in_progress", False) is False

    def test_disabled_when_cleared(self):
        assert can_mark_completed("cleared", True) is False
        assert can_mark_completed("cleared", False) is False


# ===== SECTION: can_mark_review =====

class TestCanMarkReview:
    def test_enabled_when_has_auditor_report_and_not_cleared(self):
        assert can_mark_review("coding_completed", True) is True
        assert can_mark_review("coding_in_progress", True) is True
        assert can_mark_review("awaiting_task", True) is True

    def test_disabled_when_no_report(self):
        assert can_mark_review("coding_completed", False) is False

    def test_disabled_when_cleared(self):
        assert can_mark_review("cleared", True) is False
        assert can_mark_review("cleared", False) is False


# ===== SECTION: can_new_phase =====

class TestCanNewPhase:
    def test_enabled_when_no_phase(self):
        assert can_new_phase(None) is True

    def test_enabled_when_cleared(self):
        assert can_new_phase("cleared") is True

    def test_disabled_otherwise(self):
        assert can_new_phase("awaiting_task") is False
        assert can_new_phase("coding_in_progress") is False
        assert can_new_phase("coding_completed") is False


# ===== SECTION: recommendation =====

class TestRecommendation:
    def test_not_reviewed(self):
        assert recommendation("not_reviewed", 0) == "Review not decided yet."
        assert recommendation("not_reviewed", 1) == "Review not decided yet."
        assert recommendation("not_reviewed", 3) == "Review not decided yet."

    def test_passed(self):
        expected = "Review passed. Phase cleared. Next: start the Next Phase on Screen C."
        assert recommendation("passed", 0) == expected
        assert recommendation("passed", 1) == expected
        assert recommendation("passed", 3) == expected

    def test_failed_review_1(self):
        assert recommendation("failed", 0) == "Review failed. Next: Re-Fix-1 on Screen C."

    def test_failed_review_2(self):
        assert recommendation("failed", 1) == "Review failed. Next: Re-Fix-2 on Screen C."

    def test_failed_review_3(self):
        assert recommendation("failed", 2) == "Review failed. Next: Re-Fix-3 on Screen C."

    def test_failed_final_review_stop(self):
        assert recommendation("failed", 3) == (
            "Final Review failed. STOP. Owner decision needed. No Re-Fix-4."
        )

    def test_invalid_review_result(self):
        with pytest.raises(ValueError):
            recommendation("invalid", 0)