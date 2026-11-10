"""
services.py â€” constants, local settings, device id, session storage,
hashing, attachment validation, sync tracker, Git capture, clipboard.

Phase 1 and 2 implementation. Phase 3 items (summary/export) are declared
in the Master Document and added later.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

import keyring


# ===== SECTION: Constants =====

APP_NAME: str = "SI PhasePilot"
BUCKET: str = "phasepilot-files"
MAX_FILE_BYTES: int = 52_428_800  # 50 MB, matches the bucket limit
ALLOWED_EXTENSIONS: set[str] = {
    ".md", ".txt", ".pdf", ".docx", ".png", ".jpg", ".jpeg", ".json", ".csv",
}
PHASE_STATUSES: list[str] = [
    "not_started", "in_progress", "coding_complete",
    "awaiting_audit", "audit_failed", "audit_passed", "baseline_approved",
]
STATUS_LABELS: dict[str, str] = {
    "not_started": "Not Started",
    "in_progress": "In Progress",
    "coding_complete": "Coding Complete",
    "awaiting_audit": "Awaiting Audit",
    "audit_failed": "Audit Failed",
    "audit_passed": "Audit Passed",
    "baseline_approved": "Baseline Approved",
}
NEXT_STATUSES: dict[str, list[str]] = {
    "not_started": ["in_progress"],
    "in_progress": ["coding_complete", "not_started"],
    "coding_complete": ["awaiting_audit", "in_progress"],
    "awaiting_audit": ["audit_failed", "audit_passed", "coding_complete",
                       "baseline_approved"],
    "audit_failed": ["in_progress", "baseline_approved"],
    "audit_passed": ["baseline_approved"],
    "baseline_approved": [],
}
AUDIT_STATUSES: list[str] = ["not_started", "in_progress", "passed", "failed"]
REGISTER_TYPES: list[str] = ["critical", "deferred", "fixation", "pending"]
REGISTER_STATUSES: list[str] = ["open", "pending", "deferred", "resolved", "closed"]
DOC_AREAS: list[str] = ["foundation", "ui_visual"]
FOUNDATION_CATEGORIES: list[str] = [
    "Finalized Blueprint", "Phase Control Document",
    "Initial Project Notes", "Other",
]
UI_CATEGORIES: list[str] = [
    "UI Blueprint", "UI Architecture", "Design Tokens",
    "Layout & Component Specs", "Other",
]
REPORT_KINDS: list[str] = [
    "coder_report", "auditor_report", "claude_review", "user_verification",
]
COMMAND_KINDS: list[str] = ["coder", "auditor", "fix"]
# Appendix F.6 (supersedes Appendix E): A Blue, B Violet, C Teal,
# D Indigo, E Green, F Amber, G Slate. Red is reserved for Delete only.
SCREEN_ACCENTS: dict[str, str] = {
    "A": "#2563EB", "B": "#7C3AED", "C": "#0F766E", "D": "#4F46E5",
    "E": "#15803D", "F": "#D97706", "G": "#475569",
}
_SCREEN_LABELS: dict[str, str] = {
    "A": "Project Foundation", "B": "UI && Visual Documents",
    "C": "Phase Worklist", "D": "Project Review",
    "E": "Approved Baseline", "F": "Critical Registers",
    "G": "Project Handoff",
}


# ===== SECTION: Exceptions =====

class AppError(Exception):
    """Base class for all application errors."""


class ValidationError(AppError):
    """Raised when input fails client-side validation."""


class GitError(AppError):
    """Raised when Git is missing, the repo path is invalid, or a git command fails."""


# ===== SECTION: Local paths and settings =====

def _app_data_dir() -> Path:
    """Raw %APPDATA%\\SI-PhasePilot path (internal)."""
    base = os.environ.get("APPDATA", "")
    if not base:
        raise AppError("APPDATA is not set on this system.")
    return Path(base) / "SI-PhasePilot"


def _app_root() -> Path:
    """Return the directory that contains this source tree (internal)."""
    # Walk up from services.py location
    return Path(__file__).resolve().parent


def app_data_dir() -> Path:
    """Return %APPDATA%\\SI-PhasePilot, creating it if missing."""
    path = _app_data_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def temp_dir() -> Path:
    """Return the temp subfolder under app-data, creating it if missing."""
    path = app_data_dir() / "temp"
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_export_dir() -> Path:
    """Return the exports subfolder under app-data, creating it if missing."""
    path = app_data_dir() / "exports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _settings_path() -> Path:
    """Path to settings.json (internal)."""
    return app_data_dir() / "settings.json"


def load_local_settings() -> dict[str, Any]:
    """Read settings.json; return an empty dict if missing or corrupt."""
    path = _settings_path()
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def save_local_settings(settings: dict[str, Any]) -> None:
    """Write settings.json atomically."""
    path = _settings_path()
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, sort_keys=True)
    tmp.replace(path)


# ===== SECTION: Device identity =====

def get_device_id() -> str:
    """Stable UUID for this PC, stored in settings."""
    settings = load_local_settings()
    device_id = settings.get("device_id")
    if not device_id:
        device_id = str(uuid.uuid4())
        settings["device_id"] = device_id
        save_local_settings(settings)
    return device_id


def get_device_label() -> str:
    """Computer name for display."""
    return os.environ.get("COMPUTERNAME", "unknown")


# ===== SECTION: Session storage (keyring) =====

_KEYRING_SERVICE: str = APP_NAME
_KEYRING_USER: str = "session"


def save_session(email: str, refresh_token: str) -> None:
    """Store (email, refresh_token) in Windows Credential Manager via keyring."""
    payload = json.dumps({"email": email, "refresh_token": refresh_token})
    keyring.set_password(_KEYRING_SERVICE, _KEYRING_USER, payload)


def load_session() -> tuple[str, str] | None:
    """Return (email, refresh_token) or None if no stored session."""
    payload = keyring.get_password(_KEYRING_SERVICE, _KEYRING_USER)
    if payload is None:
        return None
    try:
        obj = json.loads(payload)
        email = obj.get("email", "")
        refresh_token = obj.get("refresh_token", "")
        if email and refresh_token:
            return (email, refresh_token)
    except Exception:
        pass
    return None


def clear_session() -> None:
    """Remove the stored session from keyring."""
    try:
        keyring.delete_password(_KEYRING_SERVICE, _KEYRING_USER)
    except Exception:
        pass


# ===== SECTION: Hashing helpers =====

def sha256_file(path: str | Path) -> str:
    """Return the hex SHA-256 of a file, read in 256 KB chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(256 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    """Return the hex SHA-256 of UTF-8 text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ===== SECTION: Filename / attachment validation =====

def safe_filename(name: str) -> str:
    """Strip path components and unsafe characters, keep the extension."""
    # Remove any directory components
    name = Path(name).name
    # Replace characters that are problematic on Windows
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    # Collapse multiple underscores / spaces
    name = re.sub(r"\s+", "_", name).strip("._ ") or "file"
    return name


def validate_attachment(path: str | Path) -> dict:
    """Validate an attachment file.

    Returns a dict with file_name, size_bytes and sha256.
    Raises ValidationError on any problem.
    """
    p = Path(path)
    if not p.exists():
        raise ValidationError(f"File not found: {p}")
    if not p.is_file():
        raise ValidationError(f"Not a file: {p}")
    ext = p.suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise ValidationError(
            f"File type '{ext}' is not allowed. Allowed: {allowed}"
        )
    size = p.stat().st_size
    if size <= 0:
        raise ValidationError("File is empty.")
    if size > MAX_FILE_BYTES:
        raise ValidationError(
            f"File is too large ({size} bytes; max {MAX_FILE_BYTES})."
        )
    digest = sha256_file(p)
    return {
        "file_name": p.name,
        "size_bytes": size,
        "sha256": digest,
    }


def open_with_default_app(path: str | Path) -> None:
    """Open a file with its default Windows application."""
    os.startfile(str(path))


def format_phase_label(phase_no: int) -> str:
    """Format a phase number as a zero-padded two-digit label."""
    return f"{phase_no:02d}"


# ===== SECTION: Sync state and tracker =====

class SyncState(Enum):
    """Possible sync states shown in the UI."""
    SYNCED = "SYNCED"
    SAVING = "SAVING"
    OFFLINE = "OFFLINE"
    ERROR = "ERROR"


@dataclass
class SyncTracker:
    """Tracks the current sync state and notifies listeners."""

    _state: SyncState = field(init=False, default=SyncState.SYNCED)
    _message: str = field(init=False, default="")
    _listeners: list[Callable[[SyncState, str], None]] = field(
        init=False, default_factory=list
    )

    def set_state(self, state: SyncState, message: str = "") -> None:
        """Set the current state and notify all listeners."""
        self._state = state
        self._message = message
        for listener in list(self._listeners):
            listener(state, message)

    def get_state(self) -> SyncState:
        """Return the current sync state."""
        return self._state

    def get_message(self) -> str:
        """Return the current state message."""
        return self._message

    def add_listener(self, callback: Callable[[SyncState, str], None]) -> None:
        """Register a callback called whenever the state changes."""
        self._listeners.append(callback)

    def is_writable(self) -> bool:
        """Return False when writes are blocked (Offline or Saving)."""
        return self._state not in (SyncState.OFFLINE, SyncState.SAVING)


def screen_label(letter: str) -> str:
    """Return the human-readable label for a screen letter."""
    return _SCREEN_LABELS.get(letter.upper(), letter)


# ===== SECTION: Git capture =====
from dataclasses import dataclass


@dataclass
class GitInfo:
    """Result of a Git capture."""
    head: str
    branch: str
    tree_hash: str
    working_tree: str
    error: str | None


def git_available() -> bool:
    """Return True if Git is installed."""
    import subprocess
    try:
        result = subprocess.run(
            ["git", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def validate_repo_path(path: str) -> None:
    """Raise GitError if the path is not a valid Git repository."""
    if not path:
        raise GitError("Repository path cannot be empty.")
    import subprocess
    try:
        result = subprocess.run(
            ["git", "-C", path, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            raise GitError(
                f"'{path}' is not a Git repository. "
                "Check the path and try again."
            )
    except FileNotFoundError as exc:
        raise GitError(
            "Git is not installed or not on PATH. "
            "Install Git for Windows and restart the app."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise GitError("Git command timed out.") from exc
    except Exception as exc:
        raise GitError(f"Could not validate repository path: {exc}") from exc


def git_capture(repo_path: str) -> GitInfo:
    """Capture Git state from the repository at *repo_path*.

    Runs git commands with argument lists (no shell=True), 15-second timeout.
    Handles missing Git, non-repo path, and safe.directory errors.
    Returns GitInfo with head, branch, tree_hash, working_tree, error.
    """
    import subprocess
    try:
        # HEAD
        result = subprocess.run(
            ["git", "-C", repo_path, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if "safe.directory" in stderr:
                return GitInfo(
                    head="",
                    branch="",
                    tree_hash="",
                    working_tree="unknown",
                    error=(
                        f"Git error: repository not in safe.directory list.\n\n"
                        f"Run this command to fix: git config --global --add safe.directory \"{repo_path}\"\n"
                        f"Or: git config --global safe.directory --add \"{repo_path}\"\n\n"
                        f"Details: {stderr}"
                    ),
                )
            return GitInfo(
                head="",
                branch="",
                tree_hash="",
                working_tree="unknown",
                error=f"Failed to read HEAD: {stderr}",
            )
        head = result.stdout.strip()

        # Branch
        result = subprocess.run(
            ["git", "-C", repo_path, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            return GitInfo(
                head=head,
                branch="",
                tree_hash="",
                working_tree="unknown",
                error=f"Failed to read branch: {result.stderr.strip()}",
            )
        branch = result.stdout.strip()

        # Tree hash
        result = subprocess.run(
            ["git", "-C", repo_path, "rev-parse", "HEAD^{tree}"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            return GitInfo(
                head=head,
                branch=branch,
                tree_hash="",
                working_tree="unknown",
                error=f"Failed to read tree hash: {result.stderr.strip()}",
            )
        tree_hash = result.stdout.strip()

        # Working tree status
        result = subprocess.run(
            ["git", "-C", repo_path, "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            return GitInfo(
                head=head,
                branch=branch,
                tree_hash=tree_hash,
                working_tree="unknown",
                error=f"Failed to read working tree status: {result.stderr.strip()}",
            )
        working_tree = "clean" if result.stdout.strip() == "" else "modified"

        return GitInfo(
            head=head,
            branch=branch,
            tree_hash=tree_hash,
            working_tree=working_tree,
            error=None,
        )

    except FileNotFoundError as exc:
        raise GitError(
            "Git is not installed or not on PATH. "
            "Install Git for Windows and restart the app."
        ) from exc
    except subprocess.TimeoutExpired:
        raise GitError("Git command timed out (15 seconds).")
    except Exception as exc:
        raise GitError(f"Git capture failed: {exc}")


# ===== SECTION: Clipboard =====

def copy_to_clipboard(text: str) -> None:
    """Copy text to the system clipboard."""
    from PySide6.QtGui import QClipboard
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    clipboard: QClipboard = app.clipboard()
    if clipboard is not None:
        clipboard.setText(text)


# ===== SECTION: Session sync =====

def sync_session_to_review_client() -> bool:
    """
    Sync the authenticated session from data client to data_review client.
    
    Returns True if sync succeeded, False if data client has no session.
    Raises exception if data_review client cannot be updated.
    """
    import data
    import data_review
    
    data_client = data._require_client()
    session = data_client.auth.get_session()
    if session is None:
        return False
    
    review_client = data_review._require_client()
    review_client.auth.set_session(session.access_token, session.refresh_token)
    return True


def clear_both_sessions() -> None:
    """Clear sessions on both data and data_review clients."""
    import data
    import data_review
    
    try:
        data_client = data._require_client()
        data_client.auth.sign_out()
    except Exception:
        pass
    
    try:
        review_client = data_review._require_client()
        review_client.auth.sign_out()
    except Exception:
        pass


# ===== SECTION: Handoff export (Phase 3) =====

def build_summary_markdown(data: dict[str, Any]) -> str:
    """Build a deterministic project handoff summary markdown from *data*.

    The only timestamp used is data["generated_at"].
    Follows the structure in Appendix C of the Master Document.
    """
    lines: list[str] = []

    # Title
    project_name = data.get("project", {}).get("name", "Unknown Project")
    lines.append(f"# {project_name} â€” Project Handoff Summary")
    lines.append("")

    # Generated timestamp
    generated_at = data.get("generated_at", "Unknown date")
    lines.append(f"Generated: {generated_at}")
    lines.append("")

    # Section 1: Current State
    lines.append("## 1. Current State")
    phases = data.get("phases", [])
    current_phase = None
    for p in phases:
        if p.get("status") != "baseline_approved":
            current_phase = p
            break
    if current_phase:
        phase_no = current_phase.get("phase_no", 0)
        title = current_phase.get("title", "")
        status = current_phase.get("status", "unknown")
        attempt = current_phase.get("current_attempt", 0)
        status_label = STATUS_LABELS.get(status, status)
        lines.append(
            f"- Current phase: {phase_no:02d} â€” {title} (status: {status_label}, attempt {attempt})"
        )
    else:
        lines.append("- Current phase: None recorded")

    # Latest approved baseline
    baselines = data.get("baselines", [])
    if baselines:
        latest = baselines[0]  # Newest first
        phase_no = latest.get("phase_id", {}).get("phase_no", 0) if isinstance(latest.get("phase_id"), dict) else 0
        attempt = latest.get("attempt_no", 0)
        git_head = latest.get("git_head", "")
        branch = latest.get("branch", "")
        tree_hash = latest.get("git_tree_hash", "")
        working_tree = latest.get("working_tree", "unknown")
        approved_on = latest.get("created_at", "Unknown")
        lines.append(
            f"- Latest approved baseline: Phase {phase_no:02d} (attempt {attempt})"
        )
        lines.append(
            f"  - Git HEAD: {git_head}   Branch: {branch}   "
            f"Tree hash: {tree_hash}   Working tree: {working_tree}"
        )
        lines.append(f"  - Approved on: {approved_on}")
    else:
        lines.append("- Latest approved baseline: None recorded")
    lines.append("")

    # Section 2: Phase Overview
    lines.append("## 2. Phase Overview")
    lines.append("")
    lines.append("| Phase | Title | Status | Attempts | Baseline |")
    lines.append("|---|---|---|---|---|")
    for p in phases:
        phase_no = p.get("phase_no", 0)
        title = p.get("title", "")
        status = p.get("status", "unknown")
        status_label = STATUS_LABELS.get(status, status)
        attempt = p.get("current_attempt", 0)
        baseline_status = "Yes" if p.get("status") == "baseline_approved" else "No"
        lines.append(
            f"| {phase_no:02d} | {title} | {status_label} | {attempt} | {baseline_status} |"
        )
    if not phases:
        lines.append("| - | - | - | - | - |")
    lines.append("")

    # Section 3: Important Decisions
    lines.append("## 3. Important Decisions")
    baseline_list = data.get("baselines", [])
    decisions: list[str] = []
    for b in baseline_list:
        summary = b.get("approved_summary", "")
        override_reason = b.get("override_reason", "")
        phase_no = b.get("phase_id", {}).get("phase_no", 0) if isinstance(b.get("phase_id"), dict) else 0
        if summary:
            decisions.append(f"  - Baseline approval: Phase {phase_no:02d} â€” {summary}")
        if override_reason:
            decisions.append(f"  - Override: Phase {phase_no:02d} â€” {override_reason}")

    register_items = data.get("register_items", [])
    for item in register_items:
        if item.get("item_type") == "critical":
            desc = item.get("description", "")
            phase_no = item.get("phase_id", {}).get("phase_no", 0) if isinstance(item.get("phase_id"), dict) else 0
            status = item.get("status", "unknown")
            decisions.append(
                f"  - Critical note: {desc} (Phase {phase_no:02d}, {status})"
            )

    if decisions:
        for d in decisions:
            lines.append(d)
    else:
        lines.append("None recorded")
    lines.append("")

    # Section 4: Open and Deferred Items
    lines.append("## 4. Open and Deferred Items")
    lines.append("")
    lines.append("| Type | Item | Phase | Status |")
    lines.append("|---|---|---|---|")
    open_deferred = [
        item for item in register_items
        if item.get("status") in ("open", "deferred", "pending")
    ]
    for item in open_deferred:
        item_type = item.get("item_type", "")
        desc = item.get("description", "")
        phase_no = item.get("phase_id", {}).get("phase_no", 0) if isinstance(item.get("phase_id"), dict) else 0
        status = item.get("status", "unknown")
        lines.append(f"| {item_type} | {desc} | {phase_no:02d} | {status} |")
    if not open_deferred:
        lines.append("| - | - | - | - |")
    lines.append("")

    # Section 5: Next Phase Instructions
    lines.append("## 5. Next Phase Instructions")
    next_notes = ""
    if baselines:
        latest = baselines[0]
        next_notes = latest.get("next_phase_notes", "")
    if next_notes:
        lines.append(next_notes)
    else:
        lines.append("None recorded")
    lines.append("")

    # Section 6: Relevant Documents
    lines.append("## 6. Relevant Documents")
    lines.append("")
    lines.append("| Area | Category | Title | Latest file | Version | SHA-256 |")
    lines.append("|---|---|---|---|---|---|")
    documents = data.get("documents", [])
    for doc in documents:
        area = doc.get("area", "")
        category = doc.get("category", "")
        title = doc.get("title", "")
        latest_version = doc.get("latest_version") or {}
        file_name = latest_version.get("file_name", "")
        version_no = latest_version.get("version_no", 0)
        sha256 = latest_version.get("sha256", "")
        lines.append(
            f"| {area} | {category} | {title} | {file_name} | {version_no} | {sha256} |"
        )
    if not documents:
        lines.append("| - | - | - | - | - | - |")
    lines.append("")

    # Section 7: Baseline History
    lines.append("## 7. Baseline History")
    lines.append("")
    lines.append("| Phase | Attempt | Git HEAD | Tree hash | Override | Date |")
    lines.append("|---|---|---|---|---|---|")
    for b in baselines:
        phase_no = b.get("phase_id", {}).get("phase_no", 0) if isinstance(b.get("phase_id"), dict) else 0
        attempt = b.get("attempt_no", 0)
        git_head = b.get("git_head", "")
        tree_hash = b.get("git_tree_hash", "")
        override = "Yes" if b.get("override_used") else "No"
        date = b.get("created_at", "")
        lines.append(
            f"| {phase_no:02d} | {attempt} | {git_head} | {tree_hash} | {override} | {date} |"
        )
    if not baselines:
        lines.append("| - | - | - | - | - | - |")

    return "\n".join(lines)


def build_manifest(files: list[dict[str, Any]]) -> str:
    """Build a manifest text with name, SHA-256 and size for each file.

    Format: <name>  <sha256>  <size_bytes>
    """
    lines: list[str] = []
    for f in files:
        name = f.get("file_name", "")
        sha256 = f.get("sha256", "")
        size = f.get("size_bytes", 0)
        lines.append(f"{name}  {sha256}  {size}")
    return "\n".join(lines)


def export_markdown(data: dict[str, Any], dest_path: str | Path) -> Path:
    """Write the handoff summary as a markdown file to *dest_path*.

    Returns the written path.
    """
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = build_summary_markdown(data)
    dest.write_text(content, encoding="utf-8")
    return dest


def export_zip(
    data: dict[str, Any],
    dest_path: str | Path,
    files: list[tuple[str, Path]],
) -> Path:
    """Create a ZIP handoff package at *dest_path*.

    The ZIP contains:
    - summary.md
    - manifest.txt
    - documents/... (from the *files* list)

    The *files* list contains tuples of (relative_path_in_zip, local_file_path).
    Returns the written path.
    """
    import zipfile

    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Build summary and manifest
    summary_content = build_summary_markdown(data)

    # Build manifest from files
    manifest_lines: list[str] = ["summary.md  " + sha256_text(summary_content) + "  " + str(len(summary_content.encode("utf-8")))]
    for rel_path, local_path in files:
        file_info = validate_attachment(local_path)
        manifest_lines.append(
            f"{rel_path}  {file_info['sha256']}  {file_info['size_bytes']}"
        )
    manifest_content = "\n".join(manifest_lines)

    # Write ZIP
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        # summary.md
        zf.writestr("summary.md", summary_content)

        # manifest.txt
        zf.writestr("manifest.txt", manifest_content)

        # documents
        for rel_path, local_path in files:
            arcname = f"documents/{rel_path}"
            zf.write(local_path, arcname)

    return dest

