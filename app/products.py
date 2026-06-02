import json
import re
import shutil
import uuid
from pathlib import Path
from typing import Any, Optional

from app.database import get_data_dir, get_db, now_iso, upsert_product

_SOURCE_DATA = Path(__file__).resolve().parent.parent / "data"

def _catalogue_path() -> Path:
    import os as _os
    seed_dir = _os.environ.get("LEADS_SEED_DIR")
    base = Path(seed_dir) if seed_dir else _SOURCE_DATA
    return base / "product_catalogue.json"

CATALOGUE_PATH = _catalogue_path()
UPLOAD_ROOT = get_data_dir() / "uploads" / "products"

# Legacy / typo names → canonical catalogue name
PRODUCT_ALIASES = {
    "butyraldehyde and the rmq paperwork": "N-Butyraldehyde",
    "butyraldehyde": "N-Butyraldehyde",
    "croronaldehyde": "Crotonaldehyde (99%)",
    "crotonaldehyde": "Crotonaldehyde (99%)",
    "crotonaldehyde (99%)": "Crotonaldehyde (99%)",
    "1,3 bg": "1,3-Butylene Glycol",
    "ethyl vinyl ether": "Ethyl Vinyl Ether",
    "natural ethyl l- lactate": "Ethyl-(L)-Lactate",
    "natural ethyl l-lactate": "Ethyl-(L)-Lactate",
    "glacial acetic acid": "Acetic Acid",
    "perf. grade ethanol": "Ethanol (Perfumery Grade)",
    "ethyl acetate": "Ethyl Acetate",
    "general": "General",
}


def normalize_product_name(name: str) -> str:
    key = name.strip().lower()
    return PRODUCT_ALIASES.get(key, name.strip())


def _product_columns(conn) -> set[str]:
    return {r[1] for r in conn.execute("PRAGMA table_info(products)").fetchall()}


def upgrade_products_schema() -> None:
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS product_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                file_size INTEGER,
                created_at TEXT NOT NULL,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
            )
            """
        )
        cols = _product_columns(conn)
        for col, typ in [
            ("short_name", "TEXT"),
            ("trade_name", "TEXT"),
            ("cas_number", "TEXT"),
            ("hs_code", "TEXT"),
            ("biobased_content", "TEXT"),
            ("applications", "TEXT"),
            ("certifications", "TEXT"),
            ("category", "TEXT"),
            ("synonyms", "TEXT"),
            ("notes", "TEXT"),
            ("status", "TEXT DEFAULT 'active'"),
            ("updated_at", "TEXT"),
        ]:
            if col not in cols:
                conn.execute(f"ALTER TABLE products ADD COLUMN {col} {typ}")


def _safe_pdf_name(name: str) -> str:
    base = Path(name).name
    if not base.lower().endswith(".pdf"):
        raise ValueError("Only PDF files are allowed")
    safe = re.sub(r"[^\w.\- ]", "_", base).strip()
    return safe or "document.pdf"


def list_product_files(product_id: int) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, product_id, filename, stored_path, file_size, created_at
            FROM product_files WHERE product_id = ?
            ORDER BY created_at DESC
            """,
            (product_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def add_product_file(product_id: int, filename: str, content: bytes) -> int:
    if not content:
        raise ValueError("Empty file")
    safe = _safe_pdf_name(filename)
    stored_name = f"{uuid.uuid4().hex[:12]}_{safe}"
    product_dir = UPLOAD_ROOT / str(product_id)
    product_dir.mkdir(parents=True, exist_ok=True)
    path = product_dir / stored_name
    path.write_bytes(content)
    rel_path = f"{product_id}/{stored_name}"
    ts = now_iso()
    with get_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO product_files (product_id, filename, stored_path, file_size, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (product_id, safe, rel_path, len(content), ts),
        )
        return cur.lastrowid


def get_product_file(file_id: int) -> Optional[dict]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM product_files WHERE id = ?", (file_id,)
        ).fetchone()
    if not row:
        return None
    data = dict(row)
    path = UPLOAD_ROOT / data["stored_path"]
    if not path.is_file():
        return None
    data["absolute_path"] = str(path)
    return data


