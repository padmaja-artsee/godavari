/**
 * Commission Invoice live calculations.
 * Chain: qty × unit_price → fob_value (hidden) → commission_value → grand totals
 * Self-contained – no shared code with po_wysiwyg.js.
 */
(function () {
  "use strict";

  function _float(v) {
    const n = parseFloat(String(v || "").replace(/,/g, ""));
    return isNaN(n) ? 0 : n;
  }

  function _money(v) {
    return _float(v).toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  }

  function _num(v) {
    const n = _float(v);
    return n === 0 ? "0.00" : n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  // ── Per-row recalc ────────────────────────────────────────────────────────
  function recalcRow(row) {
    const qty      = _float(row.querySelector(".ci-qty")    && row.querySelector(".ci-qty").value);
    const uprice   = _float(row.querySelector(".ci-uprice") && row.querySelector(".ci-uprice").value);
    const rate     = _float(row.querySelector(".ci-rate")   && row.querySelector(".ci-rate").value);

    // fob = qty × unit_price
    const fob = uprice ? qty * uprice : 0;
    const fobOut = row.querySelector(".ci-fob-out");
    if (fobOut) fobOut.textContent = _num(fob);
    const fobHidden = row.querySelector(".ci-fob");
    if (fobHidden) fobHidden.value = fob.toFixed(2);

    // commission = fob × rate / 100
    const comm = fob * rate / 100;
    const commOut = row.querySelector(".ci-line-value");
    if (commOut) commOut.textContent = _money(comm);

    return comm;
  }

  // ── Grand totals ──────────────────────────────────────────────────────────
  function recalcTotals() {
    const rows = document.querySelectorAll("#ci-lines-body .ci-line-row");
    let total  = 0;
    rows.forEach(function (r) { total += recalcRow(r); });

    const vatPct = _float(
      document.querySelector(".ci-vat-pct") && document.querySelector(".ci-vat-pct").value
    );
    const net = total;
    const vat = net * vatPct / 100;
    const pay = net + vat;

    function set(id, v) {
      const el = document.getElementById(id);
      if (el) el.textContent = _money(v);
    }
    set("ci-total-commission", total);
    set("ci-net-value",        net);
    set("ci-vat-amount",       vat);
    set("ci-total-pay",        pay);
  }

  // ── Bind inputs in a row ──────────────────────────────────────────────────
  function bindRow(row) {
    row.querySelectorAll(".ci-qty, .ci-uprice, .ci-rate").forEach(function (inp) {
      inp.addEventListener("input", recalcTotals);
    });
  }

  // ── Build a blank editable row matching the template ─────────────────────
  function makeBlankRow() {
    const tmpl = document.querySelector("#ci-lines-body .ci-line-row");
    if (!tmpl) return null;
    const clone = tmpl.cloneNode(true);
    clone.querySelectorAll("input:not([type='hidden'])").forEach(function (inp) {
      inp.value = inp.classList.contains("ci-rate") ? "3" : "";
    });
    clone.querySelectorAll("input[type='hidden']").forEach(function (inp) {
      inp.value = "0";
    });
    clone.querySelectorAll("output").forEach(function (o) { o.textContent = "0.00"; });
    return clone;
  }

  document.addEventListener("DOMContentLoaded", function () {
    const tbody  = document.getElementById("ci-lines-body");
    const addBtn = document.getElementById("ci-add-line");
    const vatInp = document.querySelector(".ci-vat-pct");

    if (!tbody) return;

    // Bind existing rows
    tbody.querySelectorAll(".ci-line-row").forEach(bindRow);

    // Add line button
    if (addBtn) {
      addBtn.addEventListener("click", function () {
        const row = makeBlankRow();
        if (!row) return;
        // Append a remove button cell
        const td  = document.createElement("td");
        const btn = document.createElement("button");
        btn.type      = "button";
        btn.className = "btn btn-ghost btn-sm no-print";
        btn.textContent = "×";
        btn.addEventListener("click", function () { row.remove(); recalcTotals(); });
        td.appendChild(btn);
        row.appendChild(td);
        tbody.appendChild(row);
        bindRow(row);
        recalcTotals();
      });
    }

    // VAT % change
    if (vatInp) vatInp.addEventListener("input", recalcTotals);

    // Initial calc pass
    recalcTotals();
  });
})();
