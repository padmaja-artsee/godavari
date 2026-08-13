"""Sales pipeline stages for Active leads (First contact → Conversion)."""

from __future__ import annotations

from typing import Any, Optional

# Ordered funnel (not outcome). Outcome remains open/shipped/lost.
PIPELINE_STAGES: list[tuple[str, str]] = [
    ("first_contact", "First contact"),
    ("rfq", "RFQ"),
    ("rfs", "RFS (sample)"),
    ("conversion", "Conversion"),
]

STAGE_LABELS = dict(PIPELINE_STAGES)
STAGE_ORDER = {key: i for i, (key, _) in enumerate(PIPELINE_STAGES)}
STAGE_KEYS = [key for key, _ in PIPELINE_STAGES]

# Map activity channel → pipeline milestone
CHANNEL_STAGE: dict[str, str] = {
    "Quote": "rfq",
    "Sample": "rfs",
    "PO": "conversion",
}

DATE_COLUMNS = {
    "first_contact": "first_contact_at",
    "rfq": "rfq_at",
    "rfs": "rfs_at",
    "conversion": "conversion_at",
}


def normalize_stage(stage: Optional[str]) -> str:
    key = (stage or "").strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "contact": "first_contact",
        "firstcontact": "first_contact",
        "sample": "rfs",
        "rfs_sample": "rfs",
        "quote": "rfq",
        "po": "conversion",
        "won": "conversion",
    }
    key = aliases.get(key, key)
    return key if key in STAGE_ORDER else "first_contact"


def stage_label(stage: Optional[str]) -> str:
    return STAGE_LABELS.get(normalize_stage(stage), "First contact")


def stage_rank(stage: Optional[str]) -> int:
    return STAGE_ORDER.get(normalize_stage(stage), 0)


def max_stage(a: Optional[str], b: Optional[str]) -> str:
    return a if stage_rank(a) >= stage_rank(b) else normalize_stage(b)


def stage_from_channel(channel: Optional[str]) -> str:
    ch = (channel or "").strip()
    return CHANNEL_STAGE.get(ch, "first_contact")


def infer_stage_from_row(row: dict[str, Any]) -> str:
    """Best stage from stored stage + milestone dates + outcome."""
    if row.get("status") in ("shipped", "lost"):
        # Still show conversion if they got that far; outcome is separate.
        stored = normalize_stage(row.get("pipeline_stage"))
        if row.get("conversion_at") or stored == "conversion":
            return "conversion"
        if row.get("rfs_at"):
            return "rfs"
        if row.get("rfq_at"):
            return "rfq"
        return stored
    stored = normalize_stage(row.get("pipeline_stage"))
    for key in reversed(STAGE_KEYS):
        col = DATE_COLUMNS[key]
        if row.get(col):
            return max_stage(stored, key)
    return stored


def sort_active_leads(
    rows: list[dict],
    sort: str = "stage",
    direction: str = "asc",
) -> list[dict]:
    rev = direction == "desc"
    sort = (sort or "stage").strip().lower()

    def company_key(r: dict) -> str:
        return (r.get("company") or "").casefold()

    def product_key(r: dict) -> str:
        return (r.get("product") or "").casefold()

    def date_key(field: str):
        def _k(r: dict) -> tuple:
            return (r.get(field) or "", company_key(r), product_key(r), r.get("deal_id") or 0)

        return _k

    if sort == "company":
        key = lambda r: (company_key(r), product_key(r), r.get("deal_id") or 0)
    elif sort == "product":
        key = lambda r: (product_key(r), company_key(r), r.get("deal_id") or 0)
    elif sort == "first_contact":
        key = date_key("first_contact_at")
    elif sort == "rfq":
        key = date_key("rfq_at")
    elif sort == "rfs":
        key = date_key("rfs_at")
    elif sort == "conversion":
        key = date_key("conversion_at")
    elif sort == "last_touch":
        key = date_key("last_activity_date")
    else:  # stage (default): funnel order, then last touch newest within stage
        key = lambda r: (
            stage_rank(r.get("pipeline_stage")),
            r.get("last_activity_date") or "",
            company_key(r),
            product_key(r),
            r.get("deal_id") or 0,
        )
        # For stage default, last_touch within stage should be newest first
        # when direction is asc (funnel top→bottom). Handle specially.
        sorted_rows = sorted(rows, key=key, reverse=rev)
        if not rev:
            # Re-sort within each stage by last touch desc
            from itertools import groupby

            out: list[dict] = []
            for _, group in groupby(
                sorted_rows, key=lambda r: stage_rank(r.get("pipeline_stage"))
            ):
                chunk = list(group)
                chunk.sort(
                    key=lambda r: (
                        r.get("last_activity_date") or "",
                        r.get("deal_id") or 0,
                    ),
                    reverse=True,
                )
                out.extend(chunk)
            return out
        return sorted_rows

    return sorted(rows, key=key, reverse=rev)
