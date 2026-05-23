(function () {
  const form = document.getElementById("po-editor-form");
  if (!form) return;

  const currencyInput = document.getElementById("po-currency");
  const grandTotalEl = document.getElementById("grand-total");

  function num(v) {
    const n = parseFloat(String(v || "").replace(/,/g, ""));
    return isNaN(n) ? 0 : n;
  }

  function fmt(n, d) {
    return Number(n).toLocaleString(undefined, {
      minimumFractionDigits: d,
      maximumFractionDigits: d,
    });
  }

  function currency() {
    return (currencyInput && currencyInput.value) || "Euro";
  }

  function batchRows(section) {
    // batches now live in the sibling .po-sub-section
    const sub = section.nextElementSibling;
    if (sub && sub.classList.contains("po-sub-section")) return sub;
    return section.parentElement;
  }

  function recalcSection(section) {
    const packSize = num(section.querySelector(".calc-pack-size")?.value);
    const numPacks = num(section.querySelector(".calc-num-packs")?.value);
    const rate = num(section.querySelector(".calc-rate")?.value);
    const pricing = packSize * numPacks;
    const value = pricing * rate;

    section.querySelectorAll(".calc-pricing-readout").forEach(function (el) {
      el.textContent = pricing ? fmt(pricing, 3) : "";
    });

    const commInput = section.querySelector(".calc-commercial-sync");
    if (commInput && pricing) {
      commInput.value = (pricing / 1000).toFixed(4).replace(/\.?0+$/, "");
    }

    section.querySelectorAll(".calc-value-readout, .calc-value-readout-secondary").forEach(function (el) {
      el.textContent = fmt(value, 2);
    });

    const sub = batchRows(section);
    let batchSum = 0;
    sub.querySelectorAll(".calc-batch-qty").forEach(function (el) {
      batchSum += num(el.value);
    });
    const commercial = num(section.querySelector(".calc-commercial-sync")?.value);

    const warnings = [];
    if (commercial && batchSum && Math.abs(commercial - batchSum) > 0.01) {
      warnings.push("Batch total (" + fmt(batchSum, 2) + " MT) does not match commercial quantity (" + fmt(commercial, 2) + " MT).");
    }
    if (packSize && numPacks && !pricing) {
      warnings.push("Pack size × number of packs must be greater than zero.");
    }

    const warnEl = sub.querySelector("[data-line-warnings]");
    if (warnEl) {
      if (warnings.length) {
        warnEl.hidden = false;
        warnEl.textContent = warnings.join(" ");
      } else {
        warnEl.hidden = true;
        warnEl.textContent = "";
      }
    }
    return value;
  }

  function recalcAll() {
    let total = 0;
    form.querySelectorAll("[data-line-section]").forEach(function (section) {
      total += recalcSection(section);
    });
    if (grandTotalEl) grandTotalEl.textContent = fmt(total, 2) + " " + currency();
  }

  function bindBatchButtons(section) {
    const sub = batchRows(section);
    const addBtn = sub.querySelector(".add-batch-btn");
    if (!addBtn) return;
    const tbodyEl = sub.querySelector("[data-batch-rows]");
    const idx = tbodyEl ? tbodyEl.dataset.lineIndex || "0" : "0";

    addBtn.addEventListener("click", function () {
      const tbody = tbodyEl || sub.querySelector("tbody");
      const tr = document.createElement("tr");
      tr.className = "batch-row";
      tr.innerHTML =
        '<td><input class="po-input" name="batch_name_' + idx + '" placeholder="BATCH" /></td>' +
        '<td class="po-num"><input class="po-number-input calc-batch-qty" name="batch_quantity_' + idx + '" /></td>' +
        '<td><input class="po-unit-input" name="batch_unit_' + idx + '" value="MT" /></td>' +
        '<td class="no-print"><button type="button" class="btn btn-ghost btn-sm remove-batch-btn">×</button></td>';
      tbody.appendChild(tr);
      tr.querySelector(".remove-batch-btn").addEventListener("click", function () {
        tr.remove();
        recalcAll();
      });
      recalcAll();
    });

    sub.querySelectorAll(".remove-batch-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        btn.closest(".batch-row")?.remove();
        recalcAll();
      });
    });

    sub.addEventListener("input", recalcAll);
  }

  form.querySelectorAll("[data-line-section]").forEach(function (section) {
    section.addEventListener("input", recalcAll);
    bindBatchButtons(section);
  });

  form.querySelector('[name="incoterm_terms"]')?.addEventListener("input", function (e) {
    form.querySelectorAll(".calc-incoterm").forEach(function (el) {
      if (!el.dataset.userEdited) el.value = e.target.value;
    });
  });

  form.querySelectorAll(".calc-incoterm").forEach(function (el) {
    el.addEventListener("input", function () {
      el.dataset.userEdited = "1";
    });
  });

  currencyInput?.addEventListener("input", recalcAll);

  form.querySelectorAll(".po-textarea").forEach(function (ta) {
    function resize() {
      ta.style.height = "auto";
      ta.style.height = ta.scrollHeight + "px";
    }
    ta.addEventListener("input", resize);
    resize();
  });

  recalcAll();
})();
