/* Shared presentation deck — stored in localStorage for slideshow reuse. */
(function (global) {
  var KEY = "gbinc-presentation-deck-v1";
  var MAX_SLIDES = 40;

  function uid() {
    return "s" + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
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
      global.dispatchEvent(new CustomEvent("presentation-deck-changed", { detail: { count: (list || []).length } }));
    } catch (e) {}
  }

  function count() {
    return load().length;
  }

  function updateBadge() {
    var n = count();
    document.querySelectorAll("[data-presentation-badge]").forEach(function (el) {
      if (n > 0) {
        el.textContent = String(n);
        el.hidden = false;
      } else {
        el.textContent = "";
        el.hidden = true;
      }
    });
  }

  /** Shrink a data-URL image for localStorage (jpeg, max width). */
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

  function addSlide(opts) {
    opts = opts || {};
    return compressImage(opts.image || "", 1280, 0.82).then(function (image) {
      if (!image) throw new Error("No chart image to add");
      var list = load();
      if (list.length >= MAX_SLIDES) {
        throw new Error("Presentation is full (max " + MAX_SLIDES + " slides). Remove some first.");
      }
      var slide = {
        id: uid(),
        title: String(opts.title || "Chart").slice(0, 120),
        subtitle: String(opts.subtitle || "").slice(0, 200),
        source: String(opts.source || "chart"),
        image: image,
        addedAt: new Date().toISOString(),
      };
      list.push(slide);
      try {
        save(list);
      } catch (e) {
        throw new Error("Storage full — remove slides or use fewer charts.");
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

  function renameSlide(id, title) {
    var list = load();
    list.forEach(function (s) {
      if (s.id === id) s.title = String(title || s.title).slice(0, 120);
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

  global.PresentationDeck = {
    load: load,
    save: save,
    count: count,
    addSlide: addSlide,
    removeSlide: removeSlide,
    clearAll: clearAll,
    moveSlide: moveSlide,
    renameSlide: renameSlide,
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
