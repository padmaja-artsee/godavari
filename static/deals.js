(function () {
  const selectAll = document.getElementById("select-all");
  const checks = () => document.querySelectorAll(".deal-check");
  const bulkBar = document.getElementById("bulk-bar");
  const bulkCount = document.getElementById("bulk-count");
  const bulkForm = document.getElementById("bulk-form");
  const bulkActionInput = document.getElementById("bulk-action-input");
  const bulkIdFields = document.getElementById("bulk-id-fields");
  const bulkLogBtn = document.getElementById("bulk-log-btn");
  if (!bulkForm) return;

  function selected() {
    return [...checks()].filter((c) => c.checked);
  }

  function updateBulkLogLink() {
    if (!bulkLogBtn) return;
    const sel = selected();
    if (sel.length === 1) {
      const row = sel[0].closest("tr");
      const logLink = row && row.querySelector('a[href*="/add?tab=log"]');
      bulkLogBtn.href = logLink ? logLink.href : "/add?tab=log";
    } else if (sel.length > 1) {
      const row = sel[0].closest("tr");
      const logLink = row && row.querySelector('a[href*="/add?tab=log"]');
      const url = new URL(logLink ? logLink.href : "/add?tab=log", window.location.origin);
      url.searchParams.delete("deal_id");
      bulkLogBtn.href = url.pathname + url.search;
    } else {
      bulkLogBtn.href = "/add?tab=log";
    }
  }

  function updateBar() {
    const n = selected().length;
    if (bulkBar) bulkBar.hidden = n === 0;
    if (bulkCount) bulkCount.textContent = n + (n === 1 ? " selected" : " selected");
    updateBulkLogLink();
  }

  if (selectAll) {
    selectAll.addEventListener("change", () => {
      checks().forEach((c) => {
        c.checked = selectAll.checked;
      });
      updateBar();
    });
  }

  checks().forEach((c) => c.addEventListener("change", updateBar));

  document.querySelectorAll("[data-bulk]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const action = btn.getAttribute("data-bulk");
      const ids = selected().map((c) => c.value);
      if (!ids.length) {
        alert("Select at least one deal.");
        return;
      }
      const messages = {
        archive: "Archive " + ids.length + " deal(s)? They will be hidden from the dashboard.",
        delete: "Permanently delete " + ids.length + " deal(s)?",
        lost: "Mark " + ids.length + " deal(s) as lost?",
        shipped: "Mark " + ids.length + " deal(s) as shipped?",
        unarchive: "Restore " + ids.length + " deal(s) from archive?",
      };
      if (!confirm(messages[action] || "Apply to " + ids.length + " deal(s)?")) return;

      bulkIdFields.innerHTML = "";
      if (action === "lost") {
        const reason = prompt("Reason for lost (optional):", "");
        if (reason === null) return;
        let lr = bulkForm.querySelector('input[name="lost_reason"]');
        if (!lr) {
          lr = document.createElement("input");
          lr.type = "hidden";
          lr.name = "lost_reason";
          bulkForm.appendChild(lr);
        }
        lr.value = reason;
      }
      ids.forEach((id) => {
        const inp = document.createElement("input");
        inp.type = "hidden";
        inp.name = "deal_ids";
        inp.value = id;
        bulkIdFields.appendChild(inp);
      });
      bulkActionInput.value = action;
      bulkForm.submit();
    });
  });
})();
