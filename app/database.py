from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Optional

import os as _os

# ---------------------------------------------------------------------------
# Data directory resolution
# When packaged (PyInstaller), LEADS_DATA_DIR is set to a writable OS path
# such as ~/Library/Application Support/GodavariLeads.
# When running from source, fall back to the repo's data/ directory.
# ---------------------------------------------------------------------------
_SOURCE_DATA = Path(__file__).resolve().parent.parent / "data"

def get_data_dir() -> Path:
    """Return the writable data directory (DB, uploads, exports)."""
    env = _os.environ.get("LEADS_DATA_DIR")
    p = Path(env) if env else _SOURCE_DATA
    p.mkdir(parents=True, exist_ok=True)
    return p

DB_PATH = Path(
    _os.environ.get("LEADS_DB_PATH")
    or get_data_dir() / "leads.db"
)


def now_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_activity_date(value: str) -> str:
    """Store activity dates as YYYY-MM-DD."""
    raw = (value or "").strip()
    if not raw:
        raise ValueError("Date is required")
    if re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
        return raw
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", raw)
    if m:
        month, day, year = m.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"
    m = re.match(r"^(\d{4})[/\-](\d{1,2})[/\-](\d{1,2})$", raw)
    if m:
        year, month, day = m.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw[:10], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError("Use a valid date (YYYY-MM-DD or MM/DD/YYYY)")


def iso_date_input(value: str = "") -> str:
    """Format a stored date for HTML date inputs."""
    if not value:
        return ""
    try:
        return normalize_activity_date(str(value)[:10])
    except ValueError:
        return str(value)[:10]


PRICE_UNITS = ("/MT", "/kg", "/lb", "/unit", "Other")
QUANTITY_UNITS = ("MT", "FCL", "Other")


def normalize_quantity_unit(unit: str = "", other: str = "") -> str:
    u = (unit or "MT").strip()
    if u == "Other":
        custom = (other or "").strip()
        return custom if custom else "Other"
    return u or "MT"


def list_quantity_unit_options() -> list[str]:
    """MT, FCL, Other, plus custom units used on past deals."""
    base = list(QUANTITY_UNITS)
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT quantity_unit FROM deals
            WHERE quantity_unit IS NOT NULL AND trim(quantity_unit) != ''
              AND quantity_unit NOT IN ('MT', 'FCL', 'Other')
            ORDER BY quantity_unit COLLATE NOCASE
            """
        ).fetchall()
    seen = set(base)
    out = list(base)
    for r in rows:
        u = (r["quantity_unit"] or "").strip()
        if u and u not in seen:
            out.append(u)
            seen.add(u)
    return out


def format_quantity_display(quantity: str = "", quantity_unit: str = "MT") -> str:
    if quantity is None:
        q = ""
    else:
        q = str(quantity).strip()
    u = (quantity_unit or "MT").strip() or "MT"
    if not q:
        return ""
    if u in ("", "Other"):
        return q
    q_low = q.lower()
    u_low = u.lower()
    if q_low.endswith(u_low) or q_low.endswith(f" {u_low}"):
        return q
    return f"{q} {u}"

SHIPPING_FIELDS = (
    "po_date",
    "packing",
    "gbl_invoice",
    "gbl_invoice_date",
    "container_number",
    "vessel_name",
    "etd_india",
    "transit_time",
    "destination",
    "eta",
)

COMMERCIAL_EXTRA_FIELDS = (
    "commercial_total",
    "insurance_amount",
    "insurance_currency",
    "ocean_freight_amount",
    "ocean_freight_currency",
    "fob_value",
    "fob_currency",
    "commission_rate",
    "commission_amount",
)

COMMERCIAL_CURRENCIES = (
    ("INR", "₹ Rupee"),
    ("USD", "$ Dollar"),
)

# Deal price / FOB / commission currency (also used when prefilling CIs).
# Labels match Sales Invoice / PO currency selects.
DEAL_CURRENCIES = (
    "Euro",
    "USD",
    "GBP",
    "JPY",
    "CHF",
    "CAD",
    "AUD",
    "CNY",
    "INR",
    "SGD",
)

_CURRENCY_ALIASES = {
    "EUR": "Euro",
    "EURO": "Euro",
    "US$": "USD",
    "DOLLAR": "USD",
    "DOLLARS": "USD",
}


def normalize_deal_currency(raw: str, default: str = "USD") -> str:
    """Map free-text / legacy codes onto DEAL_CURRENCIES labels."""
    s = (raw or "").strip()
    if not s:
        return default
    upper = s.upper()
    if upper in _CURRENCY_ALIASES:
        return _CURRENCY_ALIASES[upper]
    for c in DEAL_CURRENCIES:
        if c.upper() == upper or c == s:
            return c
    return default


def currency_unit_words(currency: str) -> tuple[str, str]:
    """Major/minor unit names for amount-in-words."""
    cur = normalize_deal_currency(currency)
    mapping = {
        "USD": ("Dollar", "Cent"),
        "Euro": ("Euro", "Cent"),
        "GBP": ("Pound", "Pence"),
        "INR": ("Rupee", "Paisa"),
        "JPY": ("Yen", "Sen"),
        "CHF": ("Franc", "Rappen"),
        "CAD": ("Dollar", "Cent"),
        "AUD": ("Dollar", "Cent"),
        "CNY": ("Yuan", "Fen"),
        "SGD": ("Dollar", "Cent"),
    }
    return mapping.get(cur, (cur, "Cent"))


def format_deal_value(
    quantity: str = "",
    price: str = "",
    price_unit: str = "/MT",
    quantity_unit: str = "MT",
) -> str:
    """Legacy single-line value from structured commercial fields."""
    q = format_quantity_display(quantity, quantity_unit)
    p = (price or "").strip()
    u = (price_unit or "/MT").strip() or "/MT"
    if not q and not p:
        return ""
    if p:
        if p.startswith("$"):
            price_str = f"{p} {u}" if u != "Other" else p
        elif u == "Other":
            price_str = p
        else:
            price_str = f"${p}{u}"
    else:
        price_str = ""
    if q and price_str:
        return f"{q}, {price_str}"
    return q or price_str


def _parse_commercial_number(text: str) -> float:
    if not text:
        return 0.0
    s = str(text).replace(",", "").strip()
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(m.group()) if m else 0.0


def compute_commercial_total(quantity: str, price: str) -> str:
    """Qty × price per unit (numeric string, empty if either missing)."""
    qty = _parse_commercial_number(quantity)
    rate = _parse_commercial_number(price)
    if not qty or not rate:
        return ""
    total = qty * rate
    if total == int(total):
        return str(int(total))
    return f"{total:.2f}".rstrip("0").rstrip(".")


def _format_commercial_number(n: float) -> str:
    if n == int(n):
        return str(int(n))
    return f"{n:.2f}".rstrip("0").rstrip(".")


def compute_fob_value(
    commercial_total: str,
    insurance_amount: str,
    ocean_freight_amount: str,
) -> str:
    """FOB = Value − Insurance − Ocean freight."""
    total = _parse_commercial_number(commercial_total)
    if not total:
        return ""
    fob = total - _parse_commercial_number(insurance_amount) - _parse_commercial_number(ocean_freight_amount)
    return _format_commercial_number(fob)


def compute_commission_amount(fob_value: str, commission_rate: str) -> str:
    """Commission = FOB × (rate / 100)."""
    fob = _parse_commercial_number(fob_value)
    rate = _parse_commercial_number(commission_rate)
    if not fob or not rate:
        return ""
    return _format_commercial_number(fob * rate / 100.0)


def default_quote_ref(
    conn: sqlite3.Connection,
    customer_id: int,
    product_id: int,
    hint: str = "",
) -> str:
    """Optional override; otherwise deal id is stored after insert."""
    if hint.strip():
        return hint.strip()[:80]
    return ""


def _finalize_deal_id_ref(
    conn: sqlite3.Connection, deal_id: int, hint: str = ""
) -> None:
    if not (hint or "").strip():
        conn.execute(
            "UPDATE deals SET quote_ref = ? WHERE id = ?",
            (str(deal_id), deal_id),
        )


def deal_picker_label(deal: dict) -> str:
    """Short label for deal dropdowns."""
    parts: list[str] = []
    did = deal.get("id") or deal.get("deal_id")
    if did:
        parts.append(str(did))
    parts.append(deal.get("deal_date") or "")
    parts.append(deal.get("product") or "")
    if deal.get("po_number"):
        parts.append(f"PO {deal['po_number']}")
    elif deal.get("quantity") or deal.get("price"):
        comm = format_deal_value(
            deal.get("quantity") or "",
            deal.get("price") or "",
            deal.get("price_unit") or "/MT",
            deal.get("quantity_unit") or "MT",
        )
        if comm:
            parts.append(comm)
    parts.append(deal.get("status") or "open")
    return " · ".join(p for p in parts if p)


def commercial_from_data(data: dict[str, Any]) -> dict[str, str]:
    """Normalize commercial fields from form/log payloads."""
    unit = (
        data.get("price_unit")
        or data.get("deal_price_unit")
        or "/MT"
    ).strip() or "/MT"
    qty_unit = normalize_quantity_unit(
        data.get("quantity_unit")
        or data.get("deal_quantity_unit")
        or "MT",
        data.get("quantity_unit_other") or data.get("deal_quantity_unit_other") or "",
    )
    qty = (data.get("quantity") or data.get("deal_quantity") or "").strip()
    price = (data.get("price") or data.get("deal_price") or "").strip()
    if not qty and not price and data.get("deal_value"):
        legacy = (data.get("deal_value") or data.get("value") or "").strip()
        return {
            "po_number": (data.get("po_number") or data.get("deal_po_number") or "").strip(),
            "quantity": legacy,
            "quantity_unit": qty_unit,
            "price": "",
            "price_unit": unit,
            "value": legacy,
        }
    po = (data.get("po_number") or data.get("deal_po_number") or "").strip()
    return {
        "po_number": po,
        "quantity": qty,
        "quantity_unit": qty_unit,
        "price": price,
        "price_unit": unit,
        "value": format_deal_value(qty, price, unit, qty_unit),
    }


def patch_deal_commercial(
    conn: sqlite3.Connection,
    deal_id: int,
    data: dict[str, Any],
) -> None:
    """Update deal commercial fields when provided on log/save."""
    comm = commercial_from_data(data)
    sets: list[str] = []
    params: list[Any] = []
    if comm["po_number"]:
        sets.append("po_number = ?")
        params.append(comm["po_number"])
    if comm["quantity"] or comm["price"]:
        sets.extend(
            [
                "quantity = ?",
                "quantity_unit = ?",
                "price = ?",
                "price_unit = ?",
                "value = ?",
            ]
        )
        params.extend(
            [
                comm["quantity"],
                comm["quantity_unit"],
                comm["price"],
                comm["price_unit"],
                comm["value"],
            ]
        )
    if not sets:
        return
    sets.append("updated_at = ?")
    params.extend([now_iso(), deal_id])
    conn.execute(
        f"UPDATE deals SET {', '.join(sets)} WHERE id = ?",
        params,
    )


@contextmanager
def get_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    # timeout=30: retry for up to 30 s if another connection holds a write lock.
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL mode allows concurrent readers + one writer without blocking reads.
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER NOT NULL UNIQUE,
                contact TEXT,
                email TEXT,
                website TEXT,
                phone TEXT,
                products_interested TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (customer_id) REFERENCES customers(id)
            );

            CREATE TABLE IF NOT EXISTS deals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id INTEGER NOT NULL,
                customer_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                po_number TEXT,
                quote_ref TEXT,
                quantity TEXT,
                quantity_unit TEXT DEFAULT 'MT',
                price TEXT,
                price_unit TEXT DEFAULT '/MT',
                deal_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                shipped_date TEXT,
                value TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (lead_id) REFERENCES leads(id),
                FOREIGN KEY (customer_id) REFERENCES customers(id),
                FOREIGN KEY (product_id) REFERENCES products(id)
            );

            CREATE TABLE IF NOT EXISTS engagements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                legacy_s_no INTEGER,
                customer_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                contact TEXT,
                email TEXT,
                po_number TEXT,
                summary_notes TEXT,
                initial_request TEXT,
                initial_response TEXT,
                sample_requested TEXT,
                sample_sent TEXT,
                quote_request TEXT,
                quote_response TEXT,
                status TEXT DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (customer_id) REFERENCES customers(id),
                FOREIGN KEY (product_id) REFERENCES products(id)
            );

            CREATE TABLE IF NOT EXISTS activities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                engagement_id INTEGER,
                lead_id INTEGER,
                deal_id INTEGER,
                customer_id INTEGER,
                product_id INTEGER,
                activity_date TEXT NOT NULL,
                activity TEXT,
                type TEXT,
                value TEXT,
                comment TEXT,
                description TEXT,
                source TEXT DEFAULT 'manual',
                created_at TEXT NOT NULL,
                FOREIGN KEY (engagement_id) REFERENCES engagements(id),
                FOREIGN KEY (lead_id) REFERENCES leads(id),
                FOREIGN KEY (deal_id) REFERENCES deals(id),
                FOREIGN KEY (customer_id) REFERENCES customers(id),
                FOREIGN KEY (product_id) REFERENCES products(id)
            );

            CREATE INDEX IF NOT EXISTS idx_activities_date ON activities(activity_date);
            CREATE INDEX IF NOT EXISTS idx_deals_status ON deals(status);
            CREATE INDEX IF NOT EXISTS idx_deals_date ON deals(deal_date);
            """
        )
        _upgrade_schema(conn)
    from app.deal_files import upgrade_deal_files_schema
    from app.products import upgrade_products_schema
    from app.purchase_orders import upgrade_purchase_orders_schema

    upgrade_products_schema()
    upgrade_deal_files_schema()
    upgrade_purchase_orders_schema()
    migrate_to_leads_deals()


