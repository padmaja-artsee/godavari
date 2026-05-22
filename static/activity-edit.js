(function () {
  function closeAllEdits() {
    document.querySelectorAll(".activity-edit-row").forEach((r) => {
      r.hidden = true;
    });
    document.querySelectorAll(".activity-view").forEach((r) => {
      r.hidden = false;
    });
  }

  function setLinkMode(form, mode) {
    form.querySelectorAll("[data-panel]").forEach((panel) => {
      const active = panel.dataset.panel === mode;
      panel.style.display = active ? "block" : "none";
      panel.querySelectorAll("input, select, textarea").forEach((el) => {
        el.disabled = !active;
      });
    });
  }

  function initLinkModeForm(form) {
    if (!form || form.dataset.linkInit) return;
    form.dataset.linkInit = "1";
    form.querySelectorAll('input[name="link_mode"]').forEach((el) => {
      el.addEventListener("change", () => setLinkMode(form, el.value));
    });
    form.addEventListener("submit", () => {
      const checked = form.querySelector('input[name="link_mode"]:checked');
      if (checked) setLinkMode(form, checked.value);
    });
    const checked = form.querySelector('input[name="link_mode"]:checked');
    setLinkMode(form, checked ? checked.value : "none");
  }

  document.querySelectorAll(".activity-edit-form").forEach(initLinkModeForm);

  document.querySelectorAll(".btn-edit-activity").forEach((btn) => {
    btn.addEventListener("click", () => {
      const viewRow = btn.closest(".activity-view");
      const id = viewRow && viewRow.getAttribute("data-activity-id");
      if (!id) return;
      closeAllEdits();
      viewRow.hidden = true;
      const editRow = document.getElementById("edit-activity-" + id);
      if (editRow) {
        editRow.hidden = false;
        const form = editRow.querySelector(".activity-edit-form");
        if (form) initLinkModeForm(form);
      }
    });
  });

  document.querySelectorAll(".btn-cancel-edit").forEach((btn) => {
    btn.addEventListener("click", closeAllEdits);
  });
})();