def delete_product_file(file_id: int) -> Optional[int]:
    """Returns product_id if deleted."""
    info = get_product_file(file_id)
    if not info:
        with get_db() as conn:
            row = conn.execute(
                "SELECT product_id FROM product_files WHERE id = ?", (file_id,)
            ).fetchone()
            if row:
                conn.execute("DELETE FROM product_files WHERE id = ?", (file_id,))
                return row["product_id"]
        return None
    path = Path(info["absolute_path"])
    if path.is_file():
        path.unlink()
    product_id = info["product_id"]
    with get_db() as conn:
        conn.execute("DELETE FROM product_files WHERE id = ?", (file_id,))
    return product_id


def product_usage(product_id: int) -> dict:
    with get_db() as conn:
        deals = conn.execute(
            "SELECT COUNT(*) AS n FROM deals WHERE product_id = ?", (product_id,)
        ).fetchone()["n"]
        engagements = conn.execute(
            "SELECT COUNT(*) AS n FROM engagements WHERE product_id = ?",
            (product_id,),
        ).fetchone()["n"]
        activities = conn.execute(
            "SELECT COUNT(*) AS n FROM activities WHERE product_id = ?",
            (product_id,),
        ).fetchone()["n"]
    return {"deals": deals, "engagements": engagements, "activities": activities}


def delete_product(product_id: int) -> dict:
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, name FROM products WHERE id = ?", (product_id,)
        ).fetchone()
        if not row:
            return {"ok": False, "error": "not_found"}
        if row["name"].strip().lower() == "general":
            return {"ok": False, "error": "protected"}
        usage = product_usage(product_id)
        general_id = upsert_product(conn, "General")
        for table in ("deals", "engagements", "activities"):
            conn.execute(
                f"UPDATE {table} SET product_id = ? WHERE product_id = ?",
                (general_id, product_id),
            )
        name = row["name"]
        for lead in conn.execute(
            "SELECT id, products_interested FROM leads WHERE products_interested LIKE ?",
            (f"%{name}%",),
        ):
            parts = [
                p.strip()
                for p in (lead["products_interested"] or "").split(",")
                if p.strip() and p.strip().lower() != name.lower()
            ]
            conn.execute(
                "UPDATE leads SET products_interested = ? WHERE id = ?",
                (", ".join(parts), lead["id"]),
            )
        file_rows = conn.execute(
            "SELECT id FROM product_files WHERE product_id = ?", (product_id,)
        ).fetchall()
        for fr in file_rows:
            delete_product_file(fr["id"])
        conn.execute("DELETE FROM product_files WHERE product_id = ?", (product_id,))
        conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
    product_dir = UPLOAD_ROOT / str(product_id)
    if product_dir.is_dir():
        shutil.rmtree(product_dir, ignore_errors=True)
    return {"ok": True, "usage": usage, "name": name}


def customers_for_product(product_id: int, product_name: str, synonyms: str = "") -> list[dict]:
    """Customers linked via deals, activities, or lead interest in this product."""
    names_to_match = {product_name.strip().lower()}
    for part in (synonyms or "").split(","):
        if part.strip():
            names_to_match.add(part.strip().lower())
    with get_db() as conn:
        linked = conn.execute(
            """
            SELECT c.id AS customer_id, c.name AS company,
                   COUNT(DISTINCT d.id) AS deals,
                   COUNT(DISTINCT CASE WHEN d.status = 'open' AND d.deleted_at IS NULL THEN d.id END) AS open_deals,
                   COUNT(DISTINCT e.id) AS engagements,
                   COUNT(DISTINCT a.id) AS activities
            FROM customers c
            LEFT JOIN deals d ON d.customer_id = c.id AND d.product_id = ? AND d.deleted_at IS NULL
            LEFT JOIN engagements e ON e.customer_id = c.id AND e.product_id = ?
            LEFT JOIN activities a ON a.customer_id = c.id AND a.product_id = ?
            WHERE c.id IN (
                SELECT customer_id FROM deals WHERE product_id = ? AND deleted_at IS NULL
                UNION
                SELECT customer_id FROM engagements WHERE product_id = ?
                UNION
                SELECT customer_id FROM activities WHERE product_id = ?
            )
            GROUP BY c.id
            ORDER BY c.name COLLATE NOCASE
            """,
            (product_id, product_id, product_id, product_id, product_id, product_id),
        ).fetchall()
        seen = {r["customer_id"] for r in linked}
        result = [dict(r) for r in linked]
        for r in result:
            r["interest_only"] = (
                r["deals"] == 0 and r["activities"] == 0 and r["engagements"] == 0
            )

        lead_rows = conn.execute(
            """
            SELECT c.id AS customer_id, c.name AS company, l.products_interested
            FROM leads l
            JOIN customers c ON c.id = l.customer_id
            WHERE l.products_interested IS NOT NULL AND l.products_interested != ''
            """
        ).fetchall()
        for row in lead_rows:
            if row["customer_id"] in seen:
                continue
            interested = [
                p.strip().lower()
                for p in (row["products_interested"] or "").split(",")
                if p.strip()
            ]
            if names_to_match.intersection(interested):
                result.append(
                    {
                        "customer_id": row["customer_id"],
                        "company": row["company"],
                        "deals": 0,
                        "open_deals": 0,
                        "engagements": 0,
                        "activities": 0,
                        "interest_only": True,
                    }
                )
                seen.add(row["customer_id"])
        result.sort(key=lambda x: x["company"].lower())
    return result


