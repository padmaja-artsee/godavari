/**
 * Delivery Note live calculations.
 * Chain: number_of_packs × per-pack weights → totals → total gross (+ pallet)
 * Self-contained – no shared code with other document scripts.
 */
(function () {
  "use strict";

  function _float(v) {
    const n = parseFloat(String(v || "").replace(/,/g, ""));
    return isNaN(n) ? 0 : n;
  }

  function _fmt(v) {
    const n = _float(v);
    return n === 0 ? "0.00"
      : n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function _setOut(sel, v) {
    const el = document.querySelector(sel);
    if (el) el.textContent = _fmt(v);
  }

  function recalc() {
    const nPacks    = _float(q(".dn-num-packs")   && q(".dn-num-packs").value);
    const netEach   = _float(q(".dn-net-each")    && q(".dn-net-each").value);
    const tareEach  = _float(q(".dn-tare-each")   && q(".dn-tare-each").value);
    const grossEach = _float(q(".dn-gross-each")  && q(".dn-gross-each").value);
    const palletWt  = _float(q(".dn-pallet-wt")   && q(".dn-pallet-wt").value);

    const tNet   = nPacks * netEach;
    const tTar   = nPacks * tareEach;
    const tGro   = nPacks * grossEach + palletWt;
    const totQty = tNet;   // mirrors net weight for kgs

    // Packaging table — number-of-packs row
    document.querySelectorAll(".dn-out-npacks, .dn-out-npacks2, .dn-out-npacks3")
      .forEach(function (el) { el.textContent = nPacks || "0"; });

    // Packaging table — total weight row
    _setOut(".dn-out-tnet", tNet);
    _setOut(".dn-out-ttar", tTar);
    _setOut(".dn-out-tgro", tGro);

    // Footer total gross
    _setOut("#dn-total-gross", tGro);

    // Mirror into total_quantity field if it hasn't been manually set
    const tqEl = q(".dn-total-qty");
    if (tqEl && !tqEl.dataset.manual) tqEl.value = tNet ? tNet.toFixed(2) : "";
  }

  function q(sel) { return document.querySelector(sel); }

  document.addEventListener("DOMContentLoaded", function () {
    const watched = [".dn-num-packs", ".dn-net-each", ".dn-tare-each",
                     ".dn-gross-each", ".dn-pallet-wt"];
    watched.forEach(function (sel) {
      const el = document.querySelector(sel);
      if (el) el.addEventListener("input", recalc);
    });

    // Mark total_qty as manually edited if user types in it
    const tqEl = q(".dn-total-qty");
    if (tqEl) {
      tqEl.addEventListener("input", function () {
        tqEl.dataset.manual = "1";
      });
    }

    recalc();
  });
})();
