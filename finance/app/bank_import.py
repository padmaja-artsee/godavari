"""Bank CSV import — Chemung Canal Trust format (GBL acct 204082566)."""
from __future__ import annotations

import csv
import hashlib
import io
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from finance.app.database import fiscal_year_for_date, get_db, save_vendor
from finance.app.expenses import create_transaction

# ---------------------------------------------------------------------------
# Rule definitions (top patterns from GBL bank exports)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BankRule:
    rule_id: int
    label: str
    pattern: re.Pattern[str]
    direction: str  # debit | credit
    account_name: str
    vendor_name: str
    confidence: str  # high | medium | low
    precheck: bool = False
    force_review: bool = False


def _r(rule_id, label, pat, direction, account, vendor, confidence, precheck=False, force_review=False):
    return BankRule(
        rule_id, label, re.compile(pat, re.I), direction, account, vendor,
        confidence, precheck, force_review,
    )


BANK_RULES: list[BankRule] = [
    _r(1, "Commission wire", r"Incoming Wire.*GODAVARI BIOREFINERIES", "credit",
       "Commission Income", "Godavari Biorefineries Ltd", "high", precheck=True),
    _r(2, "Other incoming wire", r"Incoming Wire", "credit",
       "Other Income", "", "medium"),
    _r(3, "Incoming wire fee", r"Incoming Wire Fee", "debit",
       "Bank Charges", "Chemung Canal Trust", "high", precheck=True),
    _r(4, "Outgoing wire fee", r"Outgoing Wire Fee", "debit",
       "Bank Charges", "Chemung Canal Trust", "high", precheck=True),
    _r(5, "Outgoing wire", r"Outgoing Wire", "debit",
       "Miscellaneous", "", "low", force_review=True),
    _r(6, "Payroll", r"INTUIT PAYROLL", "debit",
       "Compensation", "Intuit QuickBooks Payroll", "high", precheck=True),
    _r(7, "IRS tax", r"IRS USATAXPYMT", "debit",
       "Taxes", "IRS", "high", precheck=True),
    _r(8, "PA withholding", r"PAEMPLOYTX|COMMWLTHOFPAPATH", "debit",
       "Payroll Tax", "PA Department of Revenue", "high", precheck=True),
    _r(9, "PA unemployment", r"PADLIUCCON UNEMP COMP", "debit",
       "Payroll Tax", "PA UC", "high", precheck=True),
    _r(10, "Philadelphia tax", r"PHILA DEPT REV", "debit",
       "Taxes", "City of Philadelphia", "high", precheck=True),
    _r(11, "Liability insurance", r"NATL LIAB & FIRE INS", "debit",
       "Commercial Liability Ins", "National Liability & Fire", "high", precheck=True),
    _r(12, "Accounting", r"SCIARABBA WALKER", "debit",
       "Accounting & Audit", "Sciarrabba Walker", "high", precheck=True),
    _r(13, "Regus rent", r"Regus Management", "debit",
       "Office Lease / Rent", "Regus", "high", precheck=True),
    _r(14, "Bank service charge", r"Service Charges", "debit",
       "Bank Charges", "Chemung Canal Trust", "high", precheck=True),
    _r(15, "Staples", r"PURCHASE-SIG STAPLES", "debit",
       "Office Supplies", "Staples", "high", precheck=True),
    _r(16, "FedEx", r"PURCHASE-SIG FEDEX OFFICE", "debit",
       "Postage and Delivery", "FedEx Office", "high", precheck=True),
    _r(17, "Microsoft subscription", r"PURCHASE-RECUR Microsoft", "debit",
       "Subscriptions/Software", "Microsoft", "high", precheck=True),
    _r(18, "Legal — Haylor Freyer", r"HAYLOR,\s*FREYER", "debit",
       "Legal Fees", "Haylor Freyer & Coon", "high", precheck=True),
    _r(19, "Meals / travel purchase", r"PURCHASE-SIG.*(PHILLY|GRANDMAS|AIRP|EWR)", "debit",
       "Meals and Entertainment", "", "medium"),
    _r(20, "Large electronic transfer", r"TELEPHONE OR ELECTRONIC TRANSFER", "debit",
       "Miscellaneous", "", "low", force_review=True),
]

