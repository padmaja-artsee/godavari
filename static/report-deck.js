/* Shared MR written-report deck — charts curated for narrative report. */
(function (global) {
  var KEY = "gbinc-mr-report-deck-v1";
  var META_KEY = "gbinc-mr-report-meta-v1";
  var MAX_SLIDES = 40;

  function uid() {
    return "r" + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
  }

  function load() {
    try {
      var raw = localStorage.getItem(KEY);
      var list = raw ? JSON.parse(raw) : [];
      return Array.isArray(list) ? list : [];
    } catch (e) {
      return [];
    }
  }

  function save(list) {
    localStorage.setItem(KEY, JSON.stringify(list || []));
    updateBadge();
    try {
      global.dispatchEvent(
        new CustomEvent("report-deck-changed", { detail: { count: (list || []).length } })
      );
    } catch (e) {}
  }

  function loadMeta() {
    try {
      var raw = localStorage.getItem(META_KEY);
      var m = raw ? JSON.parse(raw) : {};
      return m && typeof m === "object" ? m : {};
    } catch (e) {
      return {};
    }
  }

  function saveMeta(meta) {
    localStorage.setItem(META_KEY, JSON.stringify(meta || {}));
  }

  function count() {
    return load().length;
  }

  function updateBadge() {
    var n = count();
    document.querySelectorAll("[data-report-badge]").forEach(function (el) {
      if (n > 0) {
        el.textContent = String(n);
        el.hidden = false;
      } else {
        el.textContent = "";
        el.hidden = true;
      }
    });
  }

  function compressImage(dataUrl, maxW, quality) {
    maxW = maxW || 1280;
    quality = quality == null ? 0.82 : quality;
    return new Promise(function (resolve) {
      if (!dataUrl) {
        resolve("");
        return;
      }
      var img = new Image();
      img.onload = function () {
        var w = img.naturalWidth || img.width;
        var h = img.naturalHeight || img.height;
        if (!w || !h) {
          resolve(dataUrl);
          return;
        }
        var scale = w > maxW ? maxW / w : 1;
        var cw = Math.round(w * scale);
        var ch = Math.round(h * scale);
        var c = document.createElement("canvas");
        c.width = cw;
        c.height = ch;
        var ctx = c.getContext("2d");
        ctx.fillStyle = "#ffffff";
        ctx.fillRect(0, 0, cw, ch);
        ctx.drawImage(img, 0, 0, cw, ch);
        try {
          resolve(c.toDataURL("image/jpeg", quality));
        } catch (e) {
          resolve(dataUrl);
        }
      };
      img.onerror = function () {
        resolve(dataUrl);
      };
      img.src = dataUrl;
    });
  }

  function draftNarrative(slide) {
    var title = slide.title || "this chart";
    var sub = slide.subtitle || "";
    var src = slide.source || "chart";
    var where =
      src === "commission"
        ? "the Summary commission chart"
        : src === "generate"
          ? "Leads deal analytics"
          : src === "finance"
            ? "Finance analysis"
            : "the selected chart view";
    var lines = [
      title + " is included from " + where + ".",
    ];
    if (sub) lines.push("Context: " + sub + ".");
    lines.push(
      "Review the figure below and note material movements, mix shifts, and any variance to plan that warrants follow-up."
    );
    return lines.join(" ");
  }

  function addSlide(opts) {
    opts = opts || {};
    return compressImage(opts.image || "", 1280, 0.82).then(function (image) {
      if (!image) throw new Error("No chart image to add");
      var list = load();
      if (list.length >= MAX_SLIDES) {
        throw new Error("Report is full (max " + MAX_SLIDES + " sections). Remove some first.");
      }
      var slide = {
        id: uid(),
        title: String(opts.title || "Chart").slice(0, 120),
        subtitle: String(opts.subtitle || "").slice(0, 200),
        source: String(opts.source || "chart"),
        image: image,
        notes: "",
        addedAt: new Date().toISOString(),
      };
      slide.notes = draftNarrative(slide);
      list.push(slide);
      try {
        save(list);
      } catch (e) {
        throw new Error("Storage full — remove sections or use fewer charts.");
      }
      return slide;
    });
  }

  function removeSlide(id) {
    save(
      load().filter(function (s) {
        return s.id !== id;
      })
    );
  }

  function clearAll() {
    save([]);
  }

  function moveSlide(id, dir) {
    var list = load();
    var i = list.findIndex(function (s) {
      return s.id === id;
    });
    if (i < 0) return;
    var j = i + dir;
    if (j < 0 || j >= list.length) return;
    var tmp = list[i];
    list[i] = list[j];
    list[j] = tmp;
    save(list);
  }

  function updateSlide(id, patch) {
    var list = load();
    list.forEach(function (s) {
      if (s.id !== id) return;
      if (patch.title != null) s.title = String(patch.title).slice(0, 120);
      if (patch.notes != null) s.notes = String(patch.notes).slice(0, 4000);
      if (patch.subtitle != null) s.subtitle = String(patch.subtitle).slice(0, 200);
    });
    save(list);
  }

  function flashButton(btn, okText) {
    if (!btn) return;
    var prev = btn.textContent;
    btn.textContent = okText || "Added ✓";
    btn.disabled = true;
    setTimeout(function () {
      btn.textContent = prev;
      btn.disabled = false;
    }, 1400);
  }

  global.ReportDeck = {
    load: load,
    save: save,
    loadMeta: loadMeta,
    saveMeta: saveMeta,
    count: count,
    addSlide: addSlide,
    removeSlide: removeSlide,
    clearAll: clearAll,
    moveSlide: moveSlide,
    updateSlide: updateSlide,
    draftNarrative: draftNarrative,
    updateBadge: updateBadge,
    flashButton: flashButton,
    compressImage: compressImage,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", updateBadge);
  } else {
    updateBadge();
  }
})(window);
