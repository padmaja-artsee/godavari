(function () {
  const companyInput = document.getElementById("log-company");
  const dealSelect = document.getElementById("log-deal-id");
  const panels = {
    existing: document.getElementById("panel-existing"),
    new: document.getElementById("panel-new"),
    none: document.getElementById("panel-none"),
  };

  if (!companyInput) return;

  function setLinkMode(mode) {
    document.querySelectorAll('#log-form input[name="link_mode"]').forEach((el) => {
      el.checked = el.value === mode;
    });
    Object.keys(panels).forEach((k) => {
      const panel = panels[k];
      if (!panel) return;
      const active = k === mode;
      panel.style.display = active ? "block" : "none";
      panel.querySelectorAll("input, select, textarea").forEach((el) => {
        if (el.name === "link_mode") return;
        el.disabled = !active;
      });
    });
  }

  const logForm = document.getElementById("log-form");
  if (logForm) {
    logForm.addEventListener("submit", () => {
      const checked = logForm.querySelector('input[name="link_mode"]:checked');
      if (checked) setLinkMode(checked.value);
    });
  }

  async function loadDeals(company) {
    if (!dealSelect) return;
    const mode = document.querySelector('#log-form input[name="link_mode"]:checked');
    if (!company.trim()) {
      dealSelect.innerHTML =
        '<option value="">— Enter company name first —</option>';
      return;
    }
    if (mode && mode.value !== "existing") {
      return;
    }
    dealSelect.innerHTML = '<option value="">Loading deals…</option>';
    dealSelect.disabled = true;
    try {
      const res = await fetch(
        "/api/company-deals?company=" + encodeURIComponent(company.trim())
      );
      const deals = await res.json();
      dealSelect.disabled = false;
      if (!deals.length) {
        dealSelect.innerHTML =
          '<option value="">No deals for this company — use “Start new deal”</option>';
        return;
      }
      dealSelect.innerHTML = '<option value="">— Pick a deal —</option>';
      deals.forEach((d) => {
        const opt = document.createElement("option");
        opt.value = d.id;
        const po = d.po_number ? ` · PO ${d.po_number}` : "";
        opt.textContent =
          d.label || `${d.id} · ${d.deal_date} · ${d.product} · ${d.status}${po}`;
        if (String(d.id) === dealSelect.dataset.preset) opt.selected = true;
        dealSelect.appendChild(opt);
      });
    } catch (e) {
      dealSelect.disabled = false;
      dealSelect.innerHTML = '<option value="">Error loading deals</option>';
    }
  }

  function scheduleLoadDeals() {
    clearTimeout(scheduleLoadDeals.timer);
    scheduleLoadDeals.timer = setTimeout(
      () => loadDeals(companyInput.value),
      250
    );
  }

  companyInput.addEventListener("input", scheduleLoadDeals);
  companyInput.addEventListener("change", scheduleLoadDeals);

  document.querySelectorAll('#log-form input[name="link_mode"]').forEach((el) => {
    el.addEventListener("change", () => {
      setLinkMode(el.value);
      if (el.value === "existing") scheduleLoadDeals();
    });
  });

  if (companyInput.value) scheduleLoadDeals();

  const initial = document.querySelector('#log-form input[name="link_mode"]:checked');
  if (initial) setLinkMode(initial.value);
})();
