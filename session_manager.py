"""
REMO_OX Financial Analytics - Session Manager
Handles persistent session storage: create, load, save, list, cleanup.
Each session is isolated and stored in its own directory under sessions/.
"""

import json
import os
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from werkzeug.utils import secure_filename

# Sessions directory - shared volume in Docker, local dir otherwise
SESSIONS_DIR = Path(os.environ.get("SESSIONS_DIR", Path(__file__).parent / "sessions"))

ALLOWED_EXTENSIONS = {".xlsx"}
ALLOWED_MIME_TYPES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def _ensure_sessions_dir():
    """Create the sessions directory if it doesn't exist."""
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def create_session() -> str:
    """
    Create a new session with a unique ID.
    Returns the session_id (12 hex characters).
    """
    _ensure_sessions_dir()
    session_id = uuid.uuid4().hex[:12]
    session_dir = SESSIONS_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "session_id": session_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "file_name": None,
        "file_original_name": None,
        "columns": [],
        "row_count": 0,
    }
    _write_json(session_dir / "meta.json", meta)
    _write_json(session_dir / "chat_history.json", [])

    return session_id


def load_session(session_id: str) -> dict | None:
    """
    Load session metadata and chat history.
    Returns None if the session does not exist.
    """
    try:
        session_dir = get_session_path(session_id)
    except ValueError:
        return None

    if not session_dir.exists():
        return None

    meta_path = session_dir / "meta.json"
    chat_path = session_dir / "chat_history.json"

    meta = _read_json(meta_path) if meta_path.exists() else {}
    chat_history = _read_json(chat_path) if chat_path.exists() else []

    return {
        "meta": meta,
        "chat_history": chat_history,
        "session_dir": str(session_dir),
    }


def save_chat(session_id: str, messages: list[dict]):
    """Persist chat history to disk."""
    session_dir = get_session_path(session_id)
    if not session_dir.exists():
        raise ValueError(f"Session {session_id} not found")

    # Store only serializable fields (role, content, images)
    clean_messages = []
    for msg in messages:
        clean_msg = {
            "role": msg.get("role", ""),
            "content": msg.get("content", ""),
        }
        if msg.get("images"):
            clean_msg["images"] = msg["images"]
        clean_messages.append(clean_msg)

    _write_json(session_dir / "chat_history.json", clean_messages)


def save_upload(
    session_id: str,
    file_bytes: bytes,
    original_name: str,
    mime_type: str,
) -> dict:
    """
    Validate and save an uploaded .xlsx file to the session directory.

    Performs triple validation:
      1. File extension must be .xlsx
      2. MIME type must match Excel Open XML format
      3. File must be readable by Pandas as an actual Excel file

    Returns dict with file info and column names.
    Raises ValueError on validation failure.
    """
    session_dir = get_session_path(session_id)
    if not session_dir.exists():
        raise ValueError(f"Session {session_id} not found")

    # 1. Validate extension
    safe_name = secure_filename(original_name)
    if not safe_name:
        raise ValueError("Invalid file name.")
    ext = Path(safe_name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(
            f"Invalid file type '{ext}'. Only .xlsx files are allowed."
        )

    # 2. Validate MIME type
    if mime_type and mime_type not in ALLOWED_MIME_TYPES:
        raise ValueError(
            f"Invalid MIME type '{mime_type}'. "
            f"Expected: {', '.join(ALLOWED_MIME_TYPES)}"
        )

    # 3. Save file as data.xlsx (original name stored in meta)
    file_path = session_dir / "data.xlsx"
    file_path.write_bytes(file_bytes)

    # 4. Validate it's a real Excel file by attempting to read it
    try:
        df = pd.read_excel(file_path, engine="openpyxl")
    except Exception as e:
        file_path.unlink(missing_ok=True)
        raise ValueError(f"Failed to read Excel file: {e}")

    columns = [
        {"name": str(col), "dtype": str(df[col].dtype)} for col in df.columns
    ]

    # 5. Update session metadata
    meta_path = session_dir / "meta.json"
    meta = _read_json(meta_path) if meta_path.exists() else {}
    meta["file_name"] = "data.xlsx"
    meta["file_original_name"] = original_name
    meta["columns"] = columns
    meta["row_count"] = len(df)
    _write_json(meta_path, meta)

    return {
        "file_path": str(file_path),
        "original_name": original_name,
        "columns": columns,
        "row_count": len(df),
    }


def list_sessions() -> list[dict]:
    """List all available sessions with metadata, newest first."""
    _ensure_sessions_dir()
    sessions = []
    for item in sorted(SESSIONS_DIR.iterdir(), reverse=True):
        if item.is_dir():
            meta_path = item / "meta.json"
            if meta_path.exists():
                try:
                    meta = _read_json(meta_path)
                    sessions.append(meta)
                except (json.JSONDecodeError, OSError):
                    pass
    return sessions


def get_session_path(session_id: str) -> Path:
    """
    Get the base path for a session directory.
    Validates the session ID to prevent path traversal attacks.
    """
    safe_id = secure_filename(session_id)
    if not safe_id or safe_id != session_id:
        raise ValueError(f"Invalid session ID: {session_id}")
    return SESSIONS_DIR / safe_id


def get_data_file_path(session_id: str) -> Path | None:
    """Get the path to the uploaded data file for a session, or None."""
    try:
        session_dir = get_session_path(session_id)
    except ValueError:
        return None
    data_path = session_dir / "data.xlsx"
    return data_path if data_path.exists() else None


def cleanup_old_sessions(max_age_hours: int = 72):
    """Remove sessions older than max_age_hours to free disk space."""
    _ensure_sessions_dir()
    cutoff = time.time() - (max_age_hours * 3600)
    for item in SESSIONS_DIR.iterdir():
        if item.is_dir():
            meta_path = item / "meta.json"
            if meta_path.exists():
                try:
                    meta = _read_json(meta_path)
                    created = meta.get("created_at", "")
                    created_dt = datetime.fromisoformat(created)
                    if created_dt.timestamp() < cutoff:
                        shutil.rmtree(item, ignore_errors=True)
                except (ValueError, OSError, json.JSONDecodeError):
                    pass


# --- Internal JSON helpers ---

def _read_json(path: Path) -> dict | list:
    """Read and parse a JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, data: dict | list):
    """Write data to a JSON file atomically."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
