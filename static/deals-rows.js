(function () {
  document.querySelectorAll(".row-toggle").forEach((btn) => {
    btn.addEventListener("click", () => {
      const summary = btn.closest(".deals-summary");
      const detail = summary && summary.nextElementSibling;
      if (!detail || !detail.classList.contains("deals-detail")) return;

      const open = detail.hidden;
      detail.hidden = !open;
      summary.classList.toggle("is-expanded", open);
      btn.setAttribute("aria-expanded", open ? "true" : "false");
      btn.setAttribute("aria-label", open ? "Hide details" : "Show details");
      btn.title = open ? "Hide details" : "Show details";
    });
  });
})();
