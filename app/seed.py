import json
import os
from pathlib import Path

from app.database import get_db, init_db, migrate_to_leads_deals, now_iso, upsert_customer, upsert_product

# When packaged, LEADS_SEED_DIR points to the read-only bundle data dir.
# When running from source, fall back to the repo's data/ directory.
_seed_dir = os.environ.get("LEADS_SEED_DIR") or str(Path(__file__).resolve().parent.parent / "data")
SEED_PATH = Path(_seed_dir) / "seed.json"

MILESTONE_MAP = {
    "Initial Request": "initial_request",
    "Initial Response": "initial_response",
    "Sample Requested": "sample_requested",
    "Sample Sent": "sample_sent",
    "Quote Request": "quote_request",
    "Quote Response": "quote_response",
}


def load_seed(force: bool = False) -> dict:
    init_db()
    with get_db() as conn:
        existing = conn.execute("SELECT COUNT(*) AS n FROM engagements").fetchone()["n"]
        if existing and not force:
            migrate_to_leads_deals()
            return {"skipped": True, "engagements": existing}

    if not SEED_PATH.exists():
        return {"error": "seed.json not found"}

    data = json.loads(SEED_PATH.read_text())
    counts = {"engagements": 0, "activities": 0, "gbinc": 0}

    with get_db() as conn:
        for row in data.get("engagements", []):
            customer = row.get("Company", "").strip()
            product = row.get("Chemical", "").strip()
            if not customer or not product:
                continue
            cid = upsert_customer(conn, customer)
            pid = upsert_product(conn, product)
            ts = now_iso()
            s_no = row.get("S.No", "")
            try:
                legacy = int(float(s_no)) if s_no else None
            except (ValueError, TypeError):
                legacy = None

            milestones = {col: "" for col in MILESTONE_MAP.values()}
            for src, dst in MILESTONE_MAP.items():
                val = row.get(src, "")
                if val and str(val) not in ("", "nan"):
                    milestones[dst] = str(val)[:10] if " " in str(val) else str(val)

            cur = conn.execute(
                """
                INSERT INTO engagements (
                    legacy_s_no, customer_id, product_id, contact, summary_notes,
                    initial_request, initial_response, sample_requested, sample_sent,
                    quote_request, quote_response, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    legacy,
                    cid,
                    pid,
                    row.get("Contact", ""),
                    row.get("Summary Notes", ""),
                    milestones["initial_request"],
                    milestones["initial_response"],
                    milestones["sample_requested"],
                    milestones["sample_sent"],
                    milestones["quote_request"],
                    milestones["quote_response"],
                    ts,
                    ts,
                ),
            )
            counts["engagements"] += 1
            eid = cur.lastrowid
            note = row.get("Summary Notes", "")
            if note:
                conn.execute(
                    """
                    INSERT INTO activities (
                        engagement_id, customer_id, product_id,
                        activity_date, activity, type, comment, source, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        eid,
                        cid,
                        pid,
                        ts[:10],
                        "Summary",
                        "Note",
                        note,
                        "import",
                        ts,
                    ),
                )
                counts["activities"] += 1

        engagement_by_legacy: dict[str, int] = {}
        for r in conn.execute(
            "SELECT id, legacy_s_no FROM engagements WHERE legacy_s_no IS NOT NULL"
        ):
            engagement_by_legacy[str(r["legacy_s_no"])] = r["id"]

        for row in data.get("tracker", []):
            eng_key = str(row.get("Engagment", "")).strip()
            eid = engagement_by_legacy.get(eng_key)
            customer = row.get("Company", "").strip()
            product = row.get("Product", "").strip()
            if not customer:
                continue
            cid = upsert_customer(conn, customer)
            pid = upsert_product(conn, product) if product else upsert_product(conn, "General")
            date = str(row.get("Date", ""))[:10] or now_iso()[:10]
            conn.execute(
                """
                INSERT INTO activities (
                    engagement_id, customer_id, product_id,
                    activity_date, activity, type, value, comment, description, source, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    eid,
                    cid,
                    pid,
                    date,
                    row.get("Activity", ""),
                    row.get("Type", ""),
                    row.get("Value", ""),
                    row.get("Comment", ""),
                    row.get("Description", ""),
                    "tracker",
                    now_iso(),
                ),
            )
            counts["activities"] += 1

        for row in data.get("gbinc", []):
            customer = row.get("company", "").strip()
            if not customer:
                continue
            cid = upsert_customer(conn, customer)
            product = (row.get("product") or "General").strip() or "General"
            pid = upsert_product(conn, product)
            ts = now_iso()
            comments = row.get("comments", "")
            date = ts[:10]
            for part in comments.split():
                if len(part) > 6 and any(c.isdigit() for c in part):
                    date = part.replace(",", "")[:10]
                    break
            cur = conn.execute(
                """
                INSERT INTO engagements (
                    customer_id, product_id, contact, email, summary_notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cid,
                    pid,
                    row.get("contact", ""),
                    row.get("email", ""),
                    comments,
                    ts,
                    ts,
                ),
            )
            counts["gbinc"] += 1
            conn.execute(
                """
                INSERT INTO activities (
                    engagement_id, customer_id, product_id,
                    activity_date, activity, type, comment, source, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cur.lastrowid,
                    cid,
                    pid,
                    date,
                    "Email",
                    "Update",
                    comments,
                    "gbinc",
                    ts,
                ),
            )
            counts["activities"] += 1

    migrate_to_leads_deals()
    return counts