def _upgrade_schema(conn: sqlite3.Connection) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(deals)").fetchall()}
    if "closed_date" not in cols:
        conn.execute("ALTER TABLE deals ADD COLUMN closed_date TEXT")
        conn.execute(
            "UPDATE deals SET closed_date = shipped_date WHERE shipped_date IS NOT NULL"
        )
    if "archived" not in cols:
        conn.execute("ALTER TABLE deals ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
    if "deleted_at" not in cols:
        conn.execute("ALTER TABLE deals ADD COLUMN deleted_at TEXT")
    if "quantity" not in cols:
        conn.execute("ALTER TABLE deals ADD COLUMN quantity TEXT")
    if "quantity_unit" not in cols:
        conn.execute(
            "ALTER TABLE deals ADD COLUMN quantity_unit TEXT DEFAULT 'MT'"
        )
    if "price" not in cols:
        conn.execute("ALTER TABLE deals ADD COLUMN price TEXT")
    if "price_unit" not in cols:
        conn.execute("ALTER TABLE deals ADD COLUMN price_unit TEXT DEFAULT '/MT'")
    if "quote_ref" not in cols:
        conn.execute("ALTER TABLE deals ADD COLUMN quote_ref TEXT")
        conn.execute(
            """
            UPDATE deals SET quote_ref = CAST(id AS TEXT)
            WHERE quote_ref IS NULL OR quote_ref = ''
            """
        )
    conn.execute(
        """
        UPDATE deals SET quote_ref = CAST(id AS TEXT)
        WHERE quote_ref LIKE 'Quote %' OR quote_ref LIKE 'Quote #%'
        """
    )
    for col in SHIPPING_FIELDS:
        if col not in cols:
            conn.execute(f"ALTER TABLE deals ADD COLUMN {col} TEXT")
    for col in ("incoterms", "payment_terms", "shipment_timing"):
        if col not in cols:
            conn.execute(f"ALTER TABLE deals ADD COLUMN {col} TEXT")
    for col in COMMERCIAL_EXTRA_FIELDS:
        if col not in cols:
            conn.execute(f"ALTER TABLE deals ADD COLUMN {col} TEXT")
    if "product_short_name" not in cols:
        conn.execute("ALTER TABLE deals ADD COLUMN product_short_name TEXT")
    conn.execute(
        """
        UPDATE deals SET product_short_name = (
            SELECT CASE
                WHEN TRIM(COALESCE(p.trade_name, '')) != ''
                THEN TRIM(p.trade_name)
                ELSE TRIM(p.name)
            END
            FROM products p WHERE p.id = deals.product_id
        )
        WHERE product_short_name IS NULL OR TRIM(product_short_name) = ''
           OR LOWER(TRIM(product_short_name)) = 'none'
        """
    )
    pipeline_cols = {
        "pipeline_stage": "TEXT NOT NULL DEFAULT 'first_contact'",
        "first_contact_at": "TEXT",
        "rfq_at": "TEXT",
        "rfs_at": "TEXT",
        "conversion_at": "TEXT",
    }
    need_pipeline_backfill = False
    for col, typ in pipeline_cols.items():
        if col not in cols:
            conn.execute(f"ALTER TABLE deals ADD COLUMN {col} {typ}")
            need_pipeline_backfill = True
    if need_pipeline_backfill:
        _backfill_pipeline_stages(conn)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_deals_pipeline ON deals(pipeline_stage)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            contact TEXT,
            email TEXT,
            phone TEXT,
            is_primary INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_contacts_customer ON contacts(customer_id)"
    )
    _migrate_contacts_from_leads(conn)
    act_cols = {r[1] for r in conn.execute("PRAGMA table_info(activities)").fetchall()}
    for col, typ in [
        ("lead_id", "INTEGER"),
        ("deal_id", "INTEGER"),
        ("channel", "TEXT"),
        ("email_subject", "TEXT"),
        ("email_from", "TEXT"),
        ("email_to", "TEXT"),
    ]:
        if col not in act_cols:
            conn.execute(f"ALTER TABLE activities ADD COLUMN {col} {typ}")
    _migrate_activity_deal_links(conn)
    conn.execute(
        """
        UPDATE activities SET product_id = (
            SELECT d.product_id FROM deals d WHERE d.id = activities.deal_id
        )
        WHERE deal_id IS NOT NULL
        """
    )


def _backfill_pipeline_stages(conn: sqlite3.Connection) -> None:
    """Seed pipeline milestones from deal date + activity channels."""
    from app.pipeline import DATE_COLUMNS, normalize_stage, stage_from_channel, stage_rank

    conn.execute(
        """
        UPDATE deals
        SET pipeline_stage = COALESCE(NULLIF(TRIM(pipeline_stage), ''), 'first_contact'),
            first_contact_at = COALESCE(NULLIF(TRIM(first_contact_at), ''), deal_date)
        WHERE deleted_at IS NULL
        """
    )
    rows = conn.execute(
        """
        SELECT d.id AS deal_id, a.activity_date, a.channel, a.activity
        FROM deals d
        JOIN activities a ON a.deal_id = d.id
        WHERE d.deleted_at IS NULL
        ORDER BY d.id, a.activity_date ASC, a.id ASC
        """
    ).fetchall()
    by_deal: dict[int, dict] = {}
    for r in rows:
        did = r["deal_id"]
        state = by_deal.setdefault(
            did,
            {
                "pipeline_stage": "first_contact",
                "first_contact_at": None,
                "rfq_at": None,
                "rfs_at": None,
                "conversion_at": None,
            },
        )
        date = r["activity_date"]
        if not state["first_contact_at"] and date:
            state["first_contact_at"] = date
        ch = (r["channel"] or r["activity"] or "").strip()
        stage = stage_from_channel(ch)
        col = DATE_COLUMNS[stage]
        if date and not state[col]:
            state[col] = date
        if stage_rank(stage) > stage_rank(state["pipeline_stage"]):
            state["pipeline_stage"] = stage
    for did, state in by_deal.items():
        conn.execute(
            """
            UPDATE deals SET
                pipeline_stage = ?,
                first_contact_at = COALESCE(first_contact_at, ?),
                rfq_at = COALESCE(rfq_at, ?),
                rfs_at = COALESCE(rfs_at, ?),
                conversion_at = COALESCE(conversion_at, ?)
            WHERE id = ?
            """,
            (
                normalize_stage(state["pipeline_stage"]),
                state["first_contact_at"],
                state["rfq_at"],
                state["rfs_at"],
                state["conversion_at"],
                did,
            ),
        )
    # PO number implies conversion milestone
    conn.execute(
        """
        UPDATE deals
        SET conversion_at = COALESCE(conversion_at, po_date, deal_date),
            pipeline_stage = 'conversion'
        WHERE deleted_at IS NULL
          AND po_number IS NOT NULL AND TRIM(po_number) != ''
          AND (pipeline_stage IS NULL OR pipeline_stage != 'conversion')
        """
    )


def apply_pipeline_progress(
    conn: sqlite3.Connection,
    deal_id: int,
    stage: Optional[str],
    activity_date: Optional[str] = None,
) -> None:
    """Advance deal stage and stamp milestone date (never move backwards)."""
    from app.pipeline import DATE_COLUMNS, normalize_stage, stage_rank

    target = normalize_stage(stage)
    date = (activity_date or "").strip() or None
    row = conn.execute(
        """
        SELECT pipeline_stage, first_contact_at, rfq_at, rfs_at, conversion_at, deal_date
        FROM deals WHERE id = ? AND deleted_at IS NULL
        """,
        (deal_id,),
    ).fetchone()
    if not row:
        return
    current = normalize_stage(row["pipeline_stage"])
    new_stage = target if stage_rank(target) >= stage_rank(current) else current
    updates = {"pipeline_stage": new_stage, "updated_at": now_iso()}
    # Always ensure first contact has a date
    if not row["first_contact_at"]:
        updates["first_contact_at"] = date or row["deal_date"]
    col = DATE_COLUMNS[target]
    if date and not row[col]:
        updates[col] = date
    # Stamp intermediate empty milestones with this date when jumping ahead
    if date:
        for key in ("first_contact", "rfq", "rfs", "conversion"):
            if stage_rank(key) > stage_rank(target):
                break
            c = DATE_COLUMNS[key]
            if not row[c] and c not in updates:
                if key == "first_contact" or stage_rank(key) <= stage_rank(target):
                    if key == target or key == "first_contact":
                        updates.setdefault(c, date)
    sets = ", ".join(f"{k} = ?" for k in updates)
    conn.execute(
        f"UPDATE deals SET {sets} WHERE id = ?",
        (*updates.values(), deal_id),
    )


def set_deal_pipeline_stage(deal_id: int, stage: str, at_date: str = "") -> None:
    with get_db() as conn:
        apply_pipeline_progress(conn, deal_id, stage, at_date or None)


def _migrate_activity_deal_links(conn: sqlite3.Connection) -> None:
    """Link orphan activities to a deal only when exactly one deal matches."""
    conn.execute(
        """
        UPDATE activities SET deal_id = (
            SELECT d.id FROM deals d
            WHERE d.customer_id = activities.customer_id
              AND d.product_id = activities.product_id
              AND d.deleted_at IS NULL
            ORDER BY d.deal_date DESC, d.id DESC LIMIT 1
        )
        WHERE deal_id IS NULL
          AND customer_id IS NOT NULL
          AND product_id IS NOT NULL
          AND (
            SELECT COUNT(*) FROM deals d
            WHERE d.customer_id = activities.customer_id
              AND d.product_id = activities.product_id
              AND d.deleted_at IS NULL
          ) = 1
        """
    )
    conn.execute(
        """
        UPDATE activities SET deal_id = NULL
        WHERE deal_id IS NOT NULL
          AND customer_id IS NOT NULL
          AND product_id IS NOT NULL
          AND (
            SELECT COUNT(*) FROM deals d
            WHERE d.customer_id = activities.customer_id
              AND d.product_id = activities.product_id
              AND d.deleted_at IS NULL
          ) > 1
          AND deal_id = (
            SELECT d.id FROM deals d
            WHERE d.customer_id = activities.customer_id
              AND d.product_id = activities.product_id
              AND d.deleted_at IS NULL
            ORDER BY d.deal_date DESC, d.id DESC LIMIT 1
          )
        """
    )


def _infer_product_name(conn: sqlite3.Connection, customer_id: int) -> str:
    """Best-effort product for a company-only email when none was typed."""
    open_rows = conn.execute(
        """
        SELECT p.name FROM deals d
        JOIN products p ON p.id = d.product_id
        WHERE d.customer_id = ? AND d.status = 'open' AND d.archived = 0
          AND d.deleted_at IS NULL AND lower(p.name) != 'general'
        """,
        (customer_id,),
    ).fetchall()
    if len(open_rows) == 1:
        return open_rows[0]["name"]
    recent = conn.execute(
        """
        SELECT p.name FROM activities a
        JOIN products p ON p.id = a.product_id
        WHERE a.customer_id = ? AND lower(p.name) != 'general'
        ORDER BY a.activity_date DESC, a.id DESC LIMIT 1
        """,
        (customer_id,),
    ).fetchone()
    if recent:
        return recent["name"]
    lead = conn.execute(
        "SELECT products_interested FROM leads WHERE customer_id = ?", (customer_id,)
    ).fetchone()
    if lead and lead["products_interested"]:
        first = lead["products_interested"].split(",")[0].strip()
        if first and first.lower() != "general":
            return first
    latest_deal = conn.execute(
        """
        SELECT p.name FROM deals d
        JOIN products p ON p.id = d.product_id
        WHERE d.customer_id = ? AND d.deleted_at IS NULL
        ORDER BY d.deal_date DESC LIMIT 1
        """,
        (customer_id,),
    ).fetchone()
    return latest_deal["name"] if latest_deal else ""


def _resolve_company_only_link(
    conn: sqlite3.Connection,
    customer_id: int,
    product_name: str,
) -> tuple[Optional[int], int]:
    """Attach company-only entry to a product (and matching deal if one exists)."""
    name = product_name.strip()
    if not name:
        name = _infer_product_name(conn, customer_id)
    if not name:
        return None, upsert_product(conn, "General")
    pid = upsert_product(conn, name)
    lead = conn.execute(
        "SELECT id, products_interested FROM leads WHERE customer_id = ?", (customer_id,)
    ).fetchone()
    ts = now_iso()
    if lead:
        merged = _merge_products(lead["products_interested"], name)
        conn.execute(
            "UPDATE leads SET products_interested = ?, updated_at = ? WHERE id = ?",
            (merged, ts, lead["id"]),
        )
    open_deals = conn.execute(
        """
        SELECT d.id, d.product_id FROM deals d
        JOIN products p ON p.id = d.product_id
        WHERE d.customer_id = ? AND p.name = ? COLLATE NOCASE
          AND d.deleted_at IS NULL AND d.archived = 0 AND d.status = 'open'
        ORDER BY d.deal_date DESC, d.id DESC
        """,
        (customer_id, name),
    ).fetchall()
    if len(open_deals) == 1:
        return open_deals[0]["id"], open_deals[0]["product_id"]
    return None, pid


