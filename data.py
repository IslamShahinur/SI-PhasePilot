"""
data.py — all Supabase access: auth, projects, repo paths, phases,
documents, versions, upload/download.

This is the ONLY module that imports and uses the supabase client.
It does not import PySide6 or any ui module.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
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
    # Network / transport errors → OfflineError
    if isinstance(exc, httpx.TransportError):
        return OfflineError("Cannot reach the server. Check your network connection.")
    # Auth API errors (wrong password, expired token, etc.) → DataError
    if isinstance(exc, AuthApiError):
        msg = getattr(exc, "message", None) or str(exc)
        return DataError(msg)
    # PostgREST API errors
    if isinstance(exc, PostgrestAPIError):
        code = getattr(exc, "code", None)
        msg = getattr(exc, "message", None) or str(exc)
        if code == "23514":  # check_violation
            return RuleViolationError(msg)
        return DataError(msg)
    # Storage exceptions
    if isinstance(exc, StorageException):
        cause = getattr(exc, "__cause__", None)
        if isinstance(cause, httpx.TransportError):
            return OfflineError("Cannot reach storage. Check your network connection.")
        return DataError(str(exc))
    # Fallback
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


# ===== SECTION: Secure Delete =====

@_wrap
def _secure_delete_select(
    table: str,
    columns: str,
    filters: dict[str, Any],
    in_filters: dict[str, list[Any]] | None = None,
) -> Rows:
    """Read rows for the Secure Delete workflow."""
    query = _require_client().table(table).select(columns)
    for column, value in filters.items():
        query = query.eq(column, value)
    for column, values in (in_filters or {}).items():
        query = query.in_(column, values)
    result = query.execute()
    return result.data or []


@_wrap
def _secure_delete_rpc(kind: str, item_id: str) -> Any:
    """Run the transactional Secure Delete database function."""
    return _require_client().rpc(
        "pp_secure_delete",
        {"p_kind": kind, "p_id": item_id},
    ).execute()


@_wrap
def _secure_delete_remove_storage(path: str) -> Any:
    """Remove one Storage object after its database rows were deleted."""
    return _require_client().storage.from_(BUCKET).remove([path])


# ===== SECTION: Auth =====

@_wrap
def sign_in(email: str, password: str) -> Row:
    """Sign in with email/password. Returns {user_id, email, refresh_token}."""
    client = _require_client()
    response = client.auth.sign_in_with_password(
        {"email": email, "password": password}
    )
    session = response.session
    if session is None:
        raise DataError("Sign-in failed: no session returned.")
    user = response.user or session.user
    return {
        "user_id": str(user.id),
        "email": user.email,
        "refresh_token": session.refresh_token,
    }


@_wrap
def restore_session(refresh_token: str) -> Row:
    """Restore a session from a stored refresh token.

    Returns {user_id, email, refresh_token}.
    Raises DataError if the token is no longer valid.
    """
    client = _require_client()
    try:
        response = client.auth.refresh_session(refresh_token)
    except AuthApiError as exc:
        msg = getattr(exc, "message", None) or str(exc)
        raise DataError(f"Session restore failed: {msg}") from exc
    session = response.session
    if session is None:
        raise DataError("Session restore failed: no session returned.")
    user = response.user or session.user
    return {
        "user_id": str(user.id),
        "email": user.email,
        "refresh_token": session.refresh_token,
    }


@_wrap
def sign_out() -> None:
    """End the session and clear the client's session cache."""
    client = _require_client()
    client.auth.sign_out()


@_wrap
def current_user_id() -> str:
    """Return the signed-in user's id (used for storage paths)."""
    client = _require_client()
    session = client.auth.get_session()
    if session is None:
        raise DataError("Not signed in.")
    return str(session.user.id)


def ping() -> bool:
    """Cheap reachability check; never raises."""
    client = _require_client()
    try:
        client.table("projects").select("id", count="exact").limit(1).execute()
        return True
    except Exception:
        return False


# ===== SECTION: Projects =====

@_wrap
def list_projects(include_archived: bool = False) -> Rows:
    """Return all projects for the signed-in user, ordered by name."""
    client = _require_client()
    query = client.table("projects").select("*").order("name")
    if not include_archived:
        query = query.is_("archived_at", None)
    result = query.execute()
    return result.data or []


