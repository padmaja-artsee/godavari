/* MR Written Report composer — narrative + charts from ReportDeck. */
(function () {
  var Deck = window.ReportDeck;
  if (!Deck) return;

  var emptyEl = document.getElementById("rptEmpty");
  var editorEl = document.getElementById("rptEditor");
  var printEl = document.getElementById("rptPrint");
  var titleInp = document.getElementById("rptTitle");
  var periodInp = document.getElementById("rptPeriod");
  var summaryInp = document.getElementById("rptSummary");
  var printBtn = document.getElementById("rptPrintBtn");
  var clearBtn = document.getElementById("rptClearBtn");
  var draftBtn = document.getElementById("rptDraftBtn");

  function escapeHtml(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function sourceLabel(src) {
    if (src === "commission") return "Summary · Commission";
    if (src === "generate") return "Generate · Charts";
    if (src === "finance") return "Finance";
    return src || "Chart";
  }

  function loadMetaIntoForm() {
    var m = Deck.loadMeta();
    if (titleInp && m.title) titleInp.value = m.title;
    if (periodInp && m.period) periodInp.value = m.period;
    if (summaryInp && m.summary) summaryInp.value = m.summary;
    if (titleInp && !titleInp.value) {
      titleInp.value = "Management Report";
    }
  }

  function persistMeta() {
    Deck.saveMeta({
      title: (titleInp && titleInp.value) || "",
      period: (periodInp && periodInp.value) || "",
      summary: (summaryInp && summaryInp.value) || "",
    });
  }

  function renderEditor() {
    var list = Deck.load();
    var has = list.length > 0;
    if (emptyEl) emptyEl.hidden = has;
    if (editorEl) editorEl.hidden = !has;
    if (printBtn) printBtn.disabled = !has;
    if (clearBtn) clearBtn.disabled = !has;
    if (draftBtn) draftBtn.disabled = !has;
    if (!editorEl) return;
    if (!has) {
      editorEl.innerHTML = "";
      return;
    }
    editorEl.innerHTML = list
      .map(function (s, i) {
        return (
          '<section class="mr-card mr-rpt-section" data-id="' +
          s.id +
          '">' +
          '<div class="mr-rpt-section-head">' +
          '<div class="mr-rpt-section-idx">Section ' +
          (i + 1) +
          "</div>" +
          '<input type="text" class="mr-input mr-rpt-section-title" data-title="' +
          s.id +
          '" value="' +
          escapeHtml(s.title) +
          '" />' +
          '<div class="mr-rpt-section-sub">' +
          escapeHtml(s.subtitle || sourceLabel(s.source)) +
          "</div>" +
          "</div>" +
          '<div class="mr-rpt-section-grid">' +
          '<div class="mr-rpt-thumb"><img src="' +
          s.image +
          '" alt="" /></div>' +
          '<label class="mr-label">Written commentary' +
          '<textarea class="mr-input mr-rpt-textarea" rows="6" data-notes="' +
          s.id +
          '">' +
          escapeHtml(s.notes || "") +
          "</textarea></label>" +
          "</div>" +
          '<div class="mr-rpt-section-actions no-print">' +
          '<button type="button" class="mr-btn mr-btn-outline" data-up="' +
          s.id +
          '"' +
          (i === 0 ? " disabled" : "") +
          ">↑</button>" +
          '<button type="button" class="mr-btn mr-btn-outline" data-down="' +
          s.id +
          '"' +
          (i === list.length - 1 ? " disabled" : "") +
          ">↓</button>" +
          '<button type="button" class="mr-btn mr-btn-outline" data-redraft="' +
          s.id +
          '">Rewrite draft</button>' +
          '<button type="button" class="mr-btn mr-btn-danger" data-remove="' +
          s.id +
          '">Remove</button>' +
          "</div></section>"
        );
      })
      .join("");
  }

  function buildPrintView() {
    persistMeta();
    var list = Deck.load();
    var title = (titleInp && titleInp.value.trim()) || "Management Report";
    var period = (periodInp && periodInp.value.trim()) || "";
    var summary = (summaryInp && summaryInp.value.trim()) || "";

    document.getElementById("rptPrintTitle").textContent = title;
    document.getElementById("rptPrintPeriod").textContent = period;
    document.getElementById("rptPrintDate").textContent = new Date().toLocaleString();

    var sumWrap = document.getElementById("rptPrintSummaryWrap");
    var sumP = document.getElementById("rptPrintSummary");
    if (summary) {
      sumWrap.hidden = false;
      sumP.textContent = summary;
    } else {
      sumWrap.hidden = true;
      sumP.textContent = "";
    }

    var body = document.getElementById("rptPrintBody");
    body.innerHTML = list
      .map(function (s, i) {
        return (
          '<section class="mr-rpt-print-section">' +
          "<h2>" +
          (i + 1) +
          ". " +
          escapeHtml(s.title) +
          "</h2>" +
          (s.subtitle
            ? '<p class="mr-rpt-print-sub">' + escapeHtml(s.subtitle) + "</p>"
            : "") +
          '<p class="mr-rpt-print-notes">' +
          escapeHtml(s.notes || "").replace(/\n/g, "<br/>") +
          "</p>" +
          '<figure class="mr-rpt-print-fig"><img src="' +
          s.image +
          '" alt="' +
          escapeHtml(s.title) +
          '" /></figure>' +
          "</section>"
        );
      })
      .join("");

    if (printEl) printEl.hidden = false;
    document.body.classList.add("mr-rpt-printing");
  }

  function endPrintView() {
    document.body.classList.remove("mr-rpt-printing");
    if (printEl) printEl.hidden = true;
  }

  if (editorEl) {
    editorEl.addEventListener("click", function (e) {
      var t = e.target;
      if (!t) return;
      var up = t.getAttribute("data-up");
      var down = t.getAttribute("data-down");
      var rem = t.getAttribute("data-remove");
      var redraft = t.getAttribute("data-redraft");
      if (up) {
        Deck.moveSlide(up, -1);
        renderEditor();
      } else if (down) {
        Deck.moveSlide(down, 1);
        renderEditor();
      } else if (rem) {
        Deck.removeSlide(rem);
        renderEditor();
      } else if (redraft) {
        var list = Deck.load();
        var slide = list.find(function (s) {
          return s.id === redraft;
        });
        if (slide) {
          Deck.updateSlide(redraft, { notes: Deck.draftNarrative(slide) });
          renderEditor();
        }
      }
    });
    editorEl.addEventListener("change", function (e) {
      var t = e.target;
      if (!t) return;
      var tid = t.getAttribute("data-title");
      var nid = t.getAttribute("data-notes");
      if (tid) Deck.updateSlide(tid, { title: t.value });
      if (nid) Deck.updateSlide(nid, { notes: t.value });
    });
  }

  ["rptTitle", "rptPeriod", "rptSummary"].forEach(function (id) {
    var el = document.getElementById(id);
    if (el) el.addEventListener("change", persistMeta);
  });

  if (printBtn) {
    printBtn.addEventListener("click", function () {
      buildPrintView();
      setTimeout(function () {
        window.print();
        setTimeout(endPrintView, 300);
      }, 50);
    });
  }

  if (clearBtn) {
    clearBtn.addEventListener("click", function () {
      if (!confirm("Remove all charts from this written report?")) return;
      Deck.clearAll();
      renderEditor();
    });
  }

  if (draftBtn) {
    draftBtn.addEventListener("click", function () {
      var list = Deck.load();
      list.forEach(function (s) {
        if (!(s.notes || "").trim()) {
          Deck.updateSlide(s.id, { notes: Deck.draftNarrative(s) });
        }
      });
      renderEditor();
    });
  }

  window.addEventListener("report-deck-changed", renderEditor);
  window.addEventListener("afterprint", endPrintView);

  loadMetaIntoForm();
  renderEditor();
})();
