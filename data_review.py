"""
data_review.py — Supabase access for Phase 4B attempt-aware commands, reports,
phase status, and review results.

Follows the same patterns as data.py: versioned updates, append-only history,
no hard deletes, secrets from env only. No Qt imports, no UI imports.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from supabase import create_client
from supabase_auth.errors import AuthApiError
from postgrest import APIError as PostgrestAPIError
from storage3.utils import StorageException

from services import (
    AppError,
    BUCKET,
    ValidationError,
    safe_filename,
    validate_attachment,
)

Row = dict[str, Any]
Rows = list[Row]

# ===== SECTION: Exceptions =====

class DataError(AppError):
    """Generic server/database failure."""


class OfflineError(DataError):
    """Network unreachable or timeout."""


class ConflictError(DataError):
    """Versioned update matched zero rows (someone else edited)."""


class RuleViolationError(DataError):
    """Database rule rejected the change (phase transition, baseline guard, etc.)."""


# ===== SECTION: Client management =====

_client: Any | None = None


def init_client(url: str, anon_key: str) -> None:
    """Create the single shared Supabase client."""
    global _client
    _client = create_client(url, anon_key)


def _require_client() -> Any:
    """Return the shared client or raise."""
    if _client is None:
        raise DataError("Supabase client is not initialised.")
    return _client


def _translate_error(exc: Exception) -> AppError:
    """Translate library exceptions into app exceptions."""
    if isinstance(exc, AppError):
        return exc
    if isinstance(exc, httpx.TransportError):
        return OfflineError("Cannot reach the server. Check your network connection.")
    if isinstance(exc, AuthApiError):
        msg = getattr(exc, "message", None) or str(exc)
        return DataError(msg)
    if isinstance(exc, PostgrestAPIError):
        code = getattr(exc, "code", None)
        msg = getattr(exc, "message", None) or str(exc)
        if code == "23514":
            return RuleViolationError(msg)
        return DataError(msg)
    if isinstance(exc, StorageException):
        cause = getattr(exc, "__cause__", None)
        if isinstance(cause, httpx.TransportError):
            return OfflineError("Cannot reach storage. Check your network connection.")
        return DataError(str(exc))
    return DataError(str(exc))


def _wrap(fn):
    """Decorator: run *fn*, translate non-app exceptions."""
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except AppError:
            raise
        except Exception as exc:
            raise _translate_error(exc) from exc

    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__ or ""
    return wrapper


# ===== SECTION: Attempt-aware Commands (Screen C) =====

@_wrap
def list_commands(
    phase_id: str,
    kind: str,
    attempt_no: int | None = None,
) -> Rows:
    """Return commands for a phase and attempt, newest first."""
    client = _require_client()
    query = (
        client.table("commands")
        .select("*")
        .eq("phase_id", phase_id)
        .order("created_at", desc=True)
    )
    if kind:
        query = query.eq("kind", kind)
    if attempt_no is not None:
        query = query.eq("attempt_no", attempt_no)
    result = query.execute()
    return result.data or []


@_wrap
def add_command(
    project_id: str,
    phase_id: str,
    attempt_no: int,
    kind: str,
    body: str,
) -> Row:
    """Append a new command version (append-only). Sets phase status to coding_in_progress."""
    if not body or not body.strip():
        raise ValidationError("Command body cannot be empty.")
    if not 0 <= attempt_no <= 3:
        raise ValidationError("attempt_no must be 0..3")
    client = _require_client()
    result = client.table("commands").insert({
        "project_id": project_id,
        "phase_id": phase_id,
        "attempt_no": attempt_no,
        "kind": kind,
        "body": body,
    }).execute()
    data = result.data or []
    if not data:
        raise DataError("Command creation returned no data.")
    return data[0]


# ===== SECTION: Attempt-aware Reports (Screen C) =====

@_wrap
def list_reports(
    phase_id: str,
    kind: str | None = None,
    attempt_no: int | None = None,
) -> Rows:
    """Return reports for a phase and attempt, newest first."""
    client = _require_client()
    query = (
        client.table("reports")
        .select("*")
        .eq("phase_id", phase_id)
        .order("created_at", desc=True)
    )
    if kind:
        query = query.eq("kind", kind)
    if attempt_no is not None:
        query = query.eq("attempt_no", attempt_no)
    result = query.execute()
    return result.data or []


@_wrap
def add_report(
    project_id: str,
    phase_id: str,
    attempt_no: int,
    kind: str,
    content_text: str | None = None,
    file_info: dict | None = None,
) -> Row:
    """Append a new report version (append-only). Text and/or file allowed."""
    if content_text is None and file_info is None:
        raise ValidationError("Report must have text content or a file.")
    if not 0 <= attempt_no <= 3:
        raise ValidationError("attempt_no must be 0..3")
    record: dict[str, Any] = {
        "project_id": project_id,
        "phase_id": phase_id,
        "attempt_no": attempt_no,
        "kind": kind,
    }
    if content_text is not None:
        record["content_text"] = content_text
    if file_info is not None:
        record["storage_path"] = file_info["storage_path"]
        record["file_name"] = file_info["file_name"]
        record["size_bytes"] = file_info["size_bytes"]
        record["sha256"] = file_info["sha256"]
    client = _require_client()
    result = client.table("reports").insert(record).execute()
    data = result.data or []
    if not data:
        raise DataError("Report creation returned no data.")
    return data[0]


# ===== SECTION: Phase status (Screen C) =====

@_wrap
def set_phase_status(
    phase_id: str,
    expected_version: int,
    new_status: str,
) -> Row:
    """Update phase status. Database enforces allowed transitions."""
    client = _require_client()
    result = (
        client.table("phases")
        .update({"status": new_status})
        .eq("id", phase_id)
        .eq("version", expected_version)
        .execute()
    )
    data = result.data or []
    if not data:
        raise ConflictError(
            "This record was changed on another PC or window. "
            "Refresh and try again."
        )
    return data[0]


# ===== SECTION: Review records (Screen D) =====

@_wrap
def get_review_record(
    phase_id: str,
    attempt_no: int,
) -> Row | None:
    """Return the audit/review record for a phase attempt, or None."""
    client = _require_client()
    result = (
        client.table("audit_records")
        .select("*")
        .eq("phase_id", phase_id)
        .eq("attempt_no", attempt_no)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


@_wrap
def save_review_record(
    project_id: str,
    phase_id: str,
    attempt_no: int,
    findings: str,
    review_notes: str,
    expected_version: int | None = None,
) -> Row:
    """
    Insert or update a review record (versioned update on existing).
    Does NOT set audit_status or decided_at; used by 'Save Records' button.
    """
    if not 0 <= attempt_no <= 3:
        raise ValidationError("attempt_no must be 0..3")
    existing = get_review_record(phase_id, attempt_no)
    client = _require_client()
    record = {
        "project_id": project_id,
        "phase_id": phase_id,
        "attempt_no": attempt_no,
        "findings": findings,
        "review_notes": review_notes,
    }
    if existing is None:
        result = client.table("audit_records").insert(record).execute()
    else:
        if expected_version is None:
            expected_version = existing.get("version", 1)
        result = (
            client.table("audit_records")
            .update(record)
            .eq("id", existing["id"])
            .eq("version", expected_version)
            .execute()
        )
    data = result.data or []
    if not data:
        raise DataError("Review record save returned no data.")
    return data[0]


@_wrap
def mark_review_passed(
    project_id: str,
    phase_id: str,
    attempt_no: int,
    findings: str,
    review_notes: str,
    expected_version: int | None = None,
) -> Row:
    """
    Mark review as Passed: sets audit_status='passed', decided_at=now.
    Caller must also set phase status to 'cleared' via set_phase_status.
    """
    if not 0 <= attempt_no <= 3:
        raise ValidationError("attempt_no must be 0..3")
    existing = get_review_record(phase_id, attempt_no)
    client = _require_client()
    record = {
        "project_id": project_id,
        "phase_id": phase_id,
        "attempt_no": attempt_no,
        "audit_status": "passed",
        "findings": findings,
        "review_notes": review_notes,
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }
    if existing is None:
        result = client.table("audit_records").insert(record).execute()
    else:
        if expected_version is None:
            expected_version = existing.get("version", 1)
        result = (
            client.table("audit_records")
            .update(record)
            .eq("id", existing["id"])
            .eq("version", expected_version)
            .execute()
        )
    data = result.data or []
    if not data:
        raise DataError("Mark review passed returned no data.")
    return data[0]


@_wrap
def mark_review_failed(
    project_id: str,
    phase_id: str,
    attempt_no: int,
    findings: str,
    review_notes: str,
    expected_version: int | None = None,
) -> Row:
    """
    Mark review as Failed: sets audit_status='failed', decided_at=now.
    Phase status stays 'coding_completed' (caller does NOT change it).
    """
    if not 0 <= attempt_no <= 3:
        raise ValidationError("attempt_no must be 0..3")
    existing = get_review_record(phase_id, attempt_no)
    client = _require_client()
    record = {
        "project_id": project_id,
        "phase_id": phase_id,
        "attempt_no": attempt_no,
        "audit_status": "failed",
        "findings": findings,
        "review_notes": review_notes,
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }
    if existing is None:
        result = client.table("audit_records").insert(record).execute()
    else:
        if expected_version is None:
            expected_version = existing.get("version", 1)
        result = (
            client.table("audit_records")
            .update(record)
            .eq("id", existing["id"])
            .eq("version", expected_version)
            .execute()
        )
    data = result.data or []
    if not data:
        raise DataError("Mark review failed returned no data.")
    return data[0]


# ===== SECTION: File upload / download (re-exported from data.py pattern) =====

@_wrap
def upload_file(project_id: str, local_path: str) -> Row:
    """Validate, upload to <user_id>/<project_id>/<uuid>-<safe_name>, return info."""
    file_info = validate_attachment(local_path)
    # current_user_id would need auth context; use a placeholder approach
    # In practice, the UI layer gets user_id from session and passes it
    raise NotImplementedError("upload_file requires current_user_id from session")


@_wrap
def download_file(storage_path: str, dest_path: str) -> str:
    """Download a storage file to dest_path and return the path."""
    client = _require_client()
    content = client.storage.from_(BUCKET).download(storage_path)
    from pathlib import Path
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as f:
        f.write(content)
    return str(dest)