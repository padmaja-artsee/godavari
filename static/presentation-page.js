/* Presentation tab — manage deck + fullscreen slideshow. */
(function () {
  var Deck = window.PresentationDeck;
  if (!Deck) return;

  var deckEl = document.getElementById("presDeck");
  var emptyEl = document.getElementById("presEmpty");
  var startBtn = document.getElementById("presStartBtn");
  var clearBtn = document.getElementById("presClearBtn");
  var showEl = document.getElementById("presShow");
  var showImg = document.getElementById("presShowImg");
  var showTitle = document.getElementById("presShowTitle");
  var showMeta = document.getElementById("presShowMeta");
  var showDots = document.getElementById("presShowDots");
  var showing = false;
  var index = 0;

  function slides() {
    return Deck.load();
  }

  function sourceLabel(src) {
    if (src === "commission") return "Summary · Commission";
    if (src === "generate") return "Generate · Charts";
    return src || "Chart";
  }

  function renderList() {
    var list = slides();
    var has = list.length > 0;
    if (emptyEl) emptyEl.hidden = has;
    if (deckEl) deckEl.hidden = !has;
    if (startBtn) startBtn.disabled = !has;
    if (clearBtn) clearBtn.disabled = !has;
    if (!deckEl) return;
    if (!has) {
      deckEl.innerHTML = "";
      return;
    }
    deckEl.innerHTML = list
      .map(function (s, i) {
        return (
          '<article class="pres-slide-card" data-id="' +
          s.id +
          '">' +
          '<div class="pres-slide-thumb"><img src="' +
          s.image +
          '" alt="" /></div>' +
          '<div class="pres-slide-body">' +
          '<div class="pres-slide-idx">' +
          (i + 1) +
          "</div>" +
          '<input class="pres-slide-title" type="text" value="' +
          escapeAttr(s.title) +
          '" data-rename="' +
          s.id +
          '" />' +
          '<div class="pres-slide-sub">' +
          escapeHtml(s.subtitle || sourceLabel(s.source)) +
          "</div>" +
          '<div class="pres-slide-actions">' +
          '<button type="button" class="btn btn-ghost btn-sm" data-up="' +
          s.id +
          '"' +
          (i === 0 ? " disabled" : "") +
          ">↑</button>" +
          '<button type="button" class="btn btn-ghost btn-sm" data-down="' +
          s.id +
          '"' +
          (i === list.length - 1 ? " disabled" : "") +
          ">↓</button>" +
          '<button type="button" class="btn btn-ghost btn-sm" data-play="' +
          s.id +
          '">Play from here</button>' +
          '<button type="button" class="btn btn-ghost btn-sm" data-remove="' +
          s.id +
          '">Remove</button>' +
          "</div></div></article>"
        );
      })
      .join("");
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function escapeAttr(s) {
    return escapeHtml(s).replace(/'/g, "&#39;");
  }

  function showSlide(i) {
    var list = slides();
    if (!list.length) {
      stopShow();
      return;
    }
    index = ((i % list.length) + list.length) % list.length;
    var s = list[index];
    if (showImg) {
      showImg.src = s.image;
      showImg.alt = s.title;
    }
    if (showTitle) showTitle.textContent = s.title;
    if (showMeta) {
      showMeta.textContent =
        sourceLabel(s.source) +
        (s.subtitle ? " · " + s.subtitle : "") +
        "  ·  " +
        (index + 1) +
        "/" +
        list.length;
    }
    if (showDots) {
      showDots.innerHTML = list
        .map(function (_, di) {
          return (
            '<button type="button" class="pres-dot' +
            (di === index ? " active" : "") +
            '" data-dot="' +
            di +
            '" aria-label="Slide ' +
            (di + 1) +
            '"></button>'
          );
        })
        .join("");
    }
  }

  function startShow(fromId) {
    var list = slides();
    if (!list.length) return;
    index = 0;
    if (fromId) {
      var found = list.findIndex(function (s) {
        return s.id === fromId;
      });
      if (found >= 0) index = found;
    }
    showing = true;
    document.body.classList.add("pres-showing");
    if (showEl) showEl.hidden = false;
    showSlide(index);
    try {
      if (document.documentElement.requestFullscreen) {
        document.documentElement.requestFullscreen().catch(function () {});
      }
    } catch (e) {}
  }

  function stopShow() {
    showing = false;
    document.body.classList.remove("pres-showing");
    if (showEl) showEl.hidden = true;
    if (document.fullscreenElement) {
      try {
        document.exitFullscreen();
      } catch (e) {}
    }
  }

  if (deckEl) {
    deckEl.addEventListener("click", function (e) {
      var t = e.target;
      if (!t) return;
      var up = t.getAttribute("data-up");
      var down = t.getAttribute("data-down");
      var rem = t.getAttribute("data-remove");
      var play = t.getAttribute("data-play");
      if (up) {
        Deck.moveSlide(up, -1);
        renderList();
      } else if (down) {
        Deck.moveSlide(down, 1);
        renderList();
      } else if (rem) {
        Deck.removeSlide(rem);
        renderList();
      } else if (play) {
        startShow(play);
      }
    });
    deckEl.addEventListener("change", function (e) {
      var t = e.target;
      if (t && t.getAttribute("data-rename")) {
        Deck.renameSlide(t.getAttribute("data-rename"), t.value);
      }
    });
  }

  if (startBtn) startBtn.addEventListener("click", function () {
    startShow();
  });
  if (clearBtn) {
    clearBtn.addEventListener("click", function () {
      var p = window.appConfirm
        ? window.appConfirm("Remove all slides from this presentation?", "Clear")
        : Promise.resolve(confirm("Remove all slides from this presentation?"));
      Promise.resolve(p).then(function (ok) {
        if (!ok) return;
        Deck.clearAll();
        renderList();
      });
    });
  }

  var exitBtn = document.getElementById("presShowExit");
  if (exitBtn) exitBtn.addEventListener("click", stopShow);
  var prevBtn = document.getElementById("presPrev");
  var nextBtn = document.getElementById("presNext");
  if (prevBtn)
    prevBtn.addEventListener("click", function () {
      showSlide(index - 1);
    });
  if (nextBtn)
    nextBtn.addEventListener("click", function () {
      showSlide(index + 1);
    });
  if (showDots) {
    showDots.addEventListener("click", function (e) {
      var t = e.target;
      if (!t || !t.getAttribute("data-dot")) return;
      showSlide(parseInt(t.getAttribute("data-dot"), 10));
    });
  }

  document.addEventListener("fullscreenchange", function () {
    if (!document.fullscreenElement && showing) stopShow();
  });

  document.addEventListener("keydown", function (e) {
    if (e.target && /INPUT|TEXTAREA|SELECT/.test(e.target.tagName) && !showing) return;
    if (!showing) return;
    if (e.key === "Escape") {
      e.preventDefault();
      stopShow();
    } else if (e.key === "ArrowRight" || e.key === " " || e.key === "n" || e.key === "N") {
      e.preventDefault();
      showSlide(index + 1);
    } else if (e.key === "ArrowLeft" || e.key === "p" || e.key === "P") {
      e.preventDefault();
      showSlide(index - 1);
    } else if (e.key === "Home") {
      e.preventDefault();
      showSlide(0);
    } else if (e.key === "End") {
      e.preventDefault();
      showSlide(slides().length - 1);
    }
  });

  window.addEventListener("presentation-deck-changed", renderList);
  renderList();
})();