def get_product(product_id: int) -> Optional[dict]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    if not row:
        return None
    data = dict(row)
    data["files"] = list_product_files(product_id)
    data["usage"] = product_usage(product_id)
    data["customers"] = customers_for_product(
        product_id, data["name"], data.get("synonyms") or ""
    )
    return data


PRODUCT_STATUSES = ("active", "development", "retired")


def list_products_full(
    q: str = "",
    category: str = "",
    status: str = "",
) -> list[dict]:
    clauses = ["1=1"]
    params: list[Any] = []
    if q:
        clauses.append(
            """(
                name LIKE ? OR short_name LIKE ? OR trade_name LIKE ? OR cas_number LIKE ?
                OR synonyms LIKE ? OR applications LIKE ? OR certifications LIKE ?
            )"""
        )
        params.extend([f"%{q}%"] * 7)
    if category:
        clauses.append("category = ?")
        params.append(category)
    if status:
        clauses.append("status = ?")
        params.append(status)
    sql = f"""
        SELECT * FROM products
        WHERE {' AND '.join(clauses)}
        ORDER BY
            CASE status
                WHEN 'active' THEN 0
                WHEN 'development' THEN 1
                WHEN 'retired' THEN 2
                ELSE 3
            END,
            name COLLATE NOCASE
    """
    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def save_product(data: dict[str, Any], product_id: Optional[int] = None) -> int:
    name = data["name"].strip()
    ts = now_iso()
    with get_db() as conn:
        if product_id:
            conn.execute(
                """
                UPDATE products SET
                    name = ?, short_name = ?, trade_name = ?, cas_number = ?, hs_code = ?,
                    biobased_content = ?,
                    applications = ?, certifications = ?, category = ?,
                    synonyms = ?, notes = ?, status = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    name,
                    data.get("short_name", ""),
                    data.get("trade_name", ""),
                    data.get("cas_number", ""),
                    data.get("hs_code", ""),
                    data.get("biobased_content", ""),
                    data.get("applications", ""),
                    data.get("certifications", ""),
                    data.get("category", ""),
                    data.get("synonyms", ""),
                    data.get("notes", ""),
                    data.get("status", "active"),
                    ts,
                    product_id,
                ),
            )
            return product_id
        existing = conn.execute(
            "SELECT id FROM products WHERE name = ? COLLATE NOCASE", (name,)
        ).fetchone()
        if existing:
            return save_product(data, existing["id"])
        cur = conn.execute(
            """
            INSERT INTO products (
                name, short_name, trade_name, cas_number, hs_code, biobased_content, applications,
                certifications, category, synonyms, notes, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                data.get("short_name", ""),
                data.get("trade_name", ""),
                data.get("cas_number", ""),
                data.get("hs_code", ""),
                data.get("biobased_content", ""),
                data.get("applications", ""),
                data.get("certifications", ""),
                data.get("category", ""),
                data.get("synonyms", ""),
                data.get("notes", ""),
                data.get("status", "active"),
                ts,
                ts,
            ),
        )
        return cur.lastrowid


