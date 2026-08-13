(function () {
  const dialog = document.getElementById("master-update-dialog");
  if (!dialog) return;

  const openBtn = document.getElementById("open-master-dialog");
  const closeBtn = document.getElementById("close-master-dialog");
  const cancelBtn = document.getElementById("cancel-master-dialog");
  const form = document.getElementById("master-update-form");
  const companyInput = document.getElementById("master-company");
  const dealSelect = document.getElementById("master-deal-id");
  const linkMode = document.getElementById("master-link-mode");
  const dealWrap = document.getElementById("master-deal-wrap");
  const productWrap = document.getElementById("master-product-wrap");
  const productNew = document.getElementById("master-product-new");
  const productNone = document.getElementById("master-product-none");
  const productHidden = document.getElementById("master-product");
  const stageSelect = document.getElementById("master-stage");
  const channelSelect = document.getElementById("master-channel");
  const activityDate = document.getElementById("master-activity-date");
  const dealDate = document.getElementById("master-deal-date");
  const fullLink = document.getElementById("master-full-form-link");
  const commentInput = document.getElementById("master-comment");

  const LAST_COMPANY_KEY = "leads.master.lastCompany";
  const CHANNEL_FOR_STAGE = {
    first_contact: "Email",
    rfq: "Quote",
    rfs: "Sample",
    conversion: "PO",
  };

  function todayISO() {
    const d = new Date();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return d.getFullYear() + "-" + m + "-" + day;
  }

  function syncMode() {
    const mode = linkMode.value;
    dealWrap.hidden = mode !== "existing";
    productWrap.hidden = mode === "existing";
    if (mode === "new") {
      productNew.disabled = false;
      productNew.required = true;
      productNone.value = "";
    } else if (mode === "none") {
      productNew.disabled = false;
      productNew.required = false;
    } else {
      productNew.required = false;
    }
    dealSelect.required = mode === "existing";
  }

  function syncChannelFromStage() {
    const suggested = CHANNEL_FOR_STAGE[stageSelect.value];
    if (suggested) channelSelect.value = suggested;
  }

  function rememberCompany(company) {
    if (!company) return;
    try {
      localStorage.setItem(LAST_COMPANY_KEY, company);
    } catch (e) {}
  }

  function lastCompany() {
    try {
      return localStorage.getItem(LAST_COMPANY_KEY) || "";
    } catch (e) {
      return "";
    }
  }

  async function loadDeals(company, presetDealId) {
    dealSelect.innerHTML = '<option value="">Loading…</option>';
    if (!company) {
      dealSelect.innerHTML = '<option value="">— Enter company first —</option>';
      return;
    }
    try {
      const res = await fetch(
        "/api/company-deals?company=" + encodeURIComponent(company)
      );
      const deals = await res.json();
      dealSelect.innerHTML = '<option value="">— Pick a deal —</option>';
      let matched = null;
      (deals || []).forEach(function (d) {
        const opt = document.createElement("option");
        opt.value = d.id;
        const stageBit = d.pipeline_stage ? " · " + d.pipeline_stage : "";
        opt.textContent =
          (d.label || d.deal_date + " · " + d.product + " · " + d.status) +
          stageBit;
        opt.dataset.product = d.product || "";
        opt.dataset.stage = d.pipeline_stage || "";
        if (presetDealId && String(d.id) === String(presetDealId)) {
          opt.selected = true;
          matched = d;
        }
        dealSelect.appendChild(opt);
      });
      // Auto-pick when only one deal and no explicit preset
      if (!matched && !presetDealId && deals && deals.length === 1) {
        dealSelect.value = String(deals[0].id);
        matched = deals[0];
      }
      if (matched) {
        if (matched.pipeline_stage) stageSelect.value = matched.pipeline_stage;
        if (matched.product) productHidden.value = matched.product;
        syncChannelFromStage();
      }
    } catch (e) {
      dealSelect.innerHTML = '<option value="">— Could not load deals —</option>';
    }
  }

  function openDialog(presets) {
    presets = presets || {};
    form.reset();
    activityDate.value = todayISO();
    dealDate.value = todayISO();
    const remembered = lastCompany();
    const company = presets.company || remembered || "";
    linkMode.value = presets.dealId
      ? "existing"
      : presets.product && !presets.dealId
        ? "new"
        : "existing";
    companyInput.value = company;
    stageSelect.value = presets.stage || "first_contact";
    productNew.value = presets.product || "";
    productHidden.value = presets.product || "";
    if (commentInput) commentInput.value = "";
    syncMode();
    syncChannelFromStage();
    if (company) loadDeals(company, presets.dealId);
    if (fullLink) {
      const q = new URLSearchParams({ tab: "log", return_to: "/deals" });
      if (company) q.set("company", company);
      if (presets.product) q.set("product", presets.product);
      if (presets.dealId) q.set("deal_id", presets.dealId);
      fullLink.href = "/add?" + q.toString();
    }
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
    // Focus notes when prefilled from a row; else company
    if (presets.dealId || presets.company) {
      if (commentInput) commentInput.focus();
      else companyInput.focus();
    } else {
      companyInput.focus();
    }
  }

  function closeDialog() {
    if (typeof dialog.close === "function") dialog.close();
    else dialog.removeAttribute("open");
  }

  if (openBtn) openBtn.addEventListener("click", function () {
    openDialog({});
  });
  if (closeBtn) closeBtn.addEventListener("click", closeDialog);
  if (cancelBtn) cancelBtn.addEventListener("click", closeDialog);

  document.querySelectorAll(".open-master-row").forEach(function (btn) {
    btn.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      openDialog({
        company: btn.dataset.company,
        product: btn.dataset.product,
        dealId: btn.dataset.dealId,
        stage: btn.dataset.stage,
      });
    });
  });

  linkMode.addEventListener("change", syncMode);
  stageSelect.addEventListener("change", syncChannelFromStage);

  let companyTimer = null;
  companyInput.addEventListener("input", function () {
    clearTimeout(companyTimer);
    companyTimer = setTimeout(function () {
      if (linkMode.value === "existing") loadDeals(companyInput.value.trim());
    }, 280);
  });

  dealSelect.addEventListener("change", function () {
    const opt = dealSelect.selectedOptions[0];
    if (!opt) return;
    if (opt.dataset.product) productHidden.value = opt.dataset.product;
    if (opt.dataset.stage) {
      stageSelect.value = opt.dataset.stage;
      syncChannelFromStage();
    }
  });

  form.addEventListener("submit", function () {
    dealDate.value = activityDate.value || todayISO();
    rememberCompany(companyInput.value.trim());
    const mode = linkMode.value;
    if (mode === "new") {
      productHidden.value = productNew.value;
      productNone.value = "";
    } else if (mode === "none") {
      productNone.value = productNew.value;
      productHidden.value = productNew.value;
    }
  });

  window.openMasterUpdate = openDialog;
})();
