/**
 * Commission Invoice live calculations.
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

  // ── Per-row recalc ────────────────────────────────────────────────────────
  function recalcRow(row) {
    const fob  = _float(row.querySelector(".ci-fob")  && row.querySelector(".ci-fob").value);
    const rate = _float(row.querySelector(".ci-rate") && row.querySelector(".ci-rate").value);
    const val  = fob * rate / 100;
    const out  = row.querySelector(".ci-line-value");
    if (out) out.textContent = _money(val);
    return val;
  }

  // ── Grand totals ──────────────────────────────────────────────────────────
  function recalcTotals() {
    const rows   = document.querySelectorAll("#ci-lines-body .ci-line-row");
    let total    = 0;
    rows.forEach(function (r) { total += recalcRow(r); });

    const vatPct = _float(
      document.querySelector(".ci-vat-pct") && document.querySelector(".ci-vat-pct").value
    );
    const net    = total;
    const vat    = net * vatPct / 100;
    const pay    = net + vat;

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
    row.querySelectorAll(".ci-fob, .ci-rate").forEach(function (inp) {
      inp.addEventListener("input", recalcTotals);
    });
  }

  // ── Add / remove line rows ────────────────────────────────────────────────
  function makeBlankRow() {
    const tmpl = document.querySelector("#ci-lines-body .ci-line-row");
    if (!tmpl) return null;
    const clone = tmpl.cloneNode(true);
    clone.querySelectorAll("input").forEach(function (inp) {
      inp.value = inp.classList.contains("ci-rate") ? "3" : "";
    });
    clone.querySelectorAll("output").forEach(function (o) { o.textContent = "0.00"; });
    return clone;
  }

  document.addEventListener("DOMContentLoaded", function () {
    const tbody   = document.getElementById("ci-lines-body");
    const addBtn  = document.getElementById("ci-add-line");
    const vatInp  = document.querySelector(".ci-vat-pct");

    if (!tbody) return;

    // Bind existing rows
    tbody.querySelectorAll(".ci-line-row").forEach(bindRow);

    // Add line
    if (addBtn) {
      addBtn.addEventListener("click", function () {
        const row = makeBlankRow();
        if (!row) return;
        // Add remove button
        const td = document.createElement("td");
        const btn = document.createElement("button");
        btn.type = "button";
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

    // Initial calc
    recalcTotals();
  });
})();
