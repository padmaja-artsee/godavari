(function () {
  function syncOther(select) {
    var wrapId = select.getAttribute("data-other-wrap");
    if (!wrapId) return;
    var wrap = document.getElementById(wrapId);
    if (!wrap) return;
    wrap.style.display = select.value === "Other" ? "" : "none";
  }
  document.querySelectorAll(".qty-unit-select").forEach(function (sel) {
    syncOther(sel);
    sel.addEventListener("change", function () {
      syncOther(sel);
    });
  });
})();