def migrate_to_leads_deals() -> None:
    """Build leads + deals from legacy engagements if not yet migrated."""
    with get_db() as conn:
        lead_count = conn.execute("SELECT COUNT(*) AS n FROM leads").fetchone()["n"]
        if lead_count:
            return
        eng_count = conn.execute("SELECT COUNT(*) AS n FROM engagements").fetchone()["n"]
        if not eng_count:
            return

        customers = conn.execute("SELECT id, name FROM customers").fetchall()
        for cust in customers:
            cid = cust["id"]
            rows = conn.execute(
                """
                SELECT e.contact, e.email, e.summary_notes, p.name AS product,
                       e.initial_request, e.sample_sent, e.quote_response,
                       e.po_number, e.updated_at, e.created_at
                FROM engagements e
                JOIN products p ON p.id = e.product_id
                WHERE e.customer_id = ?
                ORDER BY e.updated_at DESC
                """,
                (cid,),
            ).fetchall()
            if not rows:
                continue
            contact = email = notes = ""
            products = []
            for r in rows:
                if not contact and r["contact"]:
                    contact = r["contact"]
                if not email and r["email"]:
                    email = r["email"]
                if r["product"] and r["product"] not in products:
                    products.append(r["product"])
                if r["summary_notes"] and r["summary_notes"] not in (notes or ""):
                    notes = (notes + " " + r["summary_notes"]).strip() if notes else r["summary_notes"]
            ts = now_iso()
            cur = conn.execute(
                """
                INSERT INTO leads (
                    customer_id, contact, email, website, phone,
                    products_interested, notes, created_at, updated_at
                ) VALUES (?, ?, ?, '', '', ?, ?, ?, ?)
                """,
                (cid, contact, email, ", ".join(products), notes[:2000], ts, ts),
            )
            lead_id = cur.lastrowid
            for r in rows:
                pid = upsert_product(conn, r["product"])
                deal_date = (
                    r["initial_request"]
                    or r["quote_response"]
                    or r["sample_sent"]
                    or (r["updated_at"] or r["created_at"] or ts)[:10]
                )
                if not deal_date:
                    deal_date = ts[:10]
                status = "shipped" if r["sample_sent"] else "open"
                shipped = r["sample_sent"] if status == "shipped" else None
                conn.execute(
                    """
                    INSERT INTO deals (
                        lead_id, customer_id, product_id, po_number, deal_date,
                        status, shipped_date, notes, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        lead_id,
                        cid,
                        pid,
                        r["po_number"] or None,
                        str(deal_date)[:10],
                        status,
                        str(shipped)[:10] if shipped else None,
                        r["summary_notes"] or "",
                        ts,
                        ts,
                    ),
                )


def upsert_customer(conn: sqlite3.Connection, name: str) -> int:
    name = name.strip()
    row = conn.execute(
        "SELECT id FROM customers WHERE name = ? COLLATE NOCASE", (name,)
    ).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO customers (name, created_at) VALUES (?, ?)",
        (name, now_iso()),
    )
    return cur.lastrowid


def upsert_product(conn: sqlite3.Connection, name: str) -> int:
    name = name.strip()
    row = conn.execute(
        "SELECT id FROM products WHERE name = ? COLLATE NOCASE", (name,)
    ).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO products (name, created_at) VALUES (?, ?)",
        (name, now_iso()),
    )
    return cur.lastrowid


def period_start(period: str) -> Optional[str]:
    today = datetime.utcnow().date()
    if period == "all":
        return None
    if period == "week":
        start = today - timedelta(days=today.weekday())
    elif period == "month":
        start = today.replace(day=1)
    elif period == "quarter":
        q_month = ((today.month - 1) // 3) * 3 + 1
        start = today.replace(month=q_month, day=1)
    elif period == "year":
        start = today.replace(month=1, day=1)
    else:
        start = today - timedelta(days=30)
    return start.isoformat()


def calendar_month_bounds(ym: str) -> Optional[tuple[str, str]]:
    """Parse YYYY-MM into inclusive (start_date, end_date) ISO strings."""
    raw = (ym or "").strip()
    if len(raw) < 7 or raw[4] != "-":
        return None
    try:
        y, m = int(raw[:4]), int(raw[5:7])
        if not (1990 <= y <= 2100 and 1 <= m <= 12):
            return None
        start = date(y, m, 1)
        if m == 12:
            end = date(y, 12, 31)
        else:
            end = date(y, m + 1, 1) - timedelta(days=1)
        return start.isoformat(), end.isoformat()
    except (TypeError, ValueError):
        return None


def list_customers() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, name FROM customers ORDER BY name COLLATE NOCASE"
        ).fetchall()
    return [dict(r) for r in rows]


def list_products(include_retired: bool = True) -> list[dict]:
    clauses = []
    if not include_retired:
        clauses.append("status != 'retired'")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with get_db() as conn:
        rows = conn.execute(
            f"""
            SELECT id, name, status FROM products
            {where}
            ORDER BY
                CASE status
                    WHEN 'active' THEN 0
                    WHEN 'development' THEN 1
                    WHEN 'retired' THEN 2
                    ELSE 3
                END,
                name COLLATE NOCASE
            """
        ).fetchall()
    return [dict(r) for r in rows]


def _merge_products(existing: str, new_product: str) -> str:
    parts = [p.strip() for p in (existing or "").split(",") if p.strip()]
    if new_product.strip() and new_product.strip() not in parts:
        parts.append(new_product.strip())
    return ", ".join(parts)


def _migrate_contacts_from_leads(conn: sqlite3.Connection) -> None:
    """One-time: copy legacy lead contact fields into contacts table."""
    has_any = conn.execute("SELECT 1 FROM contacts LIMIT 1").fetchone()
    if has_any:
        return
    for row in conn.execute(
        "SELECT customer_id, contact, email, phone, created_at, updated_at FROM leads"
    ).fetchall():
        if not (row["contact"] or row["email"] or row["phone"]):
            continue
        conn.execute(
            """
            INSERT INTO contacts (
                customer_id, contact, email, phone, is_primary, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 1, ?, ?)
            """,
            (
                row["customer_id"],
                row["contact"] or "",
                row["email"] or "",
                row["phone"] or "",
                row["created_at"],
                row["updated_at"],
            ),
        )


def _ensure_company_lead(conn: sqlite3.Connection, customer_id: int) -> int:
    row = conn.execute(
        "SELECT id FROM leads WHERE customer_id = ?", (customer_id,)
    ).fetchone()
    if row:
        return row["id"]
    ts = now_iso()
    cur = conn.execute(
        """
        INSERT INTO leads (
            customer_id, contact, email, website, phone,
            products_interested, notes, created_at, updated_at
        ) VALUES (?, '', '', '', '', '', '', ?, ?)
        """,
        (customer_id, ts, ts),
    )
    return cur.lastrowid


def _sync_lead_from_primary(conn: sqlite3.Connection, customer_id: int) -> None:
    primary = conn.execute(
        """
        SELECT contact, email, phone FROM contacts
        WHERE customer_id = ? AND is_primary = 1
        ORDER BY id LIMIT 1
        """,
        (customer_id,),
    ).fetchone()
    lead_id = _ensure_company_lead(conn, customer_id)
    ts = now_iso()
    if primary:
        conn.execute(
            """
            UPDATE leads SET contact = ?, email = ?, phone = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                primary["contact"] or "",
                primary["email"] or "",
                primary["phone"] or "",
                ts,
                lead_id,
            ),
        )
    else:
        conn.execute(
            "UPDATE leads SET contact = '', email = '', phone = ?, updated_at = ? WHERE id = ?",
            ("", ts, lead_id),
        )


def list_contacts(customer_id: int) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, customer_id, contact, email, phone, is_primary,
                   created_at, updated_at
            FROM contacts
            WHERE customer_id = ?
            ORDER BY is_primary DESC, contact COLLATE NOCASE, id
            """,
            (customer_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def create_contact(customer_id: int, data: dict[str, Any], is_primary: bool = False) -> int:
    with get_db() as conn:
        _ensure_company_lead(conn, customer_id)
        ts = now_iso()
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM contacts WHERE customer_id = ?",
            (customer_id,),
        ).fetchone()["n"]
        make_primary = is_primary or n == 0
        if make_primary:
            conn.execute(
                "UPDATE contacts SET is_primary = 0 WHERE customer_id = ?",
                (customer_id,),
            )
        cur = conn.execute(
            """
            INSERT INTO contacts (
                customer_id, contact, email, phone, is_primary, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                customer_id,
                data.get("contact", "").strip(),
                data.get("email", "").strip(),
                data.get("phone", "").strip(),
                1 if make_primary else 0,
                ts,
                ts,
            ),
        )
        contact_id = cur.lastrowid
        if make_primary:
            _sync_lead_from_primary(conn, customer_id)
        return contact_id


def update_contact(contact_id: int, data: dict[str, Any]) -> Optional[int]:
    """Update contact; returns customer_id."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT customer_id FROM contacts WHERE id = ?", (contact_id,)
        ).fetchone()
        if not row:
            return None
        cid = row["customer_id"]
        ts = now_iso()
        conn.execute(
            """
            UPDATE contacts SET contact = ?, email = ?, phone = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                data.get("contact", "").strip(),
                data.get("email", "").strip(),
                data.get("phone", "").strip(),
                ts,
                contact_id,
            ),
        )
        if data.get("is_primary"):
            conn.execute(
                "UPDATE contacts SET is_primary = 0 WHERE customer_id = ?",
                (cid,),
            )
            conn.execute(
                "UPDATE contacts SET is_primary = 1 WHERE id = ?", (contact_id,)
            )
            _sync_lead_from_primary(conn, cid)
        return cid


def delete_contact(contact_id: int) -> Optional[int]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT customer_id, is_primary FROM contacts WHERE id = ?",
            (contact_id,),
        ).fetchone()
        if not row:
            return None
        cid = row["customer_id"]
        was_primary = row["is_primary"]
        conn.execute("DELETE FROM contacts WHERE id = ?", (contact_id,))
        if was_primary:
            other = conn.execute(
                """
                SELECT id FROM contacts WHERE customer_id = ?
                ORDER BY id LIMIT 1
                """,
                (cid,),
            ).fetchone()
            if other:
                conn.execute(
                    "UPDATE contacts SET is_primary = 1 WHERE id = ?", (other["id"],)
                )
            _sync_lead_from_primary(conn, cid)
        return cid


def create_lead(data: dict[str, Any]) -> int:
    with get_db() as conn:
        cid = upsert_customer(conn, data["company"])
        ts = now_iso()
        existing = conn.execute(
            "SELECT id, products_interested FROM leads WHERE customer_id = ?", (cid,)
        ).fetchone()
        products = data.get("products_interested", "")
        if existing:
            products = _merge_products(existing["products_interested"], products)
            conn.execute(
                """
                UPDATE leads SET website = COALESCE(NULLIF(?, ''), website),
                    products_interested = ?, notes = COALESCE(NULLIF(?, ''), notes),
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    data.get("website", ""),
                    products,
                    data.get("notes", ""),
                    ts,
                    existing["id"],
                ),
            )
            lead_id = existing["id"]
        else:
            cur = conn.execute(
                """
                INSERT INTO leads (
                    customer_id, contact, email, website, phone,
                    products_interested, notes, created_at, updated_at
                ) VALUES (?, '', '', ?, '', ?, ?, ?, ?)
                """,
                (
                    cid,
                    data.get("website", ""),
                    products,
                    data.get("notes", ""),
                    ts,
                    ts,
                ),
            )
            lead_id = cur.lastrowid
        if data.get("contact") or data.get("email") or data.get("phone"):
            n = conn.execute(
                "SELECT COUNT(*) AS n FROM contacts WHERE customer_id = ?", (cid,)
            ).fetchone()["n"]
            if n == 0:
                create_contact(
                    cid,
                    {
                        "contact": data.get("contact", ""),
                        "email": data.get("email", ""),
                        "phone": data.get("phone", ""),
                    },
                    is_primary=True,
                )
            else:
                _sync_lead_from_primary(conn, cid)
        return lead_id


def update_company_profile(customer_id: int, data: dict[str, Any]) -> None:
    with get_db() as conn:
        lead_id = _ensure_company_lead(conn, customer_id)
    update_lead(lead_id, data)


def update_lead(lead_id: int, data: dict[str, Any]) -> None:
    """Update company-level lead fields (website, products, notes)."""
    ts = now_iso()
    with get_db() as conn:
        conn.execute(
            """
            UPDATE leads SET website = ?, products_interested = ?, notes = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                data.get("website", ""),
                data.get("products_interested", ""),
                data.get("notes", ""),
                ts,
                lead_id,
            ),
        )