REVIEW_AMOUNT_THRESHOLD = 10_000.0


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_desc(desc: str) -> str:
    return re.sub(r"\s+", " ", (desc or "").strip())


def _parse_amount(val: str) -> float:
    s = (val or "").strip().replace(",", "")
    if not s:
        return 0.0
    try:
        return round(float(s), 2)
    except ValueError:
        return 0.0


def _parse_bank_date(val: str) -> str:
    """M/D/YYYY or YYYY-MM-DD → ISO date."""
    s = (val or "").strip()
    if not s:
        return ""
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:10], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def compute_fingerprint(
    bank_account: str,
    posted_date: str,
    direction: str,
    amount: float,
    description: str,
    chk_ref: str = "",
) -> str:
    parts = [
        (bank_account or "").strip(),
        posted_date,
        direction,
        f"{amount:.2f}",
        _normalize_desc(description).upper(),
        (chk_ref or "").strip(),
    ]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def parse_bank_csv(file_bytes: bytes) -> list[dict[str, Any]]:
    text = file_bytes.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV has no header row")
    fields = {f.strip().lower(): f for f in reader.fieldnames if f}
    required = {"debit", "credit", "date", "description"}
    if not required.issubset(fields):
        raise ValueError(
            "Unrecognized bank CSV — expected columns: Account, Debit, Credit, Date, Description"
        )

    rows: list[dict[str, Any]] = []
    acct_col = fields.get("account")
    chk_col = fields.get("chkref")
    bal_col = fields.get("balance")
    for raw in reader:
        debit = _parse_amount(raw.get(fields["debit"], ""))
        credit = _parse_amount(raw.get(fields["credit"], ""))
        if debit > 0 and credit > 0:
            continue
        if debit <= 0 and credit <= 0:
            continue
        direction = "credit" if credit > 0 else "debit"
        amount = credit if direction == "credit" else debit
        posted = _parse_bank_date(raw.get(fields["date"], ""))
        if not posted:
            continue
        desc = _normalize_desc(raw.get(fields["description"], ""))
        acct = (raw.get(acct_col, "") if acct_col else "").strip()
        chk = (raw.get(chk_col, "") if chk_col else "").strip()
        if not desc and not chk:
            continue
        if not desc and chk:
            desc = f"CHECK {chk}"
        rows.append({
            "bank_account": acct,
            "chk_ref": chk,
            "posted_date": posted,
            "amount": amount,
            "direction": direction,
            "description": desc,
            "balance": (raw.get(bal_col, "") if bal_col else "").strip(),
        })
    return rows


def _accounts_by_name() -> dict[str, dict]:
    with get_db() as conn:
        rows = conn.execute("SELECT id, name, section FROM accounts").fetchall()
    return {r["name"]: dict(r) for r in rows}


def _vendors_by_name() -> dict[str, int]:
    with get_db() as conn:
        rows = conn.execute("SELECT id, name FROM vendors").fetchall()
    out: dict[str, int] = {}
    for r in rows:
        out[r["name"].strip().lower()] = r["id"]
    return out


def _resolve_account_id(account_name: str, accounts: dict[str, dict]) -> int | None:
    row = accounts.get(account_name)
    return row["id"] if row else None


def _get_or_create_vendor(vendor_name: str, vendor_cache: dict[str, int]) -> int | None:
    name = (vendor_name or "").strip()
    if not name:
        return None
    key = name.lower()
    if key in vendor_cache:
        return vendor_cache[key]
    vid = save_vendor(name, "", "", "Auto-created from bank import")
    vendor_cache[key] = vid
    return vid


