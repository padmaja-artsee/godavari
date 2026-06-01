(function () {
  const companyInput = document.getElementById("log-company");
  const dealSelect   = document.getElementById("log-deal-id");
  const accordion    = document.getElementById("deal-details-accordion");
  const arrow        = document.getElementById("deal-details-arrow");
  const summarySpan  = document.getElementById("deal-details-summary");

  const panels = {
    existing: document.getElementById("panel-existing"),
    new:      document.getElementById("panel-new"),
    none:     document.getElementById("panel-none"),
  };

  if (!companyInput) return;

  const linkHidden = document.getElementById("link-mode-hidden");

  // ── Accordion arrow animation ─────────────────────────
  if (accordion) {
    accordion.addEventListener("toggle", function () {
      if (arrow) arrow.style.transform = accordion.open ? "rotate(90deg)" : "";
    });
    if (accordion.open && arrow) arrow.style.transform = "rotate(90deg)";
  }

  // ── Mode switching ─────────────────────────────────────
  function setLinkMode(mode) {
    if (linkHidden) linkHidden.value = mode;
    document.querySelectorAll("#link-mode-btns .link-mode-btn").forEach(btn => {
      btn.classList.toggle("active", btn.dataset.value === mode);
    });
    Object.keys(panels).forEach(k => {
      const panel = panels[k];
      if (!panel) return;
      const active = k === mode;
      panel.style.display = active ? "block" : "none";
      panel.querySelectorAll("input, select, textarea").forEach(el => {
        if (el.name === "link_mode") return;
        el.disabled = !active;
      });
    });
  }

  // ── Deal pre-population ───────────────────────────────
  const FIELD_MAP = {
    // commercial
    "deal_po_number":    "po_number",
    "deal_price":        "price",
    "deal_price_unit":   "price_unit",
    "incoterms":         "incoterms",
    "payment_terms":     "payment_terms",
    "shipment_timing":   "shipment_timing",
    "insurance_amount":  "insurance_amount",
    "insurance_currency":"insurance_currency",
    "ocean_freight_amount": "ocean_freight_amount",
    "ocean_freight_currency": "ocean_freight_currency",
    "commission_rate":   "commission_rate",
    // shipping
    "po_date":           "po_date",
    "packing":           "packing",
    "gbl_invoice":       "gbl_invoice",
    "gbl_invoice_date":  "gbl_invoice_date",
    "container_number":  "container_number",
    "vessel_name":       "vessel_name",
    "etd_india":         "etd_india",
    "transit_time":      "transit_time",
    "destination":       "destination",
    "eta":               "eta",
  };

  function populateDealFields(deal) {
    if (!deal) return;
    // commercial text/select
    Object.entries(FIELD_MAP).forEach(([formName, dealKey]) => {
      const el = document.querySelector(`[name="${formName}"]`);
      if (!el) return;
      const val = deal[dealKey] || "";
      el.value = val;
    });
    // quantity: deal_quantity + deal_quantity_unit
    const qtyEl  = document.querySelector('[name="deal_quantity"]');
    const unitEl = document.querySelector('[name="deal_quantity_unit"]');
    if (qtyEl)  qtyEl.value  = deal.quantity  || "";
    if (unitEl) unitEl.value = deal.quantity_unit || "MT";

    const valEl = document.querySelector(".deal-commercial-value");
    const fobEl = document.querySelector(".deal-commercial-fob");
    const commEl = document.querySelector(".deal-commercial-commission");
    if (valEl) valEl.value = deal.commercial_total || "";
    if (fobEl) fobEl.value = deal.fob_value || "";
    if (commEl) commEl.value = deal.commission_amount || "";

    // update summary line
    updateSummary(deal);

    if (window.syncCommercialValues) window.syncCommercialValues();

    // auto-open accordion if deal has any non-empty data
    const hasData = deal.po_number || deal.price || deal.quantity ||
                    deal.po_date || deal.packing || deal.container_number;
    if (accordion && hasData) accordion.open = true;
  }

  function updateSummary(deal) {
    if (!summarySpan) return;
    const parts = [];
    if (deal.po_number) parts.push("PO " + deal.po_number);
    if (deal.quantity)  parts.push(deal.quantity + (deal.quantity_unit ? " " + deal.quantity_unit : ""));
    if (deal.price)     parts.push("€" + deal.price + (deal.price_unit || ""));
    if (deal.packing)   parts.push(deal.packing);
    summarySpan.textContent = parts.length ? "— " + parts.join(" · ") : "";
  }

  function clearDealFields() {
    Object.keys(FIELD_MAP).forEach(formName => {
      const el = document.querySelector(`[name="${formName}"]`);
      if (el) el.value = "";
    });
    const qtyEl  = document.querySelector('[name="deal_quantity"]');
    const unitEl = document.querySelector('[name="deal_quantity_unit"]');
    if (qtyEl)  qtyEl.value  = "";
    if (unitEl) unitEl.value = "MT";
    const valEl = document.querySelector(".deal-commercial-value");
    const fobEl = document.querySelector(".deal-commercial-fob");
    const commEl = document.querySelector(".deal-commercial-commission");
    if (valEl) valEl.value = "";
    if (fobEl) fobEl.value = "";
    if (commEl) commEl.value = "";
    if (summarySpan) summarySpan.textContent = "";
    if (window.syncCommercialValues) window.syncCommercialValues();
  }

  // ── Deal select change ────────────────────────────────
  if (dealSelect) {
    dealSelect.addEventListener("change", function () {
      const opt = dealSelect.selectedOptions[0];
      if (!opt || !opt.dataset.deal) { clearDealFields(); return; }
      try {
        populateDealFields(JSON.parse(opt.dataset.deal));
      } catch(e) { clearDealFields(); }
    });
    // Pre-populate if a deal is already selected (e.g. from URL preset)
    const presetOpt = dealSelect.querySelector("option[selected]") ||
                      (dealSelect.dataset.preset
                        ? dealSelect.querySelector(`option[value="${dealSelect.dataset.preset}"]`)
                        : null);
    if (presetOpt && presetOpt.dataset.deal) {
      try { populateDealFields(JSON.parse(presetOpt.dataset.deal)); } catch(e) {}
    }
  }

  // ── Load deals for company ────────────────────────────
  async function loadDeals(company) {
    if (!dealSelect) return;
    if (!company.trim()) {
      dealSelect.innerHTML = '<option value="">— Enter company name first —</option>';
      clearDealFields();
      return;
    }
    if (linkHidden && linkHidden.value !== "existing") return;

    dealSelect.innerHTML = '<option value="">Loading…</option>';
    dealSelect.disabled  = true;
    try {
      const res   = await fetch("/api/company-deals?company=" + encodeURIComponent(company.trim()));
      const deals = await res.json();
      dealSelect.disabled = false;
      if (!deals.length) {
        dealSelect.innerHTML = '<option value="">No deals — use "Start new deal"</option>';
        clearDealFields();
        return;
      }
      dealSelect.innerHTML = '<option value="">— Pick a deal —</option>';
      deals.forEach(d => {
        const opt       = document.createElement("option");
        opt.value       = d.id;
        opt.textContent = d.label || `${d.id} · ${d.deal_date} · ${d.product} · ${d.status}`;
        opt.dataset.deal = JSON.stringify(d);
        if (String(d.id) === dealSelect.dataset.preset) {
          opt.selected = true;
          try { populateDealFields(d); } catch(e) {}
        }
        dealSelect.appendChild(opt);
      });
    } catch(e) {
      dealSelect.disabled = false;
      dealSelect.innerHTML = '<option value="">Error loading deals</option>';
    }
  }

  function scheduleLoadDeals() {
    clearTimeout(scheduleLoadDeals._t);
    scheduleLoadDeals._t = setTimeout(() => loadDeals(companyInput.value), 250);
  }

  companyInput.addEventListener("input",  scheduleLoadDeals);
  companyInput.addEventListener("change", scheduleLoadDeals);

  document.querySelectorAll("#link-mode-btns .link-mode-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      setLinkMode(btn.dataset.value);
      if (btn.dataset.value === "existing") scheduleLoadDeals();
    });
  });

  if (companyInput.value) scheduleLoadDeals();
  if (linkHidden) setLinkMode(linkHidden.value);
})();