def search_leads_contacts(
    company: str = "",
    product: str = "",
    q: str = "",
) -> list[dict]:
    clauses = ["1=1"]
    params: list[Any] = []
    if company:
        clauses.append("c.name LIKE ? COLLATE NOCASE")
        params.append(f"%{company}%")
    if product:
        clauses.append("l.products_interested LIKE ? COLLATE NOCASE")
        params.append(f"%{product}%")
    if q:
        clauses.append(
            """(
                c.name LIKE ? OR l.website LIKE ? OR l.products_interested LIKE ?
                OR l.notes LIKE ?
                OR COALESCE(pc.contact, l.contact) LIKE ?
                OR COALESCE(pc.email, l.email) LIKE ?
                OR COALESCE(pc.phone, l.phone) LIKE ?
                OR EXISTS (
                    SELECT 1 FROM contacts ct
                    WHERE ct.customer_id = l.customer_id
                      AND (ct.contact LIKE ? OR ct.email LIKE ? OR ct.phone LIKE ?)
                )
            )"""
        )
        params.extend([f"%{q}%"] * 10)
    sql = f"""
        SELECT l.id,
               COALESCE(pc.contact, l.contact) AS contact,
               COALESCE(pc.email, l.email) AS email,
               l.website, COALESCE(pc.phone, l.phone) AS phone,
               l.products_interested, l.notes, l.updated_at,
               c.name AS company, c.id AS customer_id,
               (SELECT COUNT(*) FROM contacts ct WHERE ct.customer_id = c.id) AS contact_count
        FROM leads l
        JOIN customers c ON c.id = l.customer_id
        LEFT JOIN contacts pc ON pc.customer_id = c.id AND pc.is_primary = 1
        WHERE {' AND '.join(clauses)}
        ORDER BY c.name COLLATE NOCASE
    """
    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def get_lead_by_company(company: str) -> Optional[dict]:
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT l.*, c.name AS company
            FROM leads l
            JOIN customers c ON c.id = l.customer_id
            WHERE c.name = ? COLLATE NOCASE
            """,
            (company,),
        ).fetchone()
    return dict(row) if row else None


def create_deal(data: dict[str, Any]) -> int:
    with get_db() as conn:
        cid = upsert_customer(conn, data["company"])
        lead = conn.execute(
            "SELECT id FROM leads WHERE customer_id = ?", (cid,)
        ).fetchone()
        if not lead:
            ts = now_iso()
            cur = conn.execute(
                """
                INSERT INTO leads (customer_id, contact, email, website, phone,
                    products_interested, notes, created_at, updated_at)
                VALUES (?, '', '', '', '', ?, '', ?, ?)
                """,
                (cid, data.get("product", ""), ts, ts),
            )
            lead_id = cur.lastrowid
        else:
            lead_id = lead["id"]
            if data.get("product"):
                row = conn.execute(
                    "SELECT products_interested FROM leads WHERE id = ?", (lead_id,)
                ).fetchone()
                merged = _merge_products(row["products_interested"], data["product"])
                conn.execute(
                    "UPDATE leads SET products_interested = ?, updated_at = ? WHERE id = ?",
                    (merged, now_iso(), lead_id),
                )
        pid = upsert_product(conn, data["product"])
        from app.product_labels import initial_deal_product_short_name

        psn = initial_deal_product_short_name(conn, pid) or None
        ts = now_iso()
        qref = default_quote_ref(conn, cid, pid, data.get("quote_ref", ""))
        from app.pipeline import normalize_stage

        stage = normalize_stage(data.get("pipeline_stage") or "first_contact")
        start = data["deal_date"]
        cur = conn.execute(
            """
            INSERT INTO deals (
                lead_id, customer_id, product_id, product_short_name, po_number, quote_ref,
                quantity, quantity_unit, price, price_unit, deal_date, status, value, notes,
                pipeline_stage, first_contact_at, rfq_at, rfs_at, conversion_at,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                lead_id,
                cid,
                pid,
                psn,
                data.get("po_number") or None,
                qref,
                data.get("quantity", "").strip(),
                normalize_quantity_unit(
                    data.get("quantity_unit", "MT"),
                    data.get("quantity_unit_other", ""),
                ),
                data.get("price", "").strip(),
                (data.get("price_unit") or "/MT").strip(),
                start,
                format_deal_value(
                    data.get("quantity", ""),
                    data.get("price", ""),
                    data.get("price_unit", "/MT"),
                    normalize_quantity_unit(
                        data.get("quantity_unit", "MT"),
                        data.get("quantity_unit_other", ""),
                    ),
                )
                or data.get("value", ""),
                data.get("notes", ""),
                stage,
                start,
                start if stage in ("rfq", "rfs", "conversion") else None,
                start if stage in ("rfs", "conversion") else None,
                start if stage == "conversion" else None,
                ts,
                ts,
            ),
        )
        deal_id = cur.lastrowid
        _finalize_deal_id_ref(conn, deal_id, data.get("quote_ref", ""))
        return deal_id


def update_deal_fields(
    deal_id: int,
    notes: str = "",
    po_number: str = "",
    quote_ref: str = "",
    quantity: str = "",
    quantity_unit: str = "MT",
    quantity_unit_other: str = "",
    price: str = "",
    price_unit: str = "/MT",
    po_date: str = "",
    packing: str = "",
    gbl_invoice: str = "",
    gbl_invoice_date: str = "",
    container_number: str = "",
    vessel_name: str = "",
    etd_india: str = "",
    transit_time: str = "",
    destination: str = "",
    eta: str = "",
    incoterms: str = "",
    payment_terms: str = "",
    shipment_timing: str = "",
    insurance_amount: str = "",
    insurance_currency: str = "USD",
    ocean_freight_amount: str = "",
    ocean_freight_currency: str = "USD",
    commission_rate: str = "",
    fob_currency: str = "USD",
    product_short_name: str = "",
) -> None:
    unit = (price_unit or "/MT").strip() or "/MT"
    qty_unit = normalize_quantity_unit(quantity_unit, quantity_unit_other)
    value = format_deal_value(quantity, price, unit, qty_unit)
    commercial_total = compute_commercial_total(quantity, price)
    ins_cur = (insurance_currency or "USD").strip().upper()
    if ins_cur not in ("INR", "USD"):
        ins_cur = "USD"
    freight_cur = (ocean_freight_currency or "USD").strip().upper()
    if freight_cur not in ("INR", "USD"):
        freight_cur = "USD"
    fob_val = compute_fob_value(commercial_total, insurance_amount, ocean_freight_amount)
    comm_amt = compute_commission_amount(fob_val, commission_rate)
    fob_cur = normalize_deal_currency(fob_currency or freight_cur or "USD")
    psn = (product_short_name or "").strip()
    shipping_vals = {
        "po_date": po_date.strip(),
        "packing": packing.strip(),
        "gbl_invoice": gbl_invoice.strip(),
        "gbl_invoice_date": gbl_invoice_date.strip(),
        "container_number": container_number.strip(),
        "vessel_name": vessel_name.strip(),
        "etd_india": etd_india.strip(),
        "transit_time": transit_time.strip(),
        "destination": destination.strip(),
        "eta": eta.strip(),
    }
    with get_db() as conn:
        if not psn or psn.lower() == "none":
            row = conn.execute(
                """
                SELECT p.name, p.trade_name FROM deals d
                JOIN products p ON p.id = d.product_id
                WHERE d.id = ? AND d.deleted_at IS NULL
                """,
                (deal_id,),
            ).fetchone()
            if row:
                from app.product_labels import product_row_document_label

                psn = product_row_document_label(dict(row))
        conn.execute(
            """
            UPDATE deals SET
                po_number = ?, quote_ref = ?, quantity = ?, quantity_unit = ?,
                price = ?, price_unit = ?,
                value = ?, notes = ?,
                po_date = ?, packing = ?, gbl_invoice = ?, gbl_invoice_date = ?,
                container_number = ?, vessel_name = ?, etd_india = ?, transit_time = ?,
                destination = ?, eta = ?,
                incoterms = ?, payment_terms = ?, shipment_timing = ?,
                commercial_total = ?, insurance_amount = ?, insurance_currency = ?,
                ocean_freight_amount = ?, ocean_freight_currency = ?,
                fob_value = ?, fob_currency = ?,
                commission_rate = ?, commission_amount = ?,
                product_short_name = ?,
                updated_at = ?
            WHERE id = ? AND deleted_at IS NULL
            """,
            (
                po_number.strip() or None,
                quote_ref.strip(),
                quantity.strip(),
                qty_unit,
                price.strip(),
                unit,
                value,
                notes.strip(),
                shipping_vals["po_date"],
                shipping_vals["packing"],
                shipping_vals["gbl_invoice"],
                shipping_vals["gbl_invoice_date"],
                shipping_vals["container_number"],
                shipping_vals["vessel_name"],
                shipping_vals["etd_india"],
                shipping_vals["transit_time"],
                shipping_vals["destination"],
                shipping_vals["eta"],
                incoterms.strip(),
                payment_terms.strip(),
                shipment_timing.strip(),
                commercial_total,
                insurance_amount.strip(),
                ins_cur,
                ocean_freight_amount.strip(),
                freight_cur,
                fob_val,
                fob_cur,
                commission_rate.strip(),
                comm_amt,
                psn or None,
                now_iso(),
                deal_id,
            ),
        )


