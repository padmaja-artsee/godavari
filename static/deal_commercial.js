(function () {
  "use strict";

  function parseNum(v) {
    if (!v) return 0;
    var m = String(v).replace(/,/g, "").match(/-?\d+(?:\.\d+)?/);
    return m ? parseFloat(m[0]) : 0;
  }

  function formatTotal(n) {
    if (!n && n !== 0) return "";
    if (n === Math.floor(n)) return String(Math.floor(n));
    return n.toFixed(2).replace(/\.?0+$/, "");
  }

  function qtyPriceInForm(form) {
    var qtyEl = form.querySelector('[name="quantity"], [name="deal_quantity"]');
    var priceEl = form.querySelector(
      '[name="price"], [name="deal_price"], #deal-commercial-price, #f-price'
    );
    return { qtyEl: qtyEl, priceEl: priceEl };
  }

  function syncFormCommercial(form) {
    if (!form) return;
    var pair = qtyPriceInForm(form);
    var qty = pair.qtyEl ? parseNum(pair.qtyEl.value) : 0;
    var price = pair.priceEl ? parseNum(pair.priceEl.value) : 0;
    var value = qty && price ? qty * price : 0;

    var valueEl = form.querySelector(".deal-commercial-value");
    if (valueEl) valueEl.value = value ? formatTotal(value) : "";

    var ins = parseNum(form.querySelector('[name="insurance_amount"]') && form.querySelector('[name="insurance_amount"]').value);
    var freight = parseNum(form.querySelector('[name="ocean_freight_amount"]') && form.querySelector('[name="ocean_freight_amount"]').value);
    var fob = value ? value - ins - freight : 0;

    var fobEl = form.querySelector(".deal-commercial-fob");
    if (fobEl) fobEl.value = value ? formatTotal(fob) : "";

    var rate = parseNum(form.querySelector('[name="commission_rate"]') && form.querySelector('[name="commission_rate"]').value);
    var commission = fob && rate ? (fob * rate) / 100 : 0;

    var commEl = form.querySelector(".deal-commercial-commission");
    if (commEl) commEl.value = fob && rate ? formatTotal(commission) : "";
  }

  function syncCommercialValues() {
    document.querySelectorAll("form").forEach(syncFormCommercial);
  }

  function bindForm(form) {
    if (!form) return;
    var pair = qtyPriceInForm(form);
    var triggers = [pair.qtyEl, pair.priceEl];
    form.querySelectorAll(".deal-calc-input").forEach(function (el) {
      triggers.push(el);
    });
    triggers.forEach(function (el) {
      if (!el) return;
      el.addEventListener("input", syncCommercialValues);
      el.addEventListener("change", syncCommercialValues);
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("form").forEach(bindForm);
    syncCommercialValues();
  });

  window.syncCommercialValues = syncCommercialValues;
})();
