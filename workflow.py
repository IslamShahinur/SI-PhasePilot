"""
workflow.py — pure functions for Phase 4B attempt ladder and state transitions.

No Qt imports, no Supabase calls, no side effects.
"""
from __future__ import annotations

from typing import Literal

# ===== SECTION: Types =====

PhaseStatus = Literal["awaiting_task", "coding_in_progress", "coding_completed", "cleared"]
ReviewStatus = Literal["not_reviewed", "passed", "failed"]
Event = Literal["save_command", "completed", "review_passed", "review_failed", "manual_set"]
TaskName = Literal["No Task", "Coding", "Re-Fix-1", "Re-Fix-2", "Re-Fix-3"]
ReviewName = Literal["(none)", "Review-1", "Review-2", "Review-3", "Final Review"]

# ===== SECTION: Attempt ladder =====

# attempt_no -> (task_name, review_name)
# attempt_no 0: (none) / No Task is a special case handled separately
ATTEMPT_LADDER: dict[int, tuple[TaskName, ReviewName]] = {
    0: ("Coding", "Review-1"),
    1: ("Re-Fix-1", "Review-2"),
    2: ("Re-Fix-2", "Review-3"),
    3: ("Re-Fix-3", "Final Review"),
}

MAX_ATTEMPT_NO = 3


def task_name_for_attempt(attempt_no: int) -> TaskName:
    """Return the Screen C Task dropdown label for *attempt_no*."""
    if attempt_no < 0 or attempt_no > MAX_ATTEMPT_NO:
        raise ValueError(f"attempt_no must be 0..{MAX_ATTEMPT_NO}")
    if attempt_no == 0:
        # Special case: "No Task" is shown when no task is picked yet
        return "No Task"
    return ATTEMPT_LADDER[attempt_no][0]


def review_name_for_attempt(attempt_no: int) -> ReviewName:
    """Return the Screen D Review dropdown label for *attempt_no*."""
    if attempt_no < 0 or attempt_no > MAX_ATTEMPT_NO:
        raise ValueError(f"attempt_no must be 0..{MAX_ATTEMPT_NO}")
    if attempt_no == 0:
        return "(none)"
    return ATTEMPT_LADDER[attempt_no][1]


def all_task_names() -> list[TaskName]:
    """Return all possible Task dropdown values in order."""
    return ["No Task", "Coding", "Re-Fix-1", "Re-Fix-2", "Re-Fix-3"]


def all_review_names() -> list[ReviewName]:
    """Return all possible Review dropdown values in order."""
    return ["(none)", "Review-1", "Review-2", "Review-3", "Final Review"]


# ===== SECTION: Can-pick predicates =====

def can_pick_task(attempt_no: int, review_results: dict[int, ReviewStatus]) -> bool:
    """
    Whether the Task dropdown may be set to *attempt_no*.

    Rules (patch section 1):
    - No Task (attempt_no not picked) is always allowed.
    - Coding (attempt_no=0) allowed when no review exists for attempt 0.
    - Re-Fix-N (attempt_no=N>0) allowed only when Review-N has review_status == "failed".
    """
    if attempt_no == 0:
        # Coding: allowed if Review-1 not yet decided (not_reviewed or no record)
        return review_results.get(0, "not_reviewed") == "not_reviewed"
    if 1 <= attempt_no <= MAX_ATTEMPT_NO:
        # Re-Fix-N: allowed only if Review-N failed
        # Review-N corresponds to attempt_no = N-1
        return review_results.get(attempt_no - 1, "not_reviewed") == "failed"
    return False


def can_pick_review(attempt_no: int, reports: dict[int, bool]) -> bool:
    """
    Whether the Review dropdown may be set to *attempt_no*.

    Rules (patch section 1):
    - Review-N can be picked only after that attempt has a saved Coder Report.
    - reports[attempt_no] == True means a coder_report exists for that attempt.
    """
    if attempt_no < 0 or attempt_no > MAX_ATTEMPT_NO:
        return False
    return reports.get(attempt_no, False)


# ===== SECTION: Phase status transitions =====

def next_phase_status(event: Event, current: PhaseStatus) -> PhaseStatus:
    """
    Compute the new phase status after *event* given *current* status.

    Rules (patch sections 1, 3, 4):
    - save_command: awaiting_task -> coding_in_progress; coding_in_progress stays; others unchanged.
    - completed: coding_in_progress -> coding_completed; others unchanged.
    - review_passed: coding_completed -> cleared; others unchanged.
    - review_failed: coding_completed stays coding_completed; others unchanged.
    - manual_set: user may set awaiting_task, coding_in_progress, coding_completed.
      cleared is never set or left by manual_set.
    """
    if event == "save_command":
        if current == "awaiting_task":
            return "coding_in_progress"
        if current == "coding_in_progress":
            return "coding_in_progress"
        return current

    if event == "completed":
        if current == "coding_in_progress":
            return "coding_completed"
        return current

    if event == "review_passed":
        if current == "coding_completed":
            return "cleared"
        return current

    if event == "review_failed":
        if current == "coding_completed":
            return "coding_completed"
        return current

    if event == "manual_set":
        # manual_set never sets or leaves cleared
        if current == "cleared":
            return "cleared"
        # User can only pick the first three; caller validates the target
        return current

    return current


def can_mark_completed(phase_status: PhaseStatus, has_coder_report: bool, task_attempt: int | None = None) -> bool:
    """
    Whether the COMPLETED button is enabled.

    Rules (patch section 3):
    - Enabled only when this task has a saved Coder Report, the phase is not cleared,
      and a task has been picked.
    """
    if phase_status == "cleared":
        return False
    if not has_coder_report:
        return False
    if task_attempt is None:
        return False
    return True


def can_mark_review(phase_status: PhaseStatus, has_auditor_report: bool) -> bool:
    """
    Whether Mark Review Passed/Failed buttons are enabled.

    Rules (patch section 4):
    - Enabled only when this attempt has a saved Auditor Report and the phase is not cleared.
    """
    return phase_status != "cleared" and has_auditor_report


def can_new_phase(phase_status: PhaseStatus | None) -> bool:
    """
    Whether the New Phase button is enabled.

    Rules (patch section 3):
    - Enabled only when there is no phase, or the current phase is cleared.
    """
    return phase_status is None or phase_status == "cleared"


# ===== SECTION: Recommendation text =====

def recommendation(review_result: ReviewStatus, attempt_no: int) -> str:
    """
    Return the exact recommendation text for the Recommendations panel.

    Rules (patch section 4, table):
    - Not reviewed: "Review not decided yet."
    - Passed: "Review passed. Phase cleared. Next: start the Next Phase on Screen C."
    - Failed, Review-1/2/3: "Review failed. Next: Re-Fix-1/2/3 on Screen C."
    - Failed, Final Review: "Final Review failed. STOP. Owner decision needed. No Re-Fix-4."
    """
    if review_result == "not_reviewed":
        return "Review not decided yet."
    if review_result == "passed":
        return "Review passed. Phase cleared. Next: start the Next Phase on Screen C."
    if review_result == "failed":
        if attempt_no == 3:
            return "Final Review failed. STOP. Owner decision needed. No Re-Fix-4."
        # attempt_no 0 -> Re-Fix-1, 1 -> Re-Fix-2, 2 -> Re-Fix-3
        fix_num = attempt_no + 1
        return f"Review failed. Next: Re-Fix-{fix_num} on Screen C."
    raise ValueError(f"Unknown review_result: {review_result}")