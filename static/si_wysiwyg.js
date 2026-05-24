/**
 * Commercial (Sales) Invoice live calculations.
 * Chain: qty × rate → line value → net value → VAT → total to pay
 * Self-contained – no shared code with po_wysiwyg.js or ci_wysiwyg.js.
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
    const qty  = _float(row.querySelector(".si-qty")  && row.querySelector(".si-qty").value);
    const rate = _float(row.querySelector(".si-rate") && row.querySelector(".si-rate").value);
    const val  = qty * rate;

    const out = row.querySelector(".si-line-value");
    if (out) out.textContent = _money(val);
    const hidden = row.querySelector(".si-val-hidden");
    if (hidden) hidden.value = val.toFixed(2);

    return val;
  }

  // ── Grand totals ──────────────────────────────────────────────────────────
  function recalcTotals() {
    const rows = document.querySelectorAll("#si-lines-body .si-line-row");
    let net    = 0;
    rows.forEach(function (r) { net += recalcRow(r); });

    const vatPct = _float(
      document.querySelector(".si-vat-pct") && document.querySelector(".si-vat-pct").value
    );
    const vat = net * vatPct / 100;
    const pay = net + vat;

    function set(id, v) {
      const el = document.getElementById(id);
      if (el) el.textContent = _money(v);
    }
    set("si-net-value",  net);
    set("si-net-total",  net);   // in-table running total
    set("si-vat-amount", vat);
    set("si-total-pay",  pay);
  }

  // ── Bind a row ────────────────────────────────────────────────────────────
  function bindRow(row) {
    row.querySelectorAll(".si-qty, .si-rate").forEach(function (inp) {
      inp.addEventListener("input", recalcTotals);
    });
  }

  // ── Clone a blank row from template ──────────────────────────────────────
  function makeBlankRow() {
    const tmpl = document.querySelector("#si-lines-body .si-line-row");
    if (!tmpl) return null;
    const clone = tmpl.cloneNode(true);
    clone.querySelectorAll("input:not([type='hidden'])").forEach(function (inp) {
      inp.value = "";
    });
    clone.querySelectorAll("input[type='hidden']").forEach(function (inp) {
      inp.value = "0";
    });
    clone.querySelectorAll("output").forEach(function (o) { o.textContent = "0.00"; });
    return clone;
  }

  document.addEventListener("DOMContentLoaded", function () {
    const tbody  = document.getElementById("si-lines-body");
    const addBtn = document.getElementById("si-add-line");
    const vatInp = document.querySelector(".si-vat-pct");

    if (!tbody) return;

    tbody.querySelectorAll(".si-line-row").forEach(bindRow);

    if (addBtn) {
      addBtn.addEventListener("click", function () {
        const row = makeBlankRow();
        if (!row) return;
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

    if (vatInp) vatInp.addEventListener("input", recalcTotals);

    recalcTotals();
  });
})();
