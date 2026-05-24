"""Generate module — document type registry.

To remove Commission Invoices entirely:
  1. Delete app/commission_invoices.py, app/ci_exports.py
  2. Delete templates/generate/commission_invoices/
  3. Delete static/ci_wysiwyg.js, static/ci_wysiwyg.css
  4. Remove the CI entry below
  5. Remove the "── Commission Invoice routes ──" block in app/main.py

To remove Sales (Commercial) Invoices entirely:
  1. Delete app/sales_invoices.py, app/si_exports.py
  2. Delete templates/generate/sales_invoices/
  3. Delete static/si_wysiwyg.js, static/si_wysiwyg.css
  4. Remove the SI entry below
  5. Remove the "── Sales (Commercial) Invoice routes ──" block in app/main.py
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
    # ── Commercial (Sales) Invoice ──────────────────────────────────────────
    {
        "key": "sales_invoice",
        "title": "Commercial Invoice",
        "description": "Sales invoice to the customer. Auto-fills from deal data: buyer, quantity, rate, delivery details. Calculates value = qty × rate. Export to Excel or print.",
        "create_url": "/generate/sales-invoices/new",
        "list_url": "/generate/sales-invoices",
    },
    # ── Delivery Note ───────────────────────────────────────────────────────
    {
        "key": "delivery_note",
        "title": "Delivery Note",
        "description": "Delivery Note cum Packing List. Auto-fills product, customer, batch and weight details from deal. Calculates total net/tare/gross weights from pack count × per-pack weights.",
        "create_url": "/generate/delivery-notes/new",
        "list_url": "/generate/delivery-notes",
    },
]
