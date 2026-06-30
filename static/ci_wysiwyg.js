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

  var _ONES = [
    "Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
    "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
    "Seventeen", "Eighteen", "Nineteen"
  ];
  var _TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"];

  function _underThousand(n) {
    if (n < 20) return _ONES[n];
    if (n < 100) {
      var t = Math.floor(n / 10);
      var o = n % 10;
      return (_TENS[t] + (o ? " " + _ONES[o] : "")).trim();
    }
    var h = Math.floor(n / 100);
    var rem = n % 100;
    return _ONES[h] + " Hundred" + (rem ? " " + _underThousand(rem) : "");
  }

  function _intWords(n) {
    if (n === 0) return "Zero";
    var parts = [];
    var chunks = [
      ["Million", 1000000],
      ["Thousand", 1000],
      ["", 1]
    ];
    chunks.forEach(function (pair) {
      var label = pair[0];
      var div = pair[1];
      if (n >= div) {
        var chunk = Math.floor(n / div);
        n = n % div;
        var w = _underThousand(chunk);
        parts.push(label ? w + " " + label : w);
      }
    });
    return parts.join(" ");
  }

  function dollarsInWords(amount) {
    var v = Math.round(_float(amount) * 100) / 100;
    var dollars = Math.floor(v);
    var cents = Math.round((v - dollars) * 100);
    var words = _intWords(dollars) + " Dollar" + (dollars !== 1 ? "s" : "");
    if (cents) {
      words += " and " + _intWords(cents) + " Cent" + (cents !== 1 ? "s" : "");
    }
    return words;
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
        if (native.name === "invoice_date") syncNoticeDateFromInvoice();
      }
      sync();
      native.addEventListener("change", sync);
      native.addEventListener("input", sync);
    });
  }

  function syncNoticeDateFromInvoice() {
    const inv = document.querySelector('.ci-invoice-page .ci-date-native[name="invoice_date"]');
    if (!inv) return;
    const iso = (inv.value || "").trim().slice(0, 10);
    const display = _fmtDateDisplay(iso) || "—";
    document.querySelectorAll(".ci-notice-date-display").forEach(function (el) {
      el.textContent = display;
    });
    document.querySelectorAll(".ci-notice-date-hidden").forEach(function (el) {
      el.value = iso;
    });
  }

  // ── Per-row recalc ────────────────────────────────────────────────────────
  function recalcRow(row) {
    const qty      = _float(row.querySelector(".ci-qty")    && row.querySelector(".ci-qty").value);
    const uprice   = _float(row.querySelector(".ci-uprice") && row.querySelector(".ci-uprice").value);
    const cif      = _float(row.querySelector(".ci-cif")    && row.querySelector(".ci-cif").value);
    const rate     = _float(row.querySelector(".ci-rate")   && row.querySelector(".ci-rate").value);

    const fobHidden = row.querySelector(".ci-fob");
    const fobFromDeal = _float(fobHidden && fobHidden.value);
    const unit = uprice || cif;
    // FOB column is total $ from deal (Value − insurance − freight), not qty × CIF/MT
    const fob = unit ? qty * unit : fobFromDeal;
    const fobOut = row.querySelector(".ci-fob-out");
    if (fobOut) fobOut.textContent = "$" + _num(fob);
    if (fobHidden && unit) fobHidden.value = fob.toFixed(2);

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

    const wordsInp = document.querySelector('input[name="amount_in_words"]');
    if (wordsInp) wordsInp.value = dollarsInWords(total);

    syncNoticeRatesFromMain();
  }

  function syncNoticeRatesFromMain() {
    const mainRows = document.querySelectorAll("#ci-lines-body .ci-line-row");
    const noticeRates = document.querySelectorAll(".ci-notice-table .ci-notice-rate");
    mainRows.forEach(function (row, i) {
      const rateInp = row.querySelector(".ci-rate");
      const noticeInp = noticeRates[i];
      if (rateInp && noticeInp && document.activeElement !== noticeInp) {
        noticeInp.value = rateInp.value;
      }
    });
  }

  function syncMainRatesFromNotice(noticeInp) {
    const idx = parseInt(noticeInp.getAttribute("data-line-index") || "0", 10);
    const mainRows = document.querySelectorAll("#ci-lines-body .ci-line-row");
    const row = mainRows[idx];
    if (!row) return;
    const rateInp = row.querySelector(".ci-rate");
    if (rateInp) rateInp.value = noticeInp.value;
    recalcTotals();
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

  function syncNoticeContact() {
    const src = document.querySelector('.ci-invoice-page input[name="contact_person"]');
    const dst = document.querySelector(".ci-notice-contact-display");
    if (!src || !dst) return;
    dst.textContent = (src.value || "").trim() || "Padmaja Ganapathy";
  }

  document.addEventListener("DOMContentLoaded", function () {
    bindDatePickers(document);
    syncNoticeDateFromInvoice();

    const contactInp = document.querySelector('.ci-invoice-page input[name="contact_person"]');
    if (contactInp) {
      contactInp.addEventListener("input", syncNoticeContact);
      syncNoticeContact();
    }

    const tbody  = document.getElementById("ci-lines-body");
    const addBtn = document.getElementById("ci-add-line");
    const vatInp = document.querySelector(".ci-vat-pct");

    if (!tbody) return;

    // Print / preview: line values are server-rendered text, not inputs — do not recalc to $0
    if (!tbody.querySelector("input.ci-qty")) return;

    // Bind existing rows
    tbody.querySelectorAll(".ci-line-row").forEach(bindRow);

    document.querySelectorAll(".ci-notice-rate").forEach(function (inp) {
      inp.addEventListener("input", function () { syncMainRatesFromNotice(inp); });
    });

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
