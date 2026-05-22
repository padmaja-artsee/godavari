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

  document.querySelectorAll('#log-form input[name="link_mode"]').forEach((el) => {
    el.addEventListener("change", () => setLinkMode(el.value));
  });

  const logForm = document.getElementById("log-form");
  if (logForm) {
    logForm.addEventListener("submit", () => {
      const checked = logForm.querySelector('input[name="link_mode"]:checked');
      if (checked) setLinkMode(checked.value);
    });
  }

  async function loadDeals(company) {
    if (!dealSelect || !company.trim()) {
      if (dealSelect) dealSelect.innerHTML = '<option value="">— Select company first —</option>';
      return;
    }
    dealSelect.innerHTML = '<option value="">Loading…</option>';
    try {
      const res = await fetch("/api/company-deals?company=" + encodeURIComponent(company.trim()));
      const deals = await res.json();
      if (!deals.length) {
        dealSelect.innerHTML = '<option value="">No deals yet — use “Start new deal”</option>';
        return;
      }
      dealSelect.innerHTML = '<option value="">— Pick a deal —</option>';
      deals.forEach((d) => {
        const opt = document.createElement("option");
        opt.value = d.id;
        const po = d.po_number ? ` · PO ${d.po_number}` : "";
        opt.textContent = d.label || `${d.deal_date} · ${d.product} · ${d.status}${po}`;
        if (String(d.id) === dealSelect.dataset.preset) opt.selected = true;
        dealSelect.appendChild(opt);
      });
    } catch (e) {
      dealSelect.innerHTML = '<option value="">Error loading deals</option>';
    }
  }

  let timer;
  companyInput.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(() => loadDeals(companyInput.value), 300);
  });
  if (companyInput.value) loadDeals(companyInput.value);

  const initial = document.querySelector('#log-form input[name="link_mode"]:checked');
  if (initial) setLinkMode(initial.value);
})();
