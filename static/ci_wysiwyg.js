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

  /** ISO yyyy-mm-dd → 22-May-2026 for display */
  var _MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  function _fmtDateDisplay(iso) {
    if (!iso) return "";
    var parts = String(iso).trim().slice(0, 10).split("-");
    if (parts.length !== 3) return "";
    var y = parts[0], m = parseInt(parts[1], 10), d = parts[2];
    if (!y || !m || !d || m < 1 || m > 12) return "";
    return d + "-" + _MONTHS[m - 1] + "-" + y;
  }

  function bindDatePickers(root) {
    (root || document).querySelectorAll(".ci-date-wrap").forEach(function (wrap) {
      const native = wrap.querySelector(".ci-date-native");
      const show = wrap.querySelector(".ci-date-show");
      if (!native || !show) return;
      function sync() {
        show.value = _fmtDateDisplay(native.value);
      }
      sync();
      native.addEventListener("change", sync);
      native.addEventListener("input", sync);
    });
  }

  // ── Per-row recalc ────────────────────────────────────────────────────────
  function recalcRow(row) {
    const qty      = _float(row.querySelector(".ci-qty")    && row.querySelector(".ci-qty").value);
    const uprice   = _float(row.querySelector(".ci-uprice") && row.querySelector(".ci-uprice").value);
    const cif      = _float(row.querySelector(".ci-cif")    && row.querySelector(".ci-cif").value);
    const rate     = _float(row.querySelector(".ci-rate")   && row.querySelector(".ci-rate").value);

    const unit = uprice || cif;
    const fob = unit ? qty * unit : _float(row.querySelector(".ci-fob") && row.querySelector(".ci-fob").value);
    const fobOut = row.querySelector(".ci-fob-out");
    if (fobOut) fobOut.textContent = "$" + _num(fob);
    const fobHidden = row.querySelector(".ci-fob");
    if (fobHidden) fobHidden.value = fob.toFixed(2);

    // commission = fob × rate / 100
    const comm = fob * rate / 100;
    const commOut = row.querySelector(".ci-line-value");
    if (commOut) commOut.textContent = "$ " + _money(comm);

    return comm;
  }

  // ── Grand totals ──────────────────────────────────────────────────────────
  function recalcTotals() {
    const rows = document.querySelectorAll("#ci-lines-body .ci-line-row");
    let total  = 0;
    rows.forEach(function (r) { total += recalcRow(r); });

    const vatPct = 0;
    const net = total;
    const vat = net * vatPct / 100;
    const pay = net + vat;

    function set(id, v) {
      const el = document.getElementById(id);
      if (el) el.textContent = _money(v);
    }
    set("ci-total-commission", total);
    const totEl = document.getElementById("ci-total-commission");
    if (totEl) totEl.textContent = "$ " + _money(total);
  }

  // ── Bind inputs in a row ──────────────────────────────────────────────────
  function bindRow(row) {
    row.querySelectorAll(".ci-qty, .ci-uprice, .ci-cif, .ci-rate").forEach(function (inp) {
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
    clone.querySelectorAll(".ci-rm").forEach(function (btn) {
      btn.addEventListener("click", function () { clone.remove(); recalcTotals(); });
    });
    clone.querySelectorAll("input[type='hidden']").forEach(function (inp) {
      inp.value = "0";
    });
    clone.querySelectorAll("output").forEach(function (o) {
      if (o.classList.contains("ci-line-value")) o.textContent = "$ 0.00";
      else if (o.classList.contains("ci-fob-out")) o.textContent = "$0.00";
      else o.textContent = "0.00";
    });
    return clone;
  }

  document.addEventListener("DOMContentLoaded", function () {
    bindDatePickers(document);

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
        tbody.appendChild(row);
        bindRow(row);
        recalcTotals();
      });
    }

    tbody.querySelectorAll(".ci-rm").forEach(function (btn) {
      btn.addEventListener("click", function () {
        btn.closest(".ci-line-row").remove();
        recalcTotals();
      });
    });

    // VAT % change
    if (vatInp) vatInp.addEventListener("input", recalcTotals);

    // Initial calc pass
    recalcTotals();
  });
})();