def _shipping_po_key(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _ci_shipping_base(variant: Any) -> str:
    if str(variant or "").strip().lower() == "gbbv":
        return "/generate/gbbv-commission-invoices"
    return "/generate/commission-invoices"


def _float_ship(val: Any, default: float = 0.0) -> float:
    if val is None or val == "":
        return default
    try:
        return float(str(val).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def list_shipping_summary(
    company: str = "",
    product: str = "",
    status: str = "all",
    q: str = "",
) -> list[dict]:
    """Deal shipping rows; selected CIs become source of truth for the same PO/deal.

    No double entries. Discrepancy = CI commission − deal commission when CI is linked.
    """
    clauses = ["d.deleted_at IS NULL"]
    params: list[Any] = []
    if status == "archived":
        clauses.append("d.archived = 1")
    elif status == "open":
        clauses.append("d.archived = 0 AND d.status = 'open'")
    elif status == "shipped":
        clauses.append("d.status = 'shipped'")
    elif status == "lost":
        clauses.append("d.status = 'lost'")
    else:
        clauses.append("d.archived = 0")
    if company:
        clauses.append("c.name LIKE ? COLLATE NOCASE")
        params.append(f"%{company}%")
    if product:
        clauses.append("p.name LIKE ? COLLATE NOCASE")
        params.append(f"%{product}%")
    if q:
        clauses.append(
            """(
                c.name LIKE ? OR p.name LIKE ? OR d.po_number LIKE ?
                OR d.po_date LIKE ? OR d.quantity LIKE ? OR d.packing LIKE ?
                OR d.gbl_invoice LIKE ? OR d.gbl_invoice_date LIKE ?
                OR d.container_number LIKE ? OR d.vessel_name LIKE ?
                OR d.etd_india LIKE ? OR d.transit_time LIKE ?
                OR d.destination LIKE ? OR d.eta LIKE ?
            )"""
        )
        params.extend([f"%{q}%"] * 13)

    from app.pipeline import infer_stage_from_row, stage_label

    sql = f"""
        SELECT d.id AS deal_id, d.status, d.po_number, d.po_date, d.quantity, d.quantity_unit, d.packing,
               d.gbl_invoice, d.gbl_invoice_date, d.container_number, d.vessel_name,
               d.etd_india, d.transit_time, d.destination, d.eta,
               d.commission_amount, d.fob_currency,
               d.pipeline_stage, d.first_contact_at, d.rfq_at, d.rfs_at, d.conversion_at,
               c.name AS company, p.name AS product, p.id AS product_id
        FROM deals d
        JOIN customers c ON c.id = d.customer_id
        JOIN products p ON p.id = d.product_id
        WHERE {' AND '.join(clauses)}
        ORDER BY c.name COLLATE NOCASE ASC, p.name COLLATE NOCASE ASC, d.id ASC
    """
    with get_db() as conn:
        deal_rows = [dict(r) for r in conn.execute(sql, params).fetchall()]

        for row in deal_rows:
            row["source"] = "deal"
            row["source_label"] = "Deal"
            row["ci_id"] = None
            row["ci_number"] = ""
            row["ci_base"] = ""
            row["commission"] = _float_ship(row.get("commission_amount"))
            row["deal_commission"] = _float_ship(row.get("commission_amount"))
            row["discrepancy"] = None
            row["currency"] = row.get("fob_currency") or "USD"
            stage = infer_stage_from_row(row)
            row["pipeline_stage"] = stage
            row["stage_label"] = stage_label(stage)

        by_deal: dict[int, dict] = {}
        by_po: dict[str, dict] = {}
        for row in deal_rows:
            by_deal[int(row["deal_id"])] = row
            po_k = _shipping_po_key(row.get("po_number"))
            if po_k and po_k not in by_po:
                by_po[po_k] = row

        # Table may not exist yet on fresh DBs before CI schema upgrade
        try:
            ci_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='commission_invoices'"
            ).fetchone()
        except Exception:
            ci_exists = None
        if not ci_exists:
            return deal_rows

        ci_sql = """
            SELECT ci.id, ci.deal_id, ci.customer_order_no, ci.invoice_number, ci.invoice_date,
                   ci.variant, ci.container_numbers, ci.shipment_date, ci.port_of_loading,
                   ci.qty_unit, ci.value_currency, ci.fob_currency, ci.bill_to_name,
                   COALESCE((
                       SELECT ROUND(SUM(COALESCE(li.commission_value, 0)), 2)
                       FROM commission_invoice_line_items li
                       WHERE li.commission_invoice_id = ci.id
                   ), 0) AS total_commission,
                   COALESCE((
                       SELECT ROUND(SUM(COALESCE(li.quantity, 0)), 4)
                       FROM commission_invoice_line_items li
                       WHERE li.commission_invoice_id = ci.id
                   ), 0) AS ci_quantity,
                   (
                       SELECT li.product_description
                       FROM commission_invoice_line_items li
                       WHERE li.commission_invoice_id = ci.id
                       ORDER BY li.sort_order, li.id LIMIT 1
                   ) AS ci_product,
                   (
                       SELECT li.end_customer
                       FROM commission_invoice_line_items li
                       WHERE li.commission_invoice_id = ci.id
                       ORDER BY li.sort_order, li.id LIMIT 1
                   ) AS ci_end_customer,
                   (
                       SELECT li.gbl_invoice_number
                       FROM commission_invoice_line_items li
                       WHERE li.commission_invoice_id = ci.id
                       ORDER BY li.sort_order, li.id LIMIT 1
                   ) AS ci_gbl_invoice,
                   (
                       SELECT li.shipment_date
                       FROM commission_invoice_line_items li
                       WHERE li.commission_invoice_id = ci.id
                       ORDER BY li.sort_order, li.id LIMIT 1
                   ) AS ci_line_shipment,
                   c.name AS customer_name,
                   d.po_number AS deal_po_number,
                   d.commission_amount AS deal_commission_amount,
                   d.status AS deal_status,
                   d.po_date AS deal_po_date,
                   d.quantity AS deal_quantity,
                   d.quantity_unit AS deal_quantity_unit,
                   d.packing AS deal_packing,
                   d.gbl_invoice AS deal_gbl_invoice,
                   d.gbl_invoice_date AS deal_gbl_invoice_date,
                   d.container_number AS deal_container,
                   d.vessel_name AS deal_vessel,
                   d.etd_india AS deal_etd,
                   d.transit_time AS deal_transit,
                   d.destination AS deal_destination,
                   d.eta AS deal_eta,
                   d.fob_currency AS deal_fob_currency,
                   d.pipeline_stage AS deal_pipeline_stage,
                   d.first_contact_at AS deal_first_contact_at,
                   d.rfq_at AS deal_rfq_at,
                   d.rfs_at AS deal_rfs_at,
                   d.conversion_at AS deal_conversion_at,
                   p.name AS deal_product,
                   cust.name AS deal_company
            FROM commission_invoices ci
            LEFT JOIN customers c ON c.id = ci.customer_id
            LEFT JOIN deals d ON d.id = ci.deal_id AND d.deleted_at IS NULL
            LEFT JOIN products p ON p.id = d.product_id
            LEFT JOIN customers cust ON cust.id = d.customer_id
            WHERE COALESCE(ci.show_on_summary, 0) = 1
            ORDER BY ci.updated_at DESC, ci.id DESC
        """
        try:
            ci_rows = [dict(r) for r in conn.execute(ci_sql).fetchall()]
        except Exception:
            # show_on_summary column may be missing until upgrade runs
            return deal_rows

    claimed: set[int] = set()  # deal_ids claimed by a CI
    claimed_pos: set[str] = set()
    out: list[dict] = []
    company_f = (company or "").strip().casefold()
    product_f = (product or "").strip().casefold()
    q_f = (q or "").strip().casefold()

    def _passes_filters(company_name: str, product_name: str, haystack: str) -> bool:
        if company_f and company_f not in (company_name or "").casefold():
            return False
        if product_f and product_f not in (product_name or "").casefold():
            return False
        if q_f and q_f not in (haystack or "").casefold():
            return False
        return True

    for ci in ci_rows:
        deal_id = ci.get("deal_id")
        po = (ci.get("customer_order_no") or ci.get("deal_po_number") or "").strip()
        po_k = _shipping_po_key(po)
        match = None
        if deal_id and int(deal_id) in by_deal:
            match = by_deal[int(deal_id)]
        elif po_k and po_k in by_po:
            match = by_po[po_k]

        ci_amt = _float_ship(ci.get("total_commission"))
        deal_amt = _float_ship(
            (match or {}).get("commission_amount")
            if match
            else ci.get("deal_commission_amount")
        )
        discrepancy = round(ci_amt - deal_amt, 2) if (ci_amt or deal_amt) else None

        company_name = (
            (ci.get("ci_end_customer") or "").strip()
            or (match or {}).get("company")
            or (ci.get("deal_company") or "").strip()
            or (ci.get("customer_name") or "").strip()
            or (ci.get("bill_to_name") or "").strip()
            or "—"
        )
        product_name = (
            (ci.get("ci_product") or "").strip()
            or (match or {}).get("product")
            or (ci.get("deal_product") or "").strip()
            or "—"
        )
        qty = ci.get("ci_quantity") or None
        if qty is not None and _float_ship(qty) == 0:
            qty = (match or {}).get("quantity") or ci.get("deal_quantity")
        qty_unit = (
            (ci.get("qty_unit") or "").strip()
            or (match or {}).get("quantity_unit")
            or ci.get("deal_quantity_unit")
            or "MT"
        )
        gbl = (ci.get("ci_gbl_invoice") or "").strip() or (
            (match or {}).get("gbl_invoice") or ci.get("deal_gbl_invoice") or ""
        )
        container = (ci.get("container_numbers") or "").strip() or (
            (match or {}).get("container_number") or ci.get("deal_container") or ""
        )
        ship_date = (
            (ci.get("ci_line_shipment") or ci.get("shipment_date") or "").strip()[:10]
        )
        hay = " ".join(
            str(x or "")
            for x in (
                company_name,
                product_name,
                po,
                gbl,
                container,
                ci.get("invoice_number"),
                ship_date,
            )
        )
        if not _passes_filters(company_name, product_name, hay):
            continue

        # Status filter: CI-only rows only for all/open; matched deals already filtered
        if match is None and status not in ("all", "open", ""):
            continue

        stage_row = {
            "status": (match or {}).get("status") or ci.get("deal_status") or "open",
            "pipeline_stage": (match or {}).get("pipeline_stage") or ci.get("deal_pipeline_stage"),
            "first_contact_at": (match or {}).get("first_contact_at") or ci.get("deal_first_contact_at"),
            "rfq_at": (match or {}).get("rfq_at") or ci.get("deal_rfq_at"),
            "rfs_at": (match or {}).get("rfs_at") or ci.get("deal_rfs_at"),
            "conversion_at": (match or {}).get("conversion_at") or ci.get("deal_conversion_at"),
        }
        stage = infer_stage_from_row(stage_row) if (
            stage_row.get("pipeline_stage")
            or stage_row.get("first_contact_at")
            or stage_row.get("rfq_at")
            or stage_row.get("rfs_at")
            or stage_row.get("conversion_at")
            or stage_row.get("status") in ("shipped", "lost")
        ) else "conversion"  # CI on summary implies commercial conversion track
        row = {
            "deal_id": int(deal_id) if deal_id else ((match or {}).get("deal_id")),
            "status": stage_row["status"],
            "pipeline_stage": stage,
            "stage_label": stage_label(stage),
            "po_number": po or (match or {}).get("po_number") or "",
            "po_date": (match or {}).get("po_date") or ci.get("deal_po_date") or "",
            "quantity": qty if qty not in (None, "") else ((match or {}).get("quantity") or ci.get("deal_quantity")),
            "quantity_unit": qty_unit,
            "packing": (match or {}).get("packing") or ci.get("deal_packing") or "",
            "gbl_invoice": gbl,
            "gbl_invoice_date": (match or {}).get("gbl_invoice_date")
            or ci.get("deal_gbl_invoice_date")
            or ship_date
            or "",
            "container_number": container,
            "vessel_name": (match or {}).get("vessel_name") or ci.get("deal_vessel") or "",
            "etd_india": (match or {}).get("etd_india")
            or ci.get("deal_etd")
            or ship_date
            or "",
            "transit_time": (match or {}).get("transit_time") or ci.get("deal_transit") or "",
            "destination": (match or {}).get("destination")
            or ci.get("deal_destination")
            or (ci.get("port_of_loading") or ""),
            "eta": (match or {}).get("eta") or ci.get("deal_eta") or "",
            "company": company_name,
            "product": product_name,
            "product_id": (match or {}).get("product_id"),
            "source": "ci",
            "source_label": "Commission invoice",
            "ci_id": ci.get("id"),
            "ci_number": ci.get("invoice_number") or "",
            "ci_base": _ci_shipping_base(ci.get("variant")),
            "commission": ci_amt,
            "deal_commission": deal_amt,
            "discrepancy": discrepancy,
            "currency": ci.get("value_currency")
            or ci.get("fob_currency")
            or (match or {}).get("fob_currency")
            or "USD",
        }

        if match is not None:
            claimed.add(int(match["deal_id"]))
            po_claim = _shipping_po_key(match.get("po_number"))
            if po_claim:
                claimed_pos.add(po_claim)
        if deal_id:
            claimed.add(int(deal_id))
        if po_k:
            claimed_pos.add(po_k)
        out.append(row)

    for row in deal_rows:
        did = int(row["deal_id"])
        po_k = _shipping_po_key(row.get("po_number"))
        if did in claimed:
            continue
        if po_k and po_k in claimed_pos:
            continue
        out.append(row)

    out.sort(
        key=lambda r: (
            (r.get("company") or "").casefold(),
            (r.get("product") or "").casefold(),
            int(r.get("deal_id") or 0),
            int(r.get("ci_id") or 0),
        )
    )
    return out


def archive_deal(deal_id: int) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE deals SET archived = 1, updated_at = ? WHERE id = ? AND deleted_at IS NULL",
            (now_iso(), deal_id),
        )


def unarchive_deal(deal_id: int) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE deals SET archived = 0, updated_at = ? WHERE id = ?",
            (now_iso(), deal_id),
        )


def delete_deal(deal_id: int) -> None:
    from app.deal_files import delete_all_deal_files

    delete_all_deal_files(deal_id)
    with get_db() as conn:
        conn.execute(
            "UPDATE deals SET deleted_at = ?, updated_at = ? WHERE id = ?",
            (now_iso(), now_iso(), deal_id),
        )


def bulk_deal_action(
    deal_ids: list[int],
    action: str,
    lost_reason: str = "",
    closed_date: Optional[str] = None,
) -> int:
    count = 0
    for deal_id in deal_ids:
        if action == "archive":
            archive_deal(deal_id)
            count += 1
        elif action == "unarchive":
            unarchive_deal(deal_id)
            count += 1
        elif action == "delete":
            delete_deal(deal_id)
            count += 1
        elif action == "lost":
            mark_deal_lost(deal_id, closed_date, lost_reason)
            count += 1
        elif action == "shipped":
            mark_deal_shipped(deal_id, closed_date)
            count += 1
    return count


def _activity_period_clause(start: str) -> tuple[str, list[Any]]:
    """Deals with logged activity or closed (shipped/lost) in the period."""
    clause = """
        (
            EXISTS (
                SELECT 1 FROM activities a
                WHERE a.deal_id = d.id AND a.activity_date >= ?
            )
            OR (d.closed_date IS NOT NULL AND d.closed_date >= ?)
        )
    """
    return clause, [start, start]


def list_active_leads(
    status: str = "all",
    period: str = "month",
    company: str = "",
    product: str = "",
    po: str = "",
    q: str = "",
    stage: str = "all",
    sort: str = "stage",
    direction: str = "asc",
    attention_days: int | None = None,
    month: str = "",
) -> list[dict]:
    """One row per deal (or lead-only product) with activity in the period.

    ``month`` (YYYY-MM) overrides relative ``period`` and filters to that
    calendar month (inclusive). When set, only deals/leads with activity
    (or deal_date) in that month are shown.
    """
    from app.pipeline import infer_stage_from_row, normalize_stage, sort_active_leads

    month_bounds = calendar_month_bounds(month)
    if month_bounds:
        start, end = month_bounds
    else:
        start = period_start(period)
        end = None

    result: list[dict] = []
    stage_filter = (stage or "all").strip().lower()
    if stage_filter not in ("all", ""):
        stage_filter = normalize_stage(stage_filter)
    else:
        stage_filter = "all"

    # Needs-attention preset: focus on open work
    if attention_days is not None and status in ("all", ""):
        status = "open"

    deal_clauses = ["d.deleted_at IS NULL"]
    deal_params: list[Any] = []

    def _append_activity_range(clauses: list[str], params: list[Any], col: str = "a.activity_date") -> None:
        if start:
            clauses.append(f"{col} >= ?")
            params.append(start)
        if end:
            clauses.append(f"{col} <= ?")
            params.append(end)

    # Specific month: restrict to deals touched (or dated) in that month.
    # Relative period: for non-open/all outcomes, require activity since start.
    if month_bounds:
        in_month = []
        in_params: list[Any] = []
        _append_activity_range(in_month, in_params, "d.deal_date")
        act_bits = ["a.deal_id = d.id"]
        act_params_inner: list[Any] = []
        _append_activity_range(act_bits, act_params_inner, "a.activity_date")
        deal_clauses.append(
            f"""(
                ({' AND '.join(in_month)})
                OR EXISTS (
                    SELECT 1 FROM activities a
                    WHERE {' AND '.join(act_bits)}
                )
            )"""
        )
        deal_params.extend(in_params + act_params_inner)
    elif start and status not in ("open", "all"):
        deal_clauses.append(
            """EXISTS (
                SELECT 1 FROM activities a
                WHERE a.deal_id = d.id AND a.activity_date >= ?
            )"""
        )
        deal_params.append(start)
    if status == "archived":
        deal_clauses.append("d.archived = 1")
    elif status == "open":
        deal_clauses.append("d.archived = 0 AND d.status = 'open'")
    elif status == "shipped":
        deal_clauses.append("d.status = 'shipped'")
    elif status == "lost":
        deal_clauses.append("d.status = 'lost'")
    else:
        deal_clauses.append("d.archived = 0")
    if company:
        deal_clauses.append("c.name LIKE ? COLLATE NOCASE")
        deal_params.append(f"%{company}%")
    if product:
        deal_clauses.append("p.name LIKE ? COLLATE NOCASE")
        deal_params.append(f"%{product}%")
    if po:
        deal_clauses.append("d.po_number LIKE ?")
        deal_params.append(f"%{po}%")
    if q:
        deal_clauses.append(
            """(
                c.name LIKE ? OR p.name LIKE ? OR d.quote_ref LIKE ?
                OR d.notes LIKE ? OR d.value LIKE ? OR d.quantity LIKE ? OR d.price LIKE ?
                OR d.po_number LIKE ?
            )"""
        )
        deal_params.extend([f"%{q}%"] * 8)

    period_act_bits: list[str] = []
    act_params: list[Any] = []
    if start:
        period_act_bits.append("a.activity_date >= ?")
        act_params.append(start)
    if end:
        period_act_bits.append("a.activity_date <= ?")
        act_params.append(end)
    period_act = (" AND " + " AND ".join(period_act_bits)) if period_act_bits else ""
    deal_sql = f"""
        SELECT d.id AS deal_id, d.deal_date, d.status, d.archived, d.po_number, d.quote_ref,
               d.quantity, d.quantity_unit, d.price, d.price_unit, d.value, d.notes, d.closed_date,
               d.pipeline_stage, d.first_contact_at, d.rfq_at, d.rfs_at, d.conversion_at,
               c.name AS company, p.name AS product, d.customer_id, d.product_id,
               COALESCE(l.contact, '') AS contact,
               COALESCE(
                   (
                       SELECT MAX(a.activity_date) FROM activities a
                       WHERE a.deal_id = d.id{period_act}
                   ),
                   d.deal_date
               ) AS last_activity_date,
               (
                   SELECT COUNT(*) FROM activities a
                   WHERE a.deal_id = d.id{period_act}
               ) AS activity_count,
               (
                   SELECT COALESCE(a.comment, a.description, '')
                   FROM activities a
                   WHERE a.deal_id = d.id{period_act}
                   ORDER BY a.activity_date DESC, a.id DESC LIMIT 1
               ) AS last_activity
        FROM deals d
        JOIN customers c ON c.id = d.customer_id
        JOIN products p ON p.id = d.product_id
        LEFT JOIN leads l ON l.customer_id = d.customer_id
        WHERE {' AND '.join(deal_clauses)}
        ORDER BY company COLLATE NOCASE ASC, product COLLATE NOCASE ASC, d.id ASC
    """
    with get_db() as conn:
        deal_query_params = act_params * 3 + deal_params
        for row in conn.execute(deal_sql, deal_query_params).fetchall():
            item = dict(row)
            item["pipeline_stage"] = infer_stage_from_row(item)
            result.append(item)

        if status in ("all", "open") and stage_filter in ("all", "first_contact"):
            lead_clauses = [
                "a.deal_id IS NULL",
                """NOT EXISTS (
                    SELECT 1 FROM deals d
                    WHERE d.customer_id = a.customer_id
                      AND d.product_id = a.product_id
                      AND d.deleted_at IS NULL
                      AND d.archived = 0
                      AND d.status = 'open'
                )""",
            ]
            lead_params: list[Any] = []
            if start:
                lead_clauses.append("a.activity_date >= ?")
                lead_params.append(start)
            if end:
                lead_clauses.append("a.activity_date <= ?")
                lead_params.append(end)
            if company:
                lead_clauses.append("c.name LIKE ? COLLATE NOCASE")
                lead_params.append(f"%{company}%")
            if product:
                lead_clauses.append("p.name LIKE ? COLLATE NOCASE")
                lead_params.append(f"%{product}%")
            if q:
                lead_clauses.append(
                    """(
                        c.name LIKE ? OR p.name LIKE ?
                        OR a.comment LIKE ? OR a.description LIKE ?
                    )"""
                )
                lead_params.extend([f"%{q}%"] * 4)
            date_filter_bits: list[str] = []
            date_filter_params: list[Any] = []
            if start:
                date_filter_bits.append("a2.activity_date >= ?")
                date_filter_params.append(start)
            if end:
                date_filter_bits.append("a2.activity_date <= ?")
                date_filter_params.append(end)
            date_filter = (" AND " + " AND ".join(date_filter_bits)) if date_filter_bits else ""
            lead_sql = f"""
                SELECT c.name AS company, p.name AS product, a.customer_id,
                       a.product_id,
                       COALESCE(l.contact, '') AS contact,
                       MAX(a.activity_date) AS last_activity_date,
                       MIN(a.activity_date) AS first_contact_at,
                       COUNT(*) AS activity_count,
                       (
                           SELECT COALESCE(a2.comment, a2.description, '')
                           FROM activities a2
                           WHERE a2.customer_id = a.customer_id
                             AND a2.product_id = a.product_id
                             AND a2.deal_id IS NULL{date_filter}
                           ORDER BY a2.activity_date DESC, a2.id DESC LIMIT 1
                       ) AS last_activity
                FROM activities a
                JOIN customers c ON c.id = a.customer_id
                JOIN products p ON p.id = a.product_id
                LEFT JOIN leads l ON l.customer_id = a.customer_id
                WHERE {' AND '.join(lead_clauses)}
                GROUP BY a.customer_id, a.product_id
            """
            lead_query_params = lead_params + date_filter_params
            for row in conn.execute(lead_sql, lead_query_params).fetchall():
                item = dict(row)
                item["deal_id"] = None
                item["status"] = "lead"
                item["pipeline_stage"] = "first_contact"
                item["rfq_at"] = None
                item["rfs_at"] = None
                item["conversion_at"] = None
                item["quote_ref"] = ""
                item["po_number"] = None
                item["quantity"] = ""
                item["quantity_unit"] = "MT"
                item["price"] = ""
                item["price_unit"] = "/MT"
                item["notes"] = ""
                item["deal_date"] = item["last_activity_date"]
                result.append(item)

    if stage_filter != "all":
        result = [
            r for r in result
            if normalize_stage(r.get("pipeline_stage")) == stage_filter
        ]

    if attention_days is not None:
        cutoff = (datetime.utcnow().date() - timedelta(days=int(attention_days))).isoformat()
        filtered: list[dict] = []
        for r in result:
            if r.get("status") in ("shipped", "lost"):
                continue
            last = r.get("last_activity_date") or r.get("deal_date") or ""
            # Stale touch, or still early in funnel
            stale = (not last) or last <= cutoff
            early = normalize_stage(r.get("pipeline_stage")) in (
                "first_contact",
                "rfq",
            )
            if stale or early:
                filtered.append(r)
        result = filtered

    return sort_active_leads(result, sort=sort, direction=direction)



