(function () {
  function detailFor(summary) {
    const detail = summary && summary.nextElementSibling;
    if (!detail) return null;
    if (detail.classList.contains("deals-detail")) return detail;
    return null;
  }

  function setExpanded(summary, open) {
    const detail = detailFor(summary);
    const btn = summary && summary.querySelector(".row-toggle");
    if (!detail || !btn) return;
    detail.hidden = !open;
    summary.classList.toggle("is-expanded", open);
    btn.setAttribute("aria-expanded", open ? "true" : "false");
    const hideLabel = summary.classList.contains("deals-list-row")
      ? "Hide previous updates"
      : "Hide details";
    const showLabel = summary.classList.contains("deals-list-row")
      ? "Show previous updates"
      : "Show details";
    btn.setAttribute("aria-label", open ? hideLabel : showLabel);
    btn.title = open ? hideLabel : showLabel;
  }

  document.querySelectorAll(".row-toggle").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const summary =
        btn.closest(".deals-summary") || btn.closest(".deals-list-row");
      const detail = detailFor(summary);
      if (!detail) return;
      setExpanded(summary, detail.hidden);
    });
  });

  // Group rows: click summary (except controls) toggles expand.
  document.querySelectorAll(".deals-summary").forEach((summary) => {
    summary.addEventListener("click", (e) => {
      if (e.target.closest("a, button, input, select")) return;
      const detail = detailFor(summary);
      if (!detail) return;
      setExpanded(summary, detail.hidden);
    });
  });

  // List rows: arrow / "earlier updates" hint toggles history; row click still navigates.
  document.querySelectorAll(".deals-list-row.has-history").forEach((row) => {
    const hint = row.querySelector(".activity-more-hint");
    if (!hint) return;
    hint.style.cursor = "pointer";
    hint.addEventListener("click", (e) => {
      e.stopPropagation();
      const detail = detailFor(row);
      if (!detail) return;
      setExpanded(row, detail.hidden);
    });
  });

  // Auto-expand when filtered to one group or few results (grouped views only).
  const summaries = document.querySelectorAll(".deals-summary");
  const params = new URLSearchParams(window.location.search);
  const filtered = !!(params.get("company") || params.get("product"));
  if (summaries.length === 1 || (filtered && summaries.length <= 5)) {
    summaries.forEach((summary) => setExpanded(summary, true));
  }
})();