def categorize_row(
    description: str,
    direction: str,
    amount: float,
    chk_ref: str,
) -> dict[str, Any]:
    for rule in BANK_RULES:
        if rule.direction != direction:
            continue
        if rule.pattern.search(description):
            return {
                "rule_id": rule.rule_id,
                "rule_label": rule.label,
                "account_name": rule.account_name,
                "vendor_name": rule.vendor_name,
                "confidence": rule.confidence,
                "precheck": rule.precheck,
                "force_review": rule.force_review,
            }
    if direction == "credit":
        return {
            "rule_id": 0,
            "rule_label": "Unmatched credit",
            "account_name": "Other Income",
            "vendor_name": "",
            "confidence": "low",
            "precheck": False,
            "force_review": False,
        }
    if chk_ref or re.search(r"\bCHECK\b", description, re.I):
        return {
            "rule_id": 0,
            "rule_label": "Check payment",
            "account_name": "Miscellaneous",
            "vendor_name": "",
            "confidence": "medium",
            "precheck": False,
            "force_review": False,
        }
    if re.search(r"PURCHASE-SIG|PURCHASE-RECUR", description, re.I):
        return {
            "rule_id": 0,
            "rule_label": "Card purchase",
            "account_name": "Miscellaneous",
            "vendor_name": "",
            "confidence": "medium",
            "precheck": False,
            "force_review": False,
        }
    return {
        "rule_id": 0,
        "rule_label": "Unmatched debit",
        "account_name": "Miscellaneous",
        "vendor_name": "",
        "confidence": "low",
        "precheck": False,
        "force_review": False,
    }


def _existing_fingerprints() -> set[str]:
    with get_db() as conn:
        rows = conn.execute("SELECT fingerprint FROM bank_import_fingerprints").fetchall()
    return {r["fingerprint"] for r in rows}


def _fuzzy_match(posted_date: str, amount: float, tx_type: str) -> int | None:
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT id FROM transactions
            WHERE date = ? AND transaction_type = ?
              AND ABS(amount - ?) < 0.01
            ORDER BY id DESC LIMIT 1
            """,
            (posted_date, tx_type, amount),
        ).fetchone()
    return row["id"] if row else None


def _commission_duplicate(posted_date: str, amount: float) -> int | None:
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT t.id FROM transactions t
            JOIN accounts a ON t.account_id = a.id
            WHERE t.date = ? AND t.transaction_type = 'income'
              AND a.name = 'Commission Income'
              AND ABS(t.amount - ?) < 0.01
            LIMIT 1
            """,
            (posted_date, amount),
        ).fetchone()
    return row["id"] if row else None


def ensure_bank_import_schema(conn=None) -> None:
    sql = """
            CREATE TABLE IF NOT EXISTS bank_import_fingerprints (
                fingerprint       TEXT PRIMARY KEY,
                transaction_id    INTEGER NOT NULL REFERENCES transactions(id),
                bank_account      TEXT,
                posted_date       TEXT,
                amount            REAL,
                direction         TEXT,
                description       TEXT,
                imported_at       TEXT
            );
            CREATE TABLE IF NOT EXISTS bank_import_staging (
                batch_id              TEXT NOT NULL,
                row_index             INTEGER NOT NULL,
                fingerprint           TEXT NOT NULL,
                bank_account          TEXT,
                chk_ref               TEXT,
                posted_date           TEXT,
                amount                REAL,
                direction             TEXT,
                description           TEXT,
                transaction_type      TEXT,
                account_id            INTEGER,
                vendor_id             INTEGER,
                account_name          TEXT,
                vendor_name           TEXT,
                rule_label            TEXT,
                confidence            TEXT,
                status                TEXT,
                fuzzy_transaction_id  INTEGER,
                precheck              INTEGER DEFAULT 0,
                PRIMARY KEY (batch_id, row_index)
            );
            CREATE TABLE IF NOT EXISTS bank_import_claims (
                batch_id        TEXT PRIMARY KEY,
                committed_at    TEXT NOT NULL,
                imported_count  INTEGER NOT NULL DEFAULT 0
            );
        """
    if conn is not None:
        conn.executescript(sql)
        return
    with get_db() as c:
        c.executescript(sql)