def group_active_leads(rows: list[dict], view: str = "company") -> list[dict]:
    """Group active-lead rows for display by company or product."""
    if view == "product":
        sort_key = lambda x: (
            (x.get("product") or "").casefold(),
            (x.get("company") or "").casefold(),
            x.get("deal_id") or 0,
        )
        group_key = "product"
    else:
        sort_key = lambda x: (
            (x.get("company") or "").casefold(),
            (x.get("product") or "").casefold(),
            x.get("deal_id") or 0,
        )
        group_key = "company"

    sorted_rows = sorted(rows, key=sort_key)
    groups: list[dict] = []
    current_label: str | None = None
    current_rows: list[dict] = []

    for row in sorted_rows:
        label = row.get(group_key) or "—"
        if label != current_label:
            if current_rows:
                groups.append(
                    {
                        "label": current_label,
                        "rows": current_rows,
                        "product_id": current_rows[0].get("product_id"),
                        "customer_id": current_rows[0].get("customer_id"),
                    }
                )
            current_label = label
            current_rows = [row]
        else:
            current_rows.append(row)

    if current_rows:
        groups.append(
            {
                "label": current_label,
                "rows": current_rows,
                "product_id": current_rows[0].get("product_id"),
                "customer_id": current_rows[0].get("customer_id"),
            }
        )
    return groups


def list_deals(
    status: str = "all",
    period: str = "month",
    company: str = "",
    product: str = "",
    po: str = "",
    q: str = "",
) -> list[dict]:
    clauses = ["d.deleted_at IS NULL"]
    params: list[Any] = []
    if status == "archived":
        clauses.append("d.archived = 1")
    else:
        clauses.append("d.archived = 0")
        if status and status != "all":
            clauses.append("d.status = ?")
            params.append(status)
    start = period_start(period)
    if start:
        period_clause, period_params = _activity_period_clause(start)
        clauses.append(period_clause)
        params.extend(period_params)
    if company:
        clauses.append("c.name LIKE ? COLLATE NOCASE")
        params.append(f"%{company}%")
    if product:
        clauses.append("p.name LIKE ? COLLATE NOCASE")
        params.append(f"%{product}%")
    if po:
        clauses.append("d.po_number LIKE ?")
        params.append(f"%{po}%")
    if q:
        clauses.append(
            """(
                c.name LIKE ? OR p.name LIKE ? OR d.po_number LIKE ?
                OR d.notes LIKE ? OR d.value LIKE ? OR d.quantity LIKE ?
                OR d.price LIKE ?
            )"""
        )
        params.extend([f"%{q}%"] * 7)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    activity_start = start or "1900-01-01"
    sql = f"""
        SELECT d.id, d.po_number, d.quantity, d.quantity_unit, d.price, d.price_unit,
               d.deal_date, d.status, d.archived,
               d.shipped_date, d.closed_date, d.value, d.notes, d.updated_at,
               c.name AS company, p.name AS product,
               (
                   SELECT MAX(a.activity_date) FROM activities a
                   WHERE a.deal_id = d.id AND a.activity_date >= ?
               ) AS last_activity_date,
               (
                   SELECT COUNT(*) FROM activities a
                   WHERE a.deal_id = d.id AND a.activity_date >= ?
               ) AS activity_count,
               (
                   SELECT COALESCE(a.comment, a.description, a.activity, '')
                   FROM activities a
                   WHERE a.deal_id = d.id AND a.activity_date >= ?
                   ORDER BY a.activity_date DESC, a.id DESC
                   LIMIT 1
               ) AS last_activity
        FROM deals d
        JOIN customers c ON c.id = d.customer_id
        JOIN products p ON p.id = d.product_id
        {where}
        ORDER BY COALESCE(last_activity_date, d.closed_date, d.deal_date) DESC, d.id DESC
    """
    extra = [activity_start, activity_start, activity_start]
    with get_db() as conn:
        rows = conn.execute(sql, extra + params).fetchall()
    return [dict(r) for r in rows]


def _close_deal(
    deal_id: int,
    status: str,
    closed_date: Optional[str] = None,
    lost_reason: str = "",
) -> None:
    closed = closed_date or datetime.utcnow().date().isoformat()
    ts = now_iso()
    with get_db() as conn:
        if lost_reason:
            row = conn.execute(
                "SELECT notes FROM deals WHERE id = ?", (deal_id,)
            ).fetchone()
            notes = row["notes"] or ""
            suffix = f"[Lost {closed}] {lost_reason}"
            notes = f"{notes}\n{suffix}".strip() if notes else suffix
            conn.execute(
                """
                UPDATE deals SET status = ?, closed_date = ?, shipped_date = NULL,
                    notes = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, closed, notes, ts, deal_id),
            )
        elif status == "shipped":
            conn.execute(
                """
                UPDATE deals SET status = 'shipped', shipped_date = ?, closed_date = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (closed, closed, ts, deal_id),
            )
        else:
            conn.execute(
                """
                UPDATE deals SET status = ?, closed_date = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, closed, ts, deal_id),
            )


def mark_deal_shipped(deal_id: int, shipped_date: Optional[str] = None) -> None:
    _close_deal(deal_id, "shipped", shipped_date)


def mark_deal_lost(
    deal_id: int,
    closed_date: Optional[str] = None,
    lost_reason: str = "",
) -> None:
    _close_deal(deal_id, "lost", closed_date, lost_reason)


def reopen_deal(deal_id: int) -> None:
    """Revert a shipped or lost deal back to open status."""
    ts = now_iso()
    with get_db() as conn:
        conn.execute(
            """
            UPDATE deals
            SET status = 'open', shipped_date = NULL, closed_date = NULL, updated_at = ?
            WHERE id = ?
            """,
            (ts, deal_id),
        )


def list_deals_for_commission(
    *,
    fiscal_year: int = 0,
    month: int = 0,
    date_from: str = "",
    date_to: str = "",
    product: str = "",
    company: str = "",
    status: str = "all",
) -> list[dict]:
    """Deals for commission Excel / data-request template (open, shipped, lost)."""
    clauses = ["d.deleted_at IS NULL", "d.archived = 0"]
    params: list[Any] = []

    if status and status != "all":
        clauses.append("d.status = ?")
        params.append(status)

    if product:
        clauses.append("p.name = ? COLLATE NOCASE")
        params.append(product.strip())

    if company:
        clauses.append("c.name = ? COLLATE NOCASE")
        params.append(company.strip())

    date_expr = (
        "substr(COALESCE(NULLIF(d.shipped_date,''), NULLIF(d.gbl_invoice_date,''), d.deal_date), 1, 10)"
    )

    if date_from:
        clauses.append(f"{date_expr} >= ?")
        params.append(str(date_from).strip()[:10])
    if date_to:
        clauses.append(f"{date_expr} <= ?")
        params.append(str(date_to).strip()[:10])

    if month and fiscal_year and not date_from and not date_to:
        cal_yr = fiscal_year - 1 if month >= 4 else fiscal_year
        month_key = f"{cal_yr:04d}-{month:02d}"
        clauses.append(f"substr({date_expr}, 1, 7) = ?")
        params.append(month_key)

    where = " AND ".join(clauses)
    sql = f"""
        SELECT d.id, d.po_number, d.po_date, d.packing, d.quote_ref,
               d.quantity, d.quantity_unit, d.price, d.price_unit,
               d.deal_date, d.status,
               d.shipped_date, d.closed_date, d.value, d.notes,
               d.gbl_invoice, d.gbl_invoice_date, d.vessel_name,
               d.container_number, d.etd_india, d.transit_time,
               d.destination, d.eta,
               d.commercial_total, d.insurance_amount, d.insurance_currency,
               d.ocean_freight_amount, d.ocean_freight_currency,
               d.fob_value, d.fob_currency, d.commission_rate, d.commission_amount,
               c.name AS company, p.name AS product,
               p.trade_name AS catalog_trade_name,
               d.product_short_name
        FROM deals d
        JOIN customers c ON c.id = d.customer_id
        JOIN products p ON p.id = d.product_id
        WHERE {where}
        ORDER BY COALESCE(d.shipped_date, d.gbl_invoice_date, d.deal_date), d.id
    """
    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def list_commission_products() -> list[str]:
    """Distinct products that appear on deals (for report filters)."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT p.name
            FROM deals d
            JOIN products p ON p.id = d.product_id
            WHERE d.deleted_at IS NULL AND d.archived = 0
            ORDER BY p.name COLLATE NOCASE
            """
        ).fetchall()
    return [r["name"] for r in rows]


def list_commission_companies() -> list[str]:
    """Distinct customers that appear on deals (for report filters)."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT c.name
            FROM deals d
            JOIN customers c ON c.id = d.customer_id
            WHERE d.deleted_at IS NULL AND d.archived = 0
            ORDER BY c.name COLLATE NOCASE
            """
        ).fetchall()
    return [r["name"] for r in rows]


def deal_counts_for_customer(customer_id: int) -> dict:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT status, COUNT(*) AS n FROM deals
            WHERE customer_id = ? AND deleted_at IS NULL AND archived = 0
            GROUP BY status
            """,
            (customer_id,),
        ).fetchall()
    counts = {"open": 0, "shipped": 0, "lost": 0}
    for r in rows:
        counts[r["status"]] = r["n"]
    counts["total"] = sum(counts.values())
    return counts


