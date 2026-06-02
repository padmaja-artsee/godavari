"""Shared document assets (authorized signature image, etc.)."""
from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Optional

from app.database import get_data_dir

ASSETS_DIR = get_data_dir() / "document_assets"
SIG_BASENAME = "authorized_signature"
ALLOWED_SIGNATURE_EXT = {".png", ".jpg", ".jpeg", ".webp"}


def signature_path() -> Optional[Path]:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        p = ASSETS_DIR / f"{SIG_BASENAME}{ext}"
        if p.is_file():
            return p
    return None


def authorized_signature_url() -> Optional[str]:
    p = signature_path()
    if not p:
        return None
    return f"/generate/document-assets/authorized-signature?v={int(p.stat().st_mtime)}"


def authorized_signature_file_uri() -> Optional[str]:
    """file:// URI for WeasyPrint / server-side PDF rendering."""
    p = signature_path()
    return p.as_uri() if p else None


def save_authorized_signature(content: bytes, filename: str) -> Path:
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_SIGNATURE_EXT:
        raise ValueError("Signature must be PNG, JPEG, or WebP.")

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    for old in ASSETS_DIR.glob(f"{SIG_BASENAME}.*"):
        old.unlink(missing_ok=True)

    dest = ASSETS_DIR / f"{SIG_BASENAME}{ext}"
    dest.write_bytes(content)
    return dest


def signature_media_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"