def clear_staging_batch(batch_id: str) -> None:
    with get_db() as conn:
        conn.execute("DELETE FROM bank_import_staging WHERE batch_id = ?", (batch_id,))


def build_import_preview(
    file_bytes: bytes,
    from_date: str = "",
    to_date: str = "",
    payment_account_id: int | None = None,
) -> tuple[str, list[dict[str, Any]], dict[str, int]]:
    """Parse CSV, classify rows, stage them; return batch_id, preview rows, summary."""
    ensure_bank_import_schema()
    parsed = parse_bank_csv(file_bytes)
    if not parsed:
        raise ValueError("No transactions found in CSV")

    fd = (from_date or "").strip()[:10]
    td = (to_date or "").strip()[:10]
    if fd or td:
        parsed = [
            r for r in parsed
            if (not fd or r["posted_date"] >= fd) and (not td or r["posted_date"] <= td)
        ]
    if not parsed:
        raise ValueError("No transactions in the selected date range")

    accounts = _accounts_by_name()
    vendor_cache = _vendors_by_name()
    imported_fps = _existing_fingerprints()
    batch_id = uuid.uuid4().hex
    clear_staging_batch(batch_id)

    preview: list[dict[str, Any]] = []
    summary = {"new": 0, "duplicate": 0, "fuzzy": 0, "review": 0, "total": 0}
    staging_rows: list[tuple] = []

    for idx, row in enumerate(parsed):
        fp = compute_fingerprint(
            row["bank_account"],
            row["posted_date"],
            row["direction"],
            row["amount"],
            row["description"],
            row["chk_ref"],
        )
        cat = categorize_row(
            row["description"], row["direction"], row["amount"], row["chk_ref"]
        )
        tx_type = "income" if row["direction"] == "credit" else "expense"
        account_id = _resolve_account_id(cat["account_name"], accounts)
        vendor_id = _get_or_create_vendor(cat["vendor_name"], vendor_cache)

        status = "new"
        fuzzy_id = None
        if fp in imported_fps:
            status = "duplicate"
        else:
            fuzzy_id = _fuzzy_match(row["posted_date"], row["amount"], tx_type)
            if fuzzy_id:
                status = "fuzzy"
            elif (
                cat.get("force_review")
                or row["amount"] >= REVIEW_AMOUNT_THRESHOLD
                or cat["confidence"] == "low"
            ):
                status = "review"
            elif (
                tx_type == "income"
                and cat["account_name"] == "Commission Income"
                and _commission_duplicate(row["posted_date"], row["amount"])
            ):
                status = "review"

        precheck = (
            status == "new"
            and cat.get("precheck")
            and cat["confidence"] == "high"
            and account_id is not None
        )

        summary["total"] += 1
        summary[status] = summary.get(status, 0) + 1

        item = {
            "row_index": idx,
            "fingerprint": fp,
            "bank_account": row["bank_account"],
            "chk_ref": row["chk_ref"],
            "posted_date": row["posted_date"],
            "amount": row["amount"],
            "direction": row["direction"],
            "description": row["description"],
            "transaction_type": tx_type,
            "account_id": account_id,
            "vendor_id": vendor_id,
            "account_name": cat["account_name"],
            "vendor_name": cat["vendor_name"],
            "rule_label": cat["rule_label"],
            "confidence": cat["confidence"],
            "status": status,
            "fuzzy_transaction_id": fuzzy_id,
            "precheck": precheck,
            "payment_account_id": payment_account_id,
        }
        preview.append(item)

        staging_rows.append((
            batch_id, idx, fp, row["bank_account"], row["chk_ref"],
            row["posted_date"], row["amount"], row["direction"],
            row["description"], tx_type, account_id, vendor_id,
            cat["account_name"], cat["vendor_name"], cat["rule_label"],
            cat["confidence"], status, fuzzy_id, 1 if precheck else 0,
        ))

    with get_db() as conn:
        conn.executemany(
            """
            INSERT INTO bank_import_staging (
                batch_id, row_index, fingerprint, bank_account, chk_ref,
                posted_date, amount, direction, description, transaction_type,
                account_id, vendor_id, account_name, vendor_name, rule_label,
                confidence, status, fuzzy_transaction_id, precheck
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            staging_rows,
        )

    return batch_id, preview, summary


def commit_import_batch(
    batch_id: str,
    selected_indices: list[int],
    account_overrides: dict[int, int],
    vendor_overrides: dict[int, int | None],
    payment_account_id: int,
) -> tuple[int, list[str], bool]:
    """Import selected staged rows. Returns (count, errors, already_submitted)."""
    ensure_bank_import_schema()
    selected_indices = list(dict.fromkeys(int(i) for i in selected_indices))
    if not selected_indices:
        return 0, ["No rows selected"], False

    now = _now()
    count = 0
    errors: list[str] = []

    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")

        existing_claim = conn.execute(
            "SELECT imported_count FROM bank_import_claims WHERE batch_id = ?",
            (batch_id,),
        ).fetchone()
        if existing_claim:
            return int(existing_claim["imported_count"]), [
                "This import was already submitted. Refresh to start a new import."
            ], True

        rows_to_import: list[sqlite3.Row] = []
        for idx in selected_indices:
            row = conn.execute(
                """
                SELECT * FROM bank_import_staging
                WHERE batch_id = ? AND row_index = ?
                """,
                (batch_id, idx),
            ).fetchone()
            if row:
                rows_to_import.append(row)
            else:
                errors.append(f"Row {idx} not found in batch")

        if not rows_to_import:
            return 0, errors or ["No rows found for this batch"], False

        conn.execute(
            "INSERT INTO bank_import_claims (batch_id, committed_at, imported_count) VALUES (?,?,0)",
            (batch_id, now),
        )
        conn.execute(
            "DELETE FROM bank_import_staging WHERE batch_id = ?", (batch_id,)
        )

        for row in rows_to_import:
            fp = row["fingerprint"]
            if conn.execute(
                "SELECT 1 FROM bank_import_fingerprints WHERE fingerprint = ?", (fp,)
            ).fetchone():
                errors.append(f"Already imported: {row['description'][:40]}")
                continue

            account_id = account_overrides.get(row["row_index"]) or row["account_id"]
            if not account_id:
                errors.append(f"Row {row['row_index']}: no account selected")
                continue

            vendor_id = vendor_overrides.get(row["row_index"], row["vendor_id"])
            ref = row["chk_ref"] or row["description"][:80]
            notes = f"Bank import — {row['rule_label'] or 'manual'}"

            tx_id = create_transaction(
                date=row["posted_date"],
                account_id=account_id,
                amount=row["amount"],
                transaction_type=row["transaction_type"],
                payment_account_id=payment_account_id,
                vendor_id=vendor_id,
                reference=ref,
                notes=notes,
                conn=conn,
            )
            conn.execute(
                """
                INSERT INTO bank_import_fingerprints
                (fingerprint, transaction_id, bank_account, posted_date,
                 amount, direction, description, imported_at)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    fp, tx_id, row["bank_account"],
                    row["posted_date"], row["amount"], row["direction"],
                    row["description"], now,
                ),
            )
            count += 1

        conn.execute(
            "UPDATE bank_import_claims SET imported_count = ? WHERE batch_id = ?",
            (count, batch_id),
        )

    return count, errors, False