def list_deals_for_company(company: str, active_only: bool = True) -> list[dict]:
    extra = "AND d.deleted_at IS NULL AND d.archived = 0" if active_only else "AND d.deleted_at IS NULL"
    with get_db() as conn:
        rows = conn.execute(
            f"""
            SELECT d.id, d.deal_date, d.status, d.po_number, d.quote_ref, d.closed_date,
                   d.quantity, d.quantity_unit, d.price, d.price_unit, d.notes,
                   d.pipeline_stage, d.first_contact_at, d.rfq_at, d.rfs_at, d.conversion_at,
                   d.po_date, d.packing, d.gbl_invoice, d.gbl_invoice_date,
                   d.container_number, d.vessel_name, d.etd_india, d.transit_time,
                   d.destination, d.eta,
                   d.incoterms, d.payment_terms, d.shipment_timing,
                   d.commercial_total, d.insurance_amount, d.insurance_currency,
                   d.ocean_freight_amount, d.ocean_freight_currency,
                   d.fob_value, d.fob_currency, d.commission_rate, d.commission_amount,
                   p.name AS product
            FROM deals d
            JOIN customers c ON c.id = d.customer_id
            JOIN products p ON p.id = d.product_id
            WHERE c.name = ? COLLATE NOCASE {extra}
            ORDER BY d.deal_date DESC, d.id DESC
            """,
            (company.strip(),),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["label"] = deal_picker_label(d)
        out.append(d)
    return out


def deals_for_activity_edit(
    company: str,
    include_deal_ids: Iterable[int] = (),
) -> list[dict]:
    """Deal picker options, including soft-deleted deals already linked to activities."""
    by_id = {d["id"]: d for d in list_deals_for_company(company, active_only=False)}
    extra_ids = {int(did) for did in include_deal_ids if did}
    missing = extra_ids - set(by_id)
    if missing:
        with get_db() as conn:
            for did in missing:
                row = conn.execute(
                    """
                    SELECT d.id, d.deal_date, d.status, d.po_number, d.quote_ref,
                           d.closed_date, d.quantity, d.quantity_unit, d.price,
                           d.price_unit, d.deleted_at, p.name AS product
                    FROM deals d
                    JOIN customers c ON c.id = d.customer_id
                    JOIN products p ON p.id = d.product_id
                    WHERE d.id = ? AND c.name = ? COLLATE NOCASE
                    """,
                    (did, company.strip()),
                ).fetchone()
                if row:
                    d = dict(row)
                    d["label"] = deal_picker_label(d)
                    if d.get("deleted_at"):
                        d["label"] = f"{d['label']} (removed deal)"
                    by_id[did] = d
    return sorted(
        by_id.values(),
        key=lambda x: (x.get("deal_date") or "", x["id"]),
        reverse=True,
    )


def _format_activity_description(data: dict[str, Any]) -> str:
    parts = []
    if data.get("email_from"):
        parts.append(f"From: {data['email_from']}")
    if data.get("email_to"):
        parts.append(f"To: {data['email_to']}")
    if data.get("email_subject"):
        parts.append(f"Re: {data['email_subject']}")
    return "\n".join(parts)


def _insert_activity(conn: sqlite3.Connection, data: dict[str, Any]) -> int:
    cid = data["customer_id"]
    deal_id = data.get("deal_id")
    pid = data["product_id"]
    if deal_id:
        drow = conn.execute(
            "SELECT product_id, lead_id FROM deals WHERE id = ?", (deal_id,)
        ).fetchone()
        if drow:
            pid = drow["product_id"]
            data["product_id"] = pid
    lead = conn.execute(
        "SELECT id FROM leads WHERE customer_id = ?", (cid,)
    ).fetchone()
    lead_id = lead["id"] if lead else None
    if deal_id and not lead_id:
        drow = conn.execute(
            "SELECT lead_id FROM deals WHERE id = ?", (deal_id,)
        ).fetchone()
        if drow:
            lead_id = drow["lead_id"]
    ts = now_iso()
    description = data.get("description") or _format_activity_description(data)
    cur = conn.execute(
        """
        INSERT INTO activities (
            lead_id, deal_id, customer_id, product_id,
            activity_date, channel, activity, type, value,
            comment, description, email_subject, email_from, email_to,
            source, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            lead_id,
            data.get("deal_id"),
            cid,
            data["product_id"],
            data["activity_date"],
            data.get("channel", ""),
            data.get("activity", "Note"),
            data.get("type", "Update"),
            data.get("value", ""),
            data.get("comment", ""),
            description,
            data.get("email_subject", ""),
            data.get("email_from", ""),
            data.get("email_to", ""),
            data.get("source", "manual"),
            ts,
        ),
    )
    if lead_id:
        conn.execute("UPDATE leads SET updated_at = ? WHERE id = ?", (ts, lead_id))
    if data.get("deal_id"):
        conn.execute(
            "UPDATE deals SET updated_at = ? WHERE id = ?",
            (ts, data["deal_id"]),
        )
    return cur.lastrowid


def log_update(data: dict[str, Any]) -> dict:
    """
    Unified portal: log email/activity and optionally link to existing or new deal.
    link_mode: existing | new | none
    """
    with get_db() as conn:
        cid = upsert_customer(conn, data["company"])
        link_mode = data.get("link_mode", "none")
        deal_id = None
        created_deal = False
        product_name = data.get("product", "").strip()

        if link_mode == "existing" and data.get("deal_id"):
            deal_id = int(data["deal_id"])
            row = conn.execute(
                """
                SELECT d.product_id, p.name AS product
                FROM deals d JOIN products p ON p.id = d.product_id
                WHERE d.id = ? AND d.customer_id = ?
                """,
                (deal_id, cid),
            ).fetchone()
            if not row:
                raise ValueError("Deal not found for this company")
            product_name = row["product"]
            pid = row["product_id"]
            patch_deal_commercial(conn, deal_id, data)
            if data.get("deal_notes_append"):
                old = conn.execute(
                    "SELECT notes FROM deals WHERE id = ?", (deal_id,)
                ).fetchone()["notes"]
                notes = f"{old}\n{data['deal_notes_append']}".strip() if old else data["deal_notes_append"]
                conn.execute(
                    "UPDATE deals SET notes = ?, updated_at = ? WHERE id = ?",
                    (notes, now_iso(), deal_id),
                )
        elif link_mode == "new":
            if not product_name:
                raise ValueError("Product required for new deal")
            pid = upsert_product(conn, product_name)
            from app.product_labels import initial_deal_product_short_name

            psn = initial_deal_product_short_name(conn, pid) or None
            lead = conn.execute(
                "SELECT id, products_interested FROM leads WHERE customer_id = ?",
                (cid,),
            ).fetchone()
            ts = now_iso()
            if not lead:
                cur = conn.execute(
                    """
                    INSERT INTO leads (customer_id, contact, email, website, phone,
                        products_interested, notes, created_at, updated_at)
                    VALUES (?, '', '', '', '', ?, '', ?, ?)
                    """,
                    (cid, product_name, ts, ts),
                )
                lead_id = cur.lastrowid
            else:
                lead_id = lead["id"]
                merged = _merge_products(lead["products_interested"], product_name)
                conn.execute(
                    "UPDATE leads SET products_interested = ?, updated_at = ? WHERE id = ?",
                    (merged, ts, lead_id),
                )
            comm = commercial_from_data(data)
            qref = default_quote_ref(
                conn, cid, pid, data.get("quote_ref", "")
            )
            from app.pipeline import normalize_stage, stage_from_channel

            stage = normalize_stage(
                data.get("pipeline_stage")
                or stage_from_channel(data.get("channel"))
            )
            start = data["deal_date"]
            cur = conn.execute(
                """
                INSERT INTO deals (
                    lead_id, customer_id, product_id, product_short_name, po_number, quote_ref,
                    quantity, quantity_unit, price, price_unit, deal_date, status, value, notes,
                    pipeline_stage, first_contact_at, rfq_at, rfs_at, conversion_at,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lead_id,
                    cid,
                    pid,
                    psn,
                    comm["po_number"] or None,
                    qref,
                    comm["quantity"],
                    comm["quantity_unit"],
                    comm["price"],
                    comm["price_unit"],
                    start,
                    comm["value"],
                    data.get("deal_notes", ""),
                    stage,
                    start,
                    start if stage in ("rfq", "rfs", "conversion") else None,
                    start if stage in ("rfs", "conversion") else None,
                    start if stage == "conversion" else None,
                    ts,
                    ts,
                ),
            )
            deal_id = cur.lastrowid
            _finalize_deal_id_ref(conn, deal_id, data.get("quote_ref", ""))
            created_deal = True
        else:
            deal_id, pid = _resolve_company_only_link(conn, cid, product_name)

        comment = data.get("comment", "").strip()
        if not comment and data.get("email_subject"):
            comment = data["email_subject"]

        activity_id = _insert_activity(
            conn,
            {
                "customer_id": cid,
                "deal_id": deal_id,
                "product_id": pid,
                "activity_date": data["activity_date"],
                "channel": data.get("channel", "Note"),
                "activity": data.get("activity") or data.get("channel", "Note"),
                "type": data.get("type", ""),
                "value": data.get("value", ""),
                "comment": comment,
                "description": data.get("description", ""),
                "email_subject": data.get("email_subject", ""),
                "email_from": data.get("email_from", ""),
                "email_to": data.get("email_to", ""),
                "source": "portal",
            },
        )

        if deal_id:
            from app.pipeline import normalize_stage, stage_from_channel

            stage = normalize_stage(
                data.get("pipeline_stage")
                or stage_from_channel(data.get("channel"))
            )
            apply_pipeline_progress(
                conn, deal_id, stage, data.get("activity_date") or data.get("deal_date")
            )

        return {
            "activity_id": activity_id,
            "deal_id": deal_id,
            "created_deal": created_deal,
            "company": data["company"],
        }


def add_activity(data: dict[str, Any]) -> int:
    result = log_update(
        {
            "company": data["customer"],
            "link_mode": "existing" if data.get("deal_id") else "none",
            "deal_id": data.get("deal_id"),
            "product": data.get("product", ""),
            "activity_date": data["activity_date"],
            "channel": data.get("channel", "Note"),
            "activity": data.get("activity") or data.get("channel", "Note"),
            "type": "",
            "value": data.get("value", ""),
            "comment": data.get("comment", ""),
            "email_subject": data.get("email_subject", ""),
            "email_from": data.get("email_from", ""),
            "email_to": data.get("email_to", ""),
        }
    )
    return result["activity_id"]


def get_deal_detail(deal_id: int) -> Optional[dict]:
    with get_db() as conn:
        deal = conn.execute(
            """
            SELECT d.*, c.name AS company, p.name AS product,
                   p.trade_name AS catalog_trade_name
            FROM deals d
            JOIN customers c ON c.id = d.customer_id
            JOIN products p ON p.id = d.product_id
            WHERE d.id = ? AND d.deleted_at IS NULL
            """,
            (deal_id,),
        ).fetchone()
        if not deal:
            return None
        activities = conn.execute(
            """
            SELECT a.id, a.activity_date, a.channel, a.activity, a.type,
                   a.comment, a.description, a.email_subject, a.email_from, a.email_to,
                   a.value, a.deal_id, p.name AS product
            FROM activities a
            JOIN products p ON p.id = a.product_id
            WHERE a.deal_id = ?
            ORDER BY a.activity_date DESC, a.id DESC
            """,
            (deal_id,),
        ).fetchall()
        unlinked = conn.execute(
            """
            SELECT a.id, a.activity_date, a.channel, a.comment, a.description
            FROM activities a
            WHERE a.customer_id = ? AND a.product_id = ? AND a.deal_id IS NULL
            ORDER BY a.activity_date DESC, a.id DESC
            """,
            (deal["customer_id"], deal["product_id"]),
        ).fetchall()
    return {
        "deal": dict(deal),
        "activities": [dict(a) for a in activities],
        "unlinked_activities": [dict(a) for a in unlinked],
    }


def _activities_grouped(customer_id: int, product: str = "") -> dict:
    clauses = ["a.customer_id = ?"]
    params: list[Any] = [customer_id]
    if product:
        clauses.append("p.name = ? COLLATE NOCASE")
        params.append(product.strip())
    where = " AND ".join(clauses)
    with get_db() as conn:
        rows = conn.execute(
            f"""
            SELECT a.id, a.activity_date, a.channel, a.activity, a.type,
                   a.comment, a.description, a.email_subject, a.email_from, a.email_to,
                   a.value, a.deal_id, a.product_id,
                   p.name AS product,
                   d.deal_date, d.status AS deal_status, d.po_number
            FROM activities a
            JOIN products p ON p.id = a.product_id
            LEFT JOIN deals d ON d.id = a.deal_id
            WHERE {where}
            ORDER BY a.activity_date DESC, a.id DESC
            """,
            params,
        ).fetchall()
    company_level: list[dict] = []
    by_deal: dict[int, dict] = {}
    for r in rows:
        row = dict(r)
        if row["deal_id"]:
            did = row["deal_id"]
            if did not in by_deal:
                by_deal[did] = {
                    "deal_id": did,
                    "product": row["product"],
                    "deal_date": row["deal_date"],
                    "deal_status": row["deal_status"],
                    "po_number": row["po_number"],
                    "activities": [],
                }
            by_deal[did]["activities"].append(row)
        else:
            company_level.append(row)
    deal_groups = sorted(
        by_deal.values(),
        key=lambda g: (g["deal_date"] or "", g["deal_id"]),
        reverse=True,
    )
    return {"company_level": company_level, "deal_groups": deal_groups}


def _resolve_activity_link(
    conn: sqlite3.Connection,
    customer_id: int,
    data: dict[str, Any],
    allow_deleted_deal_id: Optional[int] = None,
) -> tuple[Optional[int], int, Optional[int]]:
    """Returns deal_id, product_id, lead_id for an activity after link_mode change."""
    link_mode = data.get("link_mode", "none")
    deal_id: Optional[int] = None
    lead_id: Optional[int] = None
    product_name = (data.get("product") or "").strip()

    if link_mode == "existing":
        if not data.get("deal_id"):
            raise ValueError("Pick a deal to attach this entry to")
        deal_id = int(data["deal_id"])
        allow_deleted = allow_deleted_deal_id is not None and deal_id == allow_deleted_deal_id
        sql = """
            SELECT d.product_id, d.lead_id
            FROM deals d
            WHERE d.id = ? AND d.customer_id = ?
        """
        if not allow_deleted:
            sql += " AND d.deleted_at IS NULL"
        drow = conn.execute(sql, (deal_id, customer_id)).fetchone()
        if not drow:
            raise ValueError("Deal not found for this company")
        pid = drow["product_id"]
        lead_id = drow["lead_id"]
    elif link_mode == "new":
        if not product_name:
            raise ValueError("Product is required for a new deal")
        deal_date = data.get("deal_date") or data.get("activity_date")
        if not deal_date:
            raise ValueError("Deal start date is required")
        pid = upsert_product(conn, product_name)
        from app.product_labels import initial_deal_product_short_name

        psn = initial_deal_product_short_name(conn, pid) or None
        lead = conn.execute(
            "SELECT id, products_interested FROM leads WHERE customer_id = ?",
            (customer_id,),
        ).fetchone()
        ts = now_iso()
        if not lead:
            cur = conn.execute(
                """
                INSERT INTO leads (customer_id, contact, email, website, phone,
                    products_interested, notes, created_at, updated_at)
                VALUES (?, '', '', '', '', ?, '', ?, ?)
                """,
                (customer_id, product_name, ts, ts),
            )
            lead_id = cur.lastrowid
        else:
            lead_id = lead["id"]
            merged = _merge_products(lead["products_interested"], product_name)
            conn.execute(
                "UPDATE leads SET products_interested = ?, updated_at = ? WHERE id = ?",
                (merged, ts, lead_id),
            )
        comm = commercial_from_data(data)
        qref = default_quote_ref(
            conn, customer_id, pid, data.get("quote_ref", "")
        )
        cur = conn.execute(
            """
            INSERT INTO deals (
                lead_id, customer_id, product_id, product_short_name, po_number, quote_ref,
                quantity, quantity_unit, price, price_unit, deal_date, status, value, notes,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?)
            """,
            (
                lead_id,
                customer_id,
                pid,
                psn,
                comm["po_number"] or None,
                qref,
                comm["quantity"],
                comm["quantity_unit"],
                comm["price"],
                comm["price_unit"],
                deal_date,
                comm["value"],
                data.get("deal_notes", ""),
                ts,
                ts,
            ),
        )
        deal_id = cur.lastrowid
        _finalize_deal_id_ref(conn, deal_id, data.get("quote_ref", ""))
    else:
        deal_id, pid = _resolve_company_only_link(conn, customer_id, product_name)

    return deal_id, pid, lead_id


def update_activity(activity_id: int, data: dict[str, Any]) -> Optional[str]:
    """Update activity fields and entry type (deal link); returns company name."""
    data = dict(data)
    data["activity_date"] = normalize_activity_date(data.get("activity_date", ""))
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT a.customer_id, a.deal_id, c.name AS company
            FROM activities a
            JOIN customers c ON c.id = a.customer_id
            WHERE a.id = ?
            """,
            (activity_id,),
        ).fetchone()
        if not row:
            return None
        existing_deal_id = row["deal_id"]
        if "link_mode" not in data:
            data["link_mode"] = "existing" if existing_deal_id else "none"
        if data.get("link_mode") == "existing" and not (data.get("deal_id") or "").strip():
            if existing_deal_id:
                data["deal_id"] = str(existing_deal_id)
        deal_id, pid, lead_id = _resolve_activity_link(
            conn,
            row["customer_id"],
            data,
            allow_deleted_deal_id=existing_deal_id,
        )
        channel = data.get("channel", "Note").strip() or "Note"
        comment = data.get("comment", "").strip()
        ts = now_iso()
        conn.execute(
            """
            UPDATE activities SET
                activity_date = ?,
                channel = ?,
                activity = ?,
                type = ?,
                comment = ?,
                description = '',
                deal_id = ?,
                product_id = ?,
                lead_id = ?
            WHERE id = ?
            """,
            (
                data["activity_date"],
                channel,
                channel,
                "",
                comment,
                deal_id,
                pid,
                lead_id,
                activity_id,
            ),
        )
        if lead_id:
            conn.execute(
                "UPDATE leads SET updated_at = ? WHERE id = ?", (ts, lead_id)
            )
        if deal_id:
            conn.execute(
                "UPDATE deals SET updated_at = ? WHERE id = ?", (ts, deal_id)
            )
        return row["company"]


def attach_activity_to_deal(activity_id: int, deal_id: int) -> bool:
    """Link an unassigned activity to a specific deal (same company + product)."""
    with get_db() as conn:
        deal = conn.execute(
            """
            SELECT customer_id, product_id FROM deals
            WHERE id = ? AND deleted_at IS NULL
            """,
            (deal_id,),
        ).fetchone()
        act = conn.execute(
            "SELECT customer_id, product_id, deal_id FROM activities WHERE id = ?",
            (activity_id,),
        ).fetchone()
        if not deal or not act:
            return False
        if act["deal_id"] is not None:
            return False
        if deal["customer_id"] != act["customer_id"]:
            return False
        if deal["product_id"] != act["product_id"]:
            return False
        conn.execute(
            "UPDATE activities SET deal_id = ? WHERE id = ?", (deal_id, activity_id)
        )
        conn.execute(
            "UPDATE deals SET updated_at = ? WHERE id = ?", (now_iso(), deal_id)
        )
        return True


def delete_activity(activity_id: int) -> Optional[str]:
    """Delete activity; returns company name for redirect."""
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT c.name AS company FROM activities a
            JOIN customers c ON c.id = a.customer_id
            WHERE a.id = ?
            """,
            (activity_id,),
        ).fetchone()
        if not row:
            return None
        conn.execute("DELETE FROM activities WHERE id = ?", (activity_id,))
        return row["company"]


