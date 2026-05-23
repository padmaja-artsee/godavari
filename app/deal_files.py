"""PDF attachments for individual deals."""
import re
import uuid
from pathlib import Path
from typing import Optional

from app.database import get_db, now_iso

DEAL_UPLOAD_ROOT = Path(__file__).resolve().parent.parent / "data" / "uploads" / "deals"


def upgrade_deal_files_schema() -> None:
    DEAL_UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS deal_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deal_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                file_size INTEGER,
                created_at TEXT NOT NULL,
                FOREIGN KEY (deal_id) REFERENCES deals(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_deal_files_deal ON deal_files(deal_id)"
        )


def _safe_pdf_name(name: str) -> str:
    base = Path(name).name
    if not base.lower().endswith(".pdf"):
        raise ValueError("Only PDF files are allowed")
    safe = re.sub(r"[^\w.\- ]", "_", base).strip()
    return safe or "document.pdf"


def list_deal_files(deal_id: int) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, deal_id, filename, stored_path, file_size, created_at
            FROM deal_files WHERE deal_id = ?
            ORDER BY created_at DESC
            """,
            (deal_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def add_deal_file(deal_id: int, filename: str, content: bytes) -> int:
    if not content:
        raise ValueError("Empty file")
    with get_db() as conn:
        if not conn.execute(
            "SELECT id FROM deals WHERE id = ? AND deleted_at IS NULL", (deal_id,)
        ).fetchone():
            raise ValueError("Deal not found")
    safe = _safe_pdf_name(filename)
    stored_name = f"{uuid.uuid4().hex[:12]}_{safe}"
    deal_dir = DEAL_UPLOAD_ROOT / str(deal_id)
    deal_dir.mkdir(parents=True, exist_ok=True)
    path = deal_dir / stored_name
    path.write_bytes(content)
    rel_path = f"{deal_id}/{stored_name}"
    ts = now_iso()
    with get_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO deal_files (deal_id, filename, stored_path, file_size, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (deal_id, safe, rel_path, len(content), ts),
        )
        conn.execute(
            "UPDATE deals SET updated_at = ? WHERE id = ?", (ts, deal_id)
        )
        return cur.lastrowid


def get_deal_file(file_id: int) -> Optional[dict]:
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT f.* FROM deal_files f
            JOIN deals d ON d.id = f.deal_id
            WHERE f.id = ? AND d.deleted_at IS NULL
            """,
            (file_id,),
        ).fetchone()
    if not row:
        return None
    data = dict(row)
    path = DEAL_UPLOAD_ROOT / data["stored_path"]
    if not path.is_file():
        return None
    data["absolute_path"] = str(path)
    return data


def delete_deal_file(file_id: int) -> Optional[int]:
    """Returns deal_id if deleted."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT deal_id, stored_path FROM deal_files WHERE id = ?", (file_id,)
        ).fetchone()
        if not row:
            return None
        deal_id = row["deal_id"]
        conn.execute("DELETE FROM deal_files WHERE id = ?", (file_id,))
    path = DEAL_UPLOAD_ROOT / row["stored_path"]
    if path.is_file():
        path.unlink()
    return deal_id


def delete_all_deal_files(deal_id: int) -> None:
    with get_db() as conn:
        conn.execute("DELETE FROM deal_files WHERE deal_id = ?", (deal_id,))
    deal_dir = DEAL_UPLOAD_ROOT / str(deal_id)
    if deal_dir.is_dir():
        for p in deal_dir.iterdir():
            if p.is_file():
                p.unlink()
        deal_dir.rmdir()