@_wrap
def create_project(name: str, description: str = "") -> Row:
    """Create a new project. Name must be unique among active projects."""
    if not name or not name.strip():
        raise ValidationError("Project name cannot be empty.")
    client = _require_client()
    result = client.table("projects").insert({
        "name": name.strip(),
        "description": description,
    }).execute()
    data = result.data or []
    if not data:
        raise DataError("Project creation returned no data.")
    return data[0]


@_wrap
def update_project(project_id: str, expected_version: int, changes: dict) -> Row:
    """Versioned update of a project."""
    client = _require_client()
    result = (
        client.table("projects")
        .update(changes)
        .eq("id", project_id)
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


@_wrap
def set_project_archived(
    project_id: str, expected_version: int, archived: bool
) -> Row:
    """Archive or reopen a project."""
    if archived:
        changes = {"archived_at": datetime.now(timezone.utc).isoformat()}
    else:
        changes = {"archived_at": None}
    return update_project(project_id, expected_version, changes)


# ===== SECTION: Repository paths =====

@_wrap
def get_repo_path(project_id: str, device_id: str) -> Row | None:
    """Return this PC's repo path for the project, or None."""
    client = _require_client()
    result = (
        client.table("project_repo_paths")
        .select("*")
        .eq("project_id", project_id)
        .eq("device_id", device_id)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


@_wrap
def set_repo_path(
    project_id: str,
    device_id: str,
    device_label: str,
    local_path: str,
    expected_version: int | None = None,
) -> Row:
    """Insert a repo path, or versioned update when a row already exists."""
    existing = get_repo_path(project_id, device_id)
    client = _require_client()
    if existing is None:
        result = client.table("project_repo_paths").insert({
            "project_id": project_id,
            "device_id": device_id,
            "device_label": device_label,
            "local_path": local_path,
        }).execute()
        data = result.data or []
        if not data:
            raise DataError("Repo path insertion returned no data.")
        return data[0]
    # Versioned update
    if expected_version is None:
        expected_version = existing.get("version", 1)
    result = (
        client.table("project_repo_paths")
        .update({
            "device_label": device_label,
            "local_path": local_path,
        })
        .eq("id", existing["id"])
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


# ===== SECTION: Phases (read-only in Phase 1) =====

@_wrap
def list_phases(project_id: str, include_archived: bool = False) -> Rows:
    """Return phases for a project, ordered by phase_no."""
    client = _require_client()
    query = (
        client.table("phases")
        .select("*")
        .eq("project_id", project_id)
        .order("phase_no")
    )
    if not include_archived:
        query = query.is_("archived_at", None)
    result = query.execute()
    return result.data or []


@_wrap
def get_next_phase_no(project_id: str) -> int:
    """Return the next phase_no for a project: max(existing) + 1, or 1 if none exist."""
    phases = list_phases(project_id, include_archived=True)
    if not phases:
        return 1
    return max(ph.get("phase_no", 0) for ph in phases) + 1


# ===== SECTION: Documents =====

@_wrap
def list_documents(
    project_id: str,
    area: str,
    category: str | None = None,
    search: str | None = None,
    include_archived: bool = False,
) -> Rows:
    """Return documents for an area, each with its latest version dict."""
    client = _require_client()
    query = (
        client.table("documents")
        .select("*")
        .eq("project_id", project_id)
        .eq("area", area)
        .order("created_at")
    )
    if not include_archived:
        query = query.is_("archived_at", None)
    if category:
        query = query.eq("category", category)
    if search:
        query = query.ilike("title", f"%{search}%")
    result = query.execute()
    docs = result.data or []
    for doc in docs:
        versions = (
            client.table("document_versions")
            .select("*")
            .eq("document_id", doc["id"])
            .order("version_no", desc=True)
            .limit(1)
            .execute()
        )
        vdata = versions.data or []
        doc["latest_version"] = vdata[0] if vdata else None
    return docs


@_wrap
def create_document(
    project_id: str,
    area: str,
    category: str,
    title: str,
    notes: str = "",
) -> Row:
    """Create document metadata (no file yet)."""
    if not title or not title.strip():
        raise ValidationError("Document title cannot be empty.")
    client = _require_client()
    result = client.table("documents").insert({
        "project_id": project_id,
        "area": area,
        "category": category,
        "title": title.strip(),
        "notes": notes,
        "status": "draft",
    }).execute()
    data = result.data or []
    if not data:
        raise DataError("Document creation returned no data.")
    return data[0]


@_wrap
def update_document(
    document_id: str, expected_version: int, changes: dict
) -> Row:
    """Versioned update of document metadata."""
    client = _require_client()
    result = (
        client.table("documents")
        .update(changes)
        .eq("id", document_id)
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


@_wrap
def archive_document(document_id: str, expected_version: int) -> Row:
    """Set archived_at on a document (no hard delete)."""
    changes = {"archived_at": datetime.now(timezone.utc).isoformat()}
    return update_document(document_id, expected_version, changes)


@_wrap
def list_document_versions(document_id: str) -> Rows:
    """Return all versions of a document, newest first."""
    client = _require_client()
    result = (
        client.table("document_versions")
        .select("*")
        .eq("document_id", document_id)
        .order("version_no", desc=True)
        .execute()
    )
    return result.data or []


@_wrap
def add_document_version(
    document_id: str, project_id: str, file_info: dict
) -> Row:
    """Insert the next version_no for a document."""
    client = _require_client()
    prev = (
        client.table("document_versions")
        .select("version_no", count="exact")
        .eq("document_id", document_id)
        .order("version_no", desc=True)
        .limit(1)
        .execute()
    )
    rows = prev.data or []
    next_no = (rows[0]["version_no"] + 1) if rows else 1
    result = client.table("document_versions").insert({
        "document_id": document_id,
        "project_id": project_id,
        "version_no": next_no,
        "storage_path": file_info["storage_path"],
        "file_name": file_info["file_name"],
        "size_bytes": file_info["size_bytes"],
        "sha256": file_info["sha256"],
    }).execute()
    data = result.data or []
    if not data:
        raise DataError("Version insertion returned no data.")
    return data[0]


# ===== SECTION: Phases (Phase 2) =====

@_wrap
def create_phase(
    project_id: str,
    phase_no: int,
    title: str = "",
    acceptance_notes: str = "",
) -> Row:
    """Create a new phase (DB defaults apply: status 'awaiting_task', attempt 0)."""
    client = _require_client()
    result = client.table("phases").insert({
        "project_id": project_id,
        "phase_no": phase_no,
        "title": title.strip() if title else "",
        "acceptance_notes": acceptance_notes,
    }).execute()
    data = result.data or []
    if not data:
        raise DataError("Phase creation returned no data.")
    return data[0]


@_wrap
def update_phase(
    phase_id: str,
    expected_version: int,
    changes: dict,
) -> Row:
    """Versioned update of phase title and acceptance notes."""
    client = _require_client()
    result = (
        client.table("phases")
        .update(changes)
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


# ===== SECTION: Work items (Phase 2) =====

@_wrap
def list_work_items(
    phase_id: str,
    include_archived: bool = False,
) -> Rows:
    """Return work items for a phase, ordered by sort_order, created_at."""
    client = _require_client()
    query = (
        client.table("work_items")
        .select("*")
        .eq("phase_id", phase_id)
        .order("sort_order")
        .order("created_at")
    )
    if not include_archived:
        query = query.is_("archived_at", None)
    result = query.execute()
    return result.data or []


@_wrap
def add_work_item(
    project_id: str,
    phase_id: str,
    title: str,
    details: str = "",
) -> Row:
    """Create a new work item."""
    if not title or not title.strip():
        raise ValidationError("Work item title cannot be empty.")
    client = _require_client()
    result = client.table("work_items").insert({
        "project_id": project_id,
        "phase_id": phase_id,
        "title": title.strip(),
        "details": details,
    }).execute()
    data = result.data or []
    if not data:
        raise DataError("Work item creation returned no data.")
    return data[0]


@_wrap
def update_work_item(
    item_id: str,
    expected_version: int,
    changes: dict,
) -> Row:
    """Versioned update of work item (title, details, is_done, archived_at)."""
    client = _require_client()
    result = (
        client.table("work_items")
        .update(changes)
        .eq("id", item_id)
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


# ===== SECTION: Commands (Phase 2) =====

@_wrap
def list_commands(
    phase_id: str,
    kind: str,
    attempt_no: int | None = None,
) -> Rows:
    """Return commands for a phase, newest first."""
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
    """Append a new command version (append-only)."""
    if not body or not body.strip():
        raise ValidationError("Command body cannot be empty.")
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


# ===== SECTION: Reports (Phase 2) =====

@_wrap
def list_reports(
    phase_id: str,
    kind: str | None = None,
    attempt_no: int | None = None,
) -> Rows:
    """Return reports for a phase, newest first."""
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


# ===== SECTION: Audit records (Phase 2) =====

@_wrap
def get_audit_record(
    phase_id: str,
    attempt_no: int,
) -> Row | None:
    """Return the audit record for a phase attempt, or None."""
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
def save_audit_record(
    project_id: str,
    phase_id: str,
    attempt_no: int,
    audit_status: str,
    findings: str,
    review_notes: str,
    expected_version: int | None = None,
) -> Row:
    """Insert or update an audit record (versioned update on existing). Sets decided_at for passed/failed."""
    from datetime import datetime, timezone
    existing = get_audit_record(phase_id, attempt_no)
    client = _require_client()
    record = {
        "project_id": project_id,
        "phase_id": phase_id,
        "attempt_no": attempt_no,
        "audit_status": audit_status,
        "findings": findings,
        "review_notes": review_notes,
    }
    # Set decided_at when audit status is passed or failed (F-05)
    if audit_status in ("passed", "failed"):
        record["decided_at"] = datetime.now(timezone.utc).isoformat()
    
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
        raise DataError("Audit record save returned no data.")
    return data[0]


# ===== SECTION: Baselines (Phase 2) =====

@_wrap
def list_baselines(
    project_id: str,
    phase_id: str | None = None,
) -> Rows:
    """Return baselines for a project, newest first. Optionally filter by phase."""
    client = _require_client()
    query = (
        client.table("baselines")
        .select("*")
        .eq("project_id", project_id)
        .order("created_at", desc=True)
    )
    if phase_id is not None:
        query = query.eq("phase_id", phase_id)
    result = query.execute()
    return result.data or []


@_wrap
def add_baseline(
    project_id: str,
    phase_id: str,
    attempt_no: int,
    fields: dict,
) -> Row:
    """Append a new baseline (append-only)."""
    record = {
        "project_id": project_id,
        "phase_id": phase_id,
        "attempt_no": attempt_no,
    }
    record.update(fields)
    client = _require_client()
    result = client.table("baselines").insert(record).execute()
    data = result.data or []
    if not data:
        raise DataError("Baseline creation returned no data.")
    return data[0]


# ===== SECTION: Register items (Phase 2) =====

@_wrap
def list_register_items(
    project_id: str,
    item_type: str | None = None,
    status: str | None = None,
    search: str | None = None,
    include_archived: bool = False,
) -> Rows:
    """Return register items for a project, filtered."""
    client = _require_client()
    query = (
        client.table("register_items")
        .select("*")
        .eq("project_id", project_id)
        .order("created_at", desc=True)
    )
    if item_type:
        query = query.eq("item_type", item_type)
    if status:
        query = query.eq("status", status)
    if search:
        query = query.ilike("description", f"%{search}%")
    if not include_archived:
        query = query.is_("archived_at", None)
    result = query.execute()
    return result.data or []


@_wrap
def add_register_item(
    project_id: str,
    item_type: str,
    description: str,
    phase_id: str | None = None,
    status: str = "open",
    notes: str = "",
) -> Row:
    """Create a new register item."""
    if not description or not description.strip():
        raise ValidationError("Item description cannot be empty.")
    client = _require_client()
    record = {
        "project_id": project_id,
        "item_type": item_type,
        "description": description.strip(),
        "status": status,
        "notes": notes,
    }
    if phase_id is not None:
        record["phase_id"] = phase_id
    result = client.table("register_items").insert(record).execute()
    data = result.data or []
    if not data:
        raise DataError("Register item creation returned no data.")
    return data[0]


@_wrap
def update_register_item(
    item_id: str,
    expected_version: int,
    changes: dict,
) -> Row:
    """Versioned update of register item."""
    client = _require_client()
    result = (
        client.table("register_items")
        .update(changes)
        .eq("id", item_id)
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


# ===== SECTION: Handoff data (Phase 3) =====

@_wrap
def fetch_handoff_data(project_id: str) -> dict[str, Any]:
    """Fetch everything Screen G needs for a project.

    Returns a dict with:
    - project: the project row
    - phases: list of phase rows, ordered by phase_no
    - latest_baseline: the most recent baseline row, or None
    - baselines: list of all baseline rows (newest first)
    - register_items: open and deferred register items
    - documents: list of document rows with their latest_version
    - generated_at: current UTC timestamp
    """
    client = _require_client()

    # Project
    result = (
        client.table("projects")
        .select("*")
        .eq("id", project_id)
        .execute()
    )
    project = (result.data or [{}])[0]

    # Phases
    result = (
        client.table("phases")
        .select("*")
        .eq("project_id", project_id)
        .order("phase_no")
        .execute()
    )
    phases = result.data or []

    # Baselines
    result = (
        client.table("baselines")
        .select(
            "id, owner_id, project_id, attempt_no, override_used, override_reason, "
            "approved_summary, next_phase_notes, repo_path, branch, git_head, "
            "git_tree_hash, working_tree, document_hashes, created_at, "
            "phase_id:phases!inner(phase_no)"
        )
        .eq("project_id", project_id)
        .order("created_at", desc=True)
        .execute()
    )
    baselines = result.data or []

    # Latest baseline (first in the ordered list)
    latest_baseline = baselines[0] if baselines else None

    # Register items (open and deferred)
    result = (
        client.table("register_items")
        .select(
            "id, owner_id, project_id, item_type, description, status, notes, "
            "archived_at, version, created_at, updated_at, "
            "phase_id:phases!inner(phase_no)"
        )
        .eq("project_id", project_id)
        .in_("status", ["open", "deferred", "pending"])
        .order("created_at")
        .execute()
    )
    register_items = result.data or []

    # Documents with latest versions
    result = (
        client.table("documents")
        .select(
            "*, latest_version:document_versions("
            "version_no, file_name, sha256, size_bytes, storage_path)"
        )
        .eq("project_id", project_id)
        .order("area")
        .order("category")
        .order("title")
        .order("version_no", desc=True, foreign_table="document_versions")
        .limit(1, foreign_table="document_versions")
        .execute()
    )
    documents = result.data or []
    for document in documents:
        versions = document.get("latest_version") or []
        document["latest_version"] = versions[0] if versions else None

    return {
        "project": project,
        "phases": phases,
        "latest_baseline": latest_baseline,
        "baselines": baselines,
        "register_items": register_items,
        "documents": documents,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }


# ===== SECTION: File upload / download =====

@_wrap
def upload_file(project_id: str, local_path: str) -> Row:
    """Validate, upload to <user_id>/<project_id>/<uuid>-<safe_name>, return info.

    Never overwrites — always uses a unique UUID-prefixed path.
    """
    file_info = validate_attachment(local_path)
    uid = current_user_id()
    safe_name = safe_filename(file_info["file_name"])
    storage_path = f"{uid}/{project_id}/{uuid.uuid4()}-{safe_name}"
    client = _require_client()
    with open(local_path, "rb") as fh:
        client.storage.from_(BUCKET).upload(storage_path, fh)
    return {
        "storage_path": storage_path,
        "file_name": safe_name,
        "size_bytes": file_info["size_bytes"],
        "sha256": file_info["sha256"],
    }


@_wrap
def download_file(storage_path: str, dest_path: str) -> str:
    """Download a storage file to dest_path and return the path."""
    client = _require_client()
    content = client.storage.from_(BUCKET).download(storage_path)
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as f:
        f.write(content)
    return str(dest)