def delete_customer(customer_id: int) -> Optional[str]:
    """Remove company and all leads, deals, engagements, and activities."""
    from app.deal_files import delete_all_deal_files

    # Step 1: read-only — get customer info and deal IDs (no write lock held).
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, name FROM customers WHERE id = ?", (customer_id,)
        ).fetchone()
        if not row:
            return None
        cid = row["id"]
        name = row["name"]
        deal_ids = [
            r["id"]
            for r in conn.execute(
                "SELECT id FROM deals WHERE customer_id = ?", (cid,)
            ).fetchall()
        ]

    # Step 2: delete uploaded files for each deal (opens its own DB connections).
    # Must happen OUTSIDE the outer get_db() block to avoid nested write-lock deadlock.
    for did in deal_ids:
        delete_all_deal_files(did)

    # Step 3: delete all DB rows in a single transaction.
    with get_db() as conn:
        conn.execute("DELETE FROM activities WHERE customer_id = ?", (cid,))
        conn.execute("DELETE FROM deals WHERE customer_id = ?", (cid,))
        conn.execute("DELETE FROM engagements WHERE customer_id = ?", (cid,))
        conn.execute("DELETE FROM contacts WHERE customer_id = ?", (cid,))
        conn.execute("DELETE FROM leads WHERE customer_id = ?", (cid,))
        conn.execute("DELETE FROM customers WHERE id = ?", (cid,))
    return name


def recent_activities(limit: int = 15, period: str = "all") -> list[dict]:
    start = period_start(period)
    clauses = []
    params: list[Any] = []
    if start:
        clauses.append("a.activity_date >= ?")
        params.append(start)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT a.id, a.activity_date, a.activity, a.type, a.value, a.comment,
               a.description, c.name AS customer, p.name AS product
        FROM activities a
        JOIN customers c ON c.id = a.customer_id
        JOIN products p ON p.id = a.product_id
        {where}
        ORDER BY a.activity_date DESC, a.id DESC
        LIMIT ?
    """
    params.append(limit)
    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def summary_by_product(period: str = "all") -> list[dict]:
    start = period_start(period)
    clauses = []
    params: list[Any] = []
    if start:
        clauses.append("a.activity_date >= ?")
        params.append(start)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT p.name AS product,
               COUNT(DISTINCT a.customer_id) AS customers,
               COUNT(a.id) AS activities,
               MAX(a.activity_date) AS last_activity
        FROM activities a
        JOIN products p ON p.id = a.product_id
        {where}
        GROUP BY p.id
        ORDER BY activities DESC, product COLLATE NOCASE
    """
    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def summary_by_customer(period: str = "all") -> list[dict]:
    start = period_start(period)
    clauses = []
    params: list[Any] = []
    if start:
        clauses.append("a.activity_date >= ?")
        params.append(start)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT c.name AS customer,
               COUNT(DISTINCT a.product_id) AS products,
               COUNT(a.id) AS activities,
               MAX(a.activity_date) AS last_activity
        FROM activities a
        JOIN customers c ON c.id = a.customer_id
        {where}
        GROUP BY c.id
        ORDER BY activities DESC, customer COLLATE NOCASE
    """
    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def dashboard_stats(period: str = "all") -> dict:
    start = period_start(period)
    date_clause = ""
    params: list[Any] = []
    if start:
        date_clause = "WHERE activity_date >= ?"
        params = [start]
    with get_db() as conn:
        leads_n = conn.execute("SELECT COUNT(*) AS n FROM leads").fetchone()["n"]
        products = conn.execute("SELECT COUNT(*) AS n FROM products").fetchone()["n"]
        open_deals = conn.execute(
            """
            SELECT COUNT(*) AS n FROM deals
            WHERE status = 'open' AND archived = 0 AND deleted_at IS NULL
            """
        ).fetchone()["n"]
        activities = conn.execute(
            f"SELECT COUNT(*) AS n FROM activities {date_clause}", params
        ).fetchone()["n"]
        shipped_clause = ""
        shipped_params: list[Any] = []
        if start:
            shipped_clause = "AND closed_date >= ?"
            shipped_params = [start]
        shipped_deals = conn.execute(
            f"""
            SELECT COUNT(*) AS n FROM deals
            WHERE status = 'shipped' AND deleted_at IS NULL {shipped_clause}
            """,
            shipped_params,
        ).fetchone()["n"]
    return {
        "leads": leads_n,
        "products": products,
        "open_deals": open_deals,
        "shipped_deals": shipped_deals,
        "activities": activities,
    }


def customer_detail(name: str, product: str = "") -> Optional[dict]:
    with get_db() as conn:
        lead = conn.execute(
            """
            SELECT l.*, c.name AS company, c.id AS customer_id
            FROM leads l
            JOIN customers c ON c.id = l.customer_id
            WHERE c.name = ? COLLATE NOCASE
            """,
            (name,),
        ).fetchone()
        if not lead:
            cust = conn.execute(
                "SELECT id, name FROM customers WHERE name = ? COLLATE NOCASE",
                (name,),
            ).fetchone()
            if not cust:
                return None
            cid = cust["id"]
            deals = conn.execute(
                """
                SELECT d.id, d.po_number, d.quantity, d.quantity_unit, d.price, d.price_unit,
                       d.deal_date, d.status, d.shipped_date,
                       d.closed_date, d.value, d.notes, p.name AS product
                FROM deals d
                JOIN products p ON p.id = d.product_id
            WHERE d.customer_id = ? AND d.deleted_at IS NULL AND d.archived = 0
            ORDER BY d.deal_date DESC, d.id DESC
            """,
            (cid,),
        ).fetchall()
            deal_list = [dict(d) for d in deals]
            by_oldest = sorted(deal_list, key=lambda x: (x["deal_date"], x["id"]))
            order_map = {d["id"]: i for i, d in enumerate(by_oldest, start=1)}
            for d in deal_list:
                d["order_num"] = order_map[d["id"]]
            deal_list.sort(key=lambda x: (x["deal_date"], x["id"]), reverse=True)
            if product:
                deal_list = [
                    d for d in deal_list
                    if d["product"].lower() == product.strip().lower()
                ]
            timeline = _activities_grouped(cid, product)
            return {
                "lead": None,
                "customer": dict(cust),
                "contacts": list_contacts(cid),
                "deals": deal_list,
                "deal_counts": deal_counts_for_customer(cid),
                "timeline": timeline,
                "product_filter": product,
            }
        deals = conn.execute(
            """
            SELECT d.id, d.po_number, d.quantity, d.quantity_unit, d.price, d.price_unit,
                   d.deal_date, d.status, d.shipped_date,
                   d.closed_date, d.value, d.notes, p.name AS product
            FROM deals d
            JOIN products p ON p.id = d.product_id
            WHERE d.customer_id = ? AND d.deleted_at IS NULL AND d.archived = 0
            ORDER BY d.deal_date DESC, d.id DESC
            """,
            (lead["customer_id"],),
        ).fetchall()
    deal_list = [dict(d) for d in deals]
    by_oldest = sorted(deal_list, key=lambda x: (x["deal_date"], x["id"]))
    order_map = {d["id"]: i for i, d in enumerate(by_oldest, start=1)}
    for d in deal_list:
        d["order_num"] = order_map[d["id"]]
    deal_list.sort(key=lambda x: (x["deal_date"], x["id"]), reverse=True)
    if product:
        deal_list = [
            d for d in deal_list
            if d["product"].lower() == product.strip().lower()
        ]

    timeline = _activities_grouped(lead["customer_id"], product)
    cid = lead["customer_id"]
    return {
        "lead": dict(lead),
        "customer": {"id": cid, "name": lead["company"]},
        "contacts": list_contacts(cid),
        "deals": deal_list,
        "deal_counts": deal_counts_for_customer(cid),
        "timeline": timeline,
        "product_filter": product,
    }