def merge_product_names(old_name: str, new_name: str) -> None:
    """Point all references from old product row to canonical product."""
    old_name = old_name.strip()
    new_name = normalize_product_name(new_name)
    with get_db() as conn:
        old = conn.execute(
            "SELECT id FROM products WHERE name = ? COLLATE NOCASE", (old_name,)
        ).fetchone()
        if not old:
            return
        new_id = upsert_product(conn, new_name)
        old_id = old["id"]
        if old_id == new_id:
            return
        for table in ("deals", "engagements", "activities"):
            conn.execute(
                f"UPDATE {table} SET product_id = ? WHERE product_id = ?",
                (new_id, old_id),
            )
        conn.execute(
            """
            UPDATE leads SET products_interested = REPLACE(products_interested, ?, ?)
            WHERE products_interested LIKE ?
            """,
            (old_name, new_name, f"%{old_name}%"),
        )
        conn.execute("DELETE FROM products WHERE id = ?", (old_id,))


def update_deal_product(deal_id: int, product_id: int) -> None:
    from app.product_labels import initial_deal_product_short_name

    with get_db() as conn:
        psn = initial_deal_product_short_name(conn, product_id)
        conn.execute(
            "UPDATE deals SET product_id = ?, product_short_name = ?, updated_at = ? WHERE id = ?",
            (product_id, psn or None, now_iso(), deal_id),
        )


def import_catalogue(merge_aliases: bool = True) -> dict:
    upgrade_products_schema()
    if not CATALOGUE_PATH.exists():
        return {"error": "catalogue not found"}
    items = json.loads(CATALOGUE_PATH.read_text())

    # Skip import if the DB already has at least as many products as the catalogue.
    # This avoids holding write locks on every startup when nothing has changed.
    with get_db() as conn:
        existing_count = conn.execute("SELECT COUNT(*) AS n FROM products").fetchone()["n"]
    if existing_count >= len(items):
        # Still run alias merges in case of name changes, but nothing new to insert.
        counts = {"imported": 0, "merged": 0}
    else:
        # Batch all inserts/updates into a single transaction to minimize lock time.
        counts = {"imported": 0, "merged": 0}
        ts = now_iso()
        with get_db() as conn:
            for item in items:
                name = item["name"].strip()
                existing = conn.execute(
                    "SELECT id FROM products WHERE name = ? COLLATE NOCASE", (name,)
                ).fetchone()
                if existing:
                    conn.execute(
                        """UPDATE products SET
                            short_name=?, trade_name=?, cas_number=?, hs_code=?, biobased_content=?,
                            applications=?, certifications=?, category=?,
                            synonyms=?, notes=?, status=?, updated_at=?
                           WHERE id=?""",
                        (
                            item.get("short_name", "") or item.get("trade_name", ""),
                            item.get("trade_name", ""), item.get("cas_number", ""),
                            item.get("hs_code", ""), item.get("biobased_content", ""),
                            item.get("applications", ""), item.get("certifications", ""),
                            item.get("category", ""), item.get("synonyms", ""),
                            item.get("notes", ""), item.get("status", "active"),
                            ts, existing["id"],
                        ),
                    )
                else:
                    conn.execute(
                        """INSERT INTO products (
                               name, short_name, trade_name, cas_number, hs_code, biobased_content,
                               applications, certifications, category, synonyms, notes,
                               status, created_at, updated_at
                           ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            name,
                            item.get("short_name", "") or item.get("trade_name", ""),
                            item.get("trade_name", ""), item.get("cas_number", ""),
                            item.get("hs_code", ""), item.get("biobased_content", ""),
                            item.get("applications", ""), item.get("certifications", ""),
                            item.get("category", ""), item.get("synonyms", ""),
                            item.get("notes", ""), item.get("status", "active"),
                            ts, ts,
                        ),
                    )
                counts["imported"] += 1

    if merge_aliases:
        with get_db() as conn:
            rows = conn.execute("SELECT id, name FROM products").fetchall()
        for row in rows:
            canonical = normalize_product_name(row["name"])
            if canonical.lower() != row["name"].lower():
                merge_product_names(row["name"], canonical)
                counts["merged"] += 1
    return counts


def fix_legacy_product_names() -> int:
    """Run alias merges for known bad names."""
    upgrade_products_schema()
    merged = 0
    with get_db() as conn:
        names = [r["name"] for r in conn.execute("SELECT name FROM products").fetchall()]
    for name in names:
        canonical = normalize_product_name(name)
        if name.lower() != canonical.lower():
            merge_product_names(name, canonical)
            merged += 1
    return merged
