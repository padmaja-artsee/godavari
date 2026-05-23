"""Generate module — document type registry.

To remove Commission Invoices entirely:
  1. Delete app/commission_invoices.py, app/ci_exports.py
  2. Delete templates/generate/commission_invoices/
  3. Delete static/ci_wysiwyg.js, static/ci_wysiwyg.css
  4. Remove the CI entry below
  5. Remove the "── Commission Invoice routes ──" block in app/main.py
"""

GENERATE_DOCUMENTS = [
    {
        "key": "purchase_order",
        "title": "Purchase Order",
        "description": "Create a structured PO from scratch or prefill from a deal. Export to Excel or PDF and print locally.",
        "create_url": "/generate/purchase-orders/new",
        "list_url": "/generate/purchase-orders",
    },
    # ── Commission Invoice ──────────────────────────────────────────────────
    {
        "key": "commission_invoice",
        "title": "Commission Invoice",
        "description": "Invoice Godavari Biorefineries Ltd for commission on product sales. Calculates commission from FOB value and rate. Export to Excel or print.",
        "create_url": "/generate/commission-invoices/new",
        "list_url": "/generate/commission-invoices",
    },
]
