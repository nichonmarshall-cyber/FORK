"""
Where raw document files go, if anywhere.

Raw storage is separate from the academic record on purpose. The notebook's
facts come from Fork's confirmed reading of a document; the original file is
a convenience for the student, and holding one is a choice with its own
privacy cost.

    FORK_DOCUMENT_STORAGE   unset or "none"  -> files are not stored (default)
                            "local"          -> files go to FORK_DOCUMENT_STORAGE_DIR

"local" is for development. A production deployment needs an object store
with encryption at rest; that backend is not built, and the API says plainly
when storage is off rather than accepting a file and dropping it.
"""

import os
import secrets
from pathlib import Path

MAX_FILE_BYTES = 10 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "text/plain": ".txt",
}


class StorageUnavailable(RuntimeError):
    pass


class LocalFileStorage:
    name = "local"

    def __init__(self, root: Path):
        self.root = root

    def save(self, student_id: str, data: bytes, content_type: str) -> str:
        folder = self.root / student_id
        folder.mkdir(parents=True, exist_ok=True)
        key = f"{student_id}/{secrets.token_hex(16)}{ALLOWED_CONTENT_TYPES[content_type]}"
        path = self.root / key
        path.write_bytes(data)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return key

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        # Keys are generated here, but a key is still checked to stay inside
        # the root before anything is read or removed.
        if self.root.resolve() not in path.parents:
            raise StorageUnavailable("Invalid storage key.")
        return path

    def read(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        path = self._path(key)
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        # Don't leave an empty per-student folder behind: its name is the
        # student's id, which outlives nothing else of theirs.
        try:
            path.parent.rmdir()
        except OSError:
            pass


def get_storage() -> LocalFileStorage | None:
    """The configured backend, or None when raw files are not stored."""
    mode = os.environ.get("FORK_DOCUMENT_STORAGE", "none").strip().lower()
    if mode in ("", "none"):
        return None
    if mode == "local":
        root = Path(os.environ.get("FORK_DOCUMENT_STORAGE_DIR", "./document_storage"))
        return LocalFileStorage(root)
    raise StorageUnavailable(
        f"FORK_DOCUMENT_STORAGE='{mode}' is not a supported storage backend."
    )


def storage_status() -> dict:
    try:
        backend = get_storage()
    except StorageUnavailable as e:
        return {"raw_files_enabled": False, "backend": None, "message": str(e)}
    if backend is None:
        return {
            "raw_files_enabled": False,
            "backend": None,
            "message": (
                "Fork isn't set up to keep original files on this deployment. "
                "Your record keeps what Fork read from each document and the "
                "details you enter, not the file itself."
            ),
        }
    return {
        "raw_files_enabled": True,
        "backend": backend.name,
        "message": "Original files you attach are stored for your account only.",
    }
