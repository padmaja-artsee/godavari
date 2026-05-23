(function () {
  const companyInput = document.getElementById("log-company");
  const dealSelect = document.getElementById("log-deal-id");
  const panels = {
    existing: document.getElementById("panel-existing"),
    new: document.getElementById("panel-new"),
    none: document.getElementById("panel-none"),
  };

  if (!companyInput) return;

  const linkHidden = document.getElementById("link-mode-hidden");

  function setLinkMode(mode) {
    if (linkHidden) linkHidden.value = mode;
    // update button active state
    document.querySelectorAll("#link-mode-btns .link-mode-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.value === mode);
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

  async function loadDeals(company) {
    if (!dealSelect) return;
    const mode = linkHidden ? linkHidden.value : "none";
    if (!company.trim()) {
      dealSelect.innerHTML =
        '<option value="">— Enter company name first —</option>';
      return;
    }
    if (mode !== "existing") {
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

  document.querySelectorAll("#link-mode-btns .link-mode-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      setLinkMode(btn.dataset.value);
      if (btn.dataset.value === "existing") scheduleLoadDeals();
    });
  });

  if (companyInput.value) scheduleLoadDeals();

  // Apply initial mode from hidden input
  if (linkHidden) setLinkMode(linkHidden.value);
})();
