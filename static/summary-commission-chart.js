/* Commission chart — filter by time period, break down monthly/company/etc, optional compare. */
(function () {
  var root = document.getElementById("ciChartRoot");
  if (!root || typeof Chart === "undefined") return;

  var rows = [];
  try {
    var dataEl = document.getElementById("ciChartData");
    rows = JSON.parse((dataEl && dataEl.textContent) || "[]");
  } catch (e) {
    rows = [];
  }

  var canvas = document.getElementById("ciChartCanvas");
  var emptyEl = document.getElementById("ciChartEmpty");
  var totalEl = document.getElementById("ciChartTotal");
  var chart = null;
  var optionCache = { months: [], quarters: [], years: [], fys: [] };

  var COLORS = [
    "rgba(15, 118, 110, 0.75)",
    "rgba(37, 99, 235, 0.7)",
    "rgba(180, 83, 9, 0.7)",
    "rgba(124, 58, 237, 0.65)",
    "rgba(190, 24, 93, 0.65)",
    "rgba(22, 163, 74, 0.7)",
    "rgba(8, 145, 178, 0.7)",
    "rgba(217, 119, 6, 0.7)",
    "rgba(79, 70, 229, 0.65)",
    "rgba(101, 163, 13, 0.7)",
    "rgba(225, 29, 72, 0.65)",
    "rgba(71, 85, 105, 0.65)",
  ];
  var COMPARE_COLORS = ["rgba(15, 118, 110, 0.8)", "rgba(37, 99, 235, 0.75)"];
  var OTHER_COLOR = "rgba(100, 116, 139, 0.55)";
  var MONTH_NAMES = [
    "", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
  ];

  function $(id) {
    return document.getElementById(id);
  }

  function colorForProduct(name) {
    if (name === "Other") return OTHER_COLOR;
    var s = String(name || "—");
    var h = 2166136261;
    for (var i = 0; i < s.length; i++) {
      h ^= s.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    return COLORS[(h >>> 0) % COLORS.length];
  }

  function parseDate(s) {
    if (!s || s.length < 7) return null;
    var y = parseInt(s.slice(0, 4), 10);
    var m = parseInt(s.slice(5, 7), 10);
    if (!y || !m) return null;
    return { y: y, m: m, iso: s.slice(0, 10) };
  }

  function fiscalYear(d) {
    return d.m >= 4 ? d.y + 1 : d.y;
  }

  function monthKey(d) {
    return d.y + "-" + String(d.m).padStart(2, "0");
  }

  function quarterKey(d) {
    return d.y + "-Q" + (Math.floor((d.m - 1) / 3) + 1);
  }

  function yearKey(d) {
    return String(d.y);
  }

  function fyKey(d) {
    return String(fiscalYear(d));
  }

  function fyLabel(fy) {
    return "FY" + String(fy % 100).padStart(2, "0") + " (Apr " + (fy - 1) + "–Mar " + fy + ")";
  }

  function prettyBucket(key, breakdown) {
    if (breakdown === "month" && /^\d{4}-\d{2}$/.test(key)) {
      var y = key.slice(0, 4);
      var m = parseInt(key.slice(5, 7), 10);
      return MONTH_NAMES[m] + " " + y;
    }
    if (breakdown === "fy" && /^\d{4}$/.test(key)) return fyLabel(parseInt(key, 10));
    if (breakdown === "fy" && /^FY\d{2}$/.test(key)) return key;
    return key;
  }

  function uniqueSorted(arr) {
    return Array.from(new Set(arr)).sort();
  }

  function money(n) {
    return (
      "$" +
      Number(n || 0).toLocaleString(undefined, {
        minimumFractionDigits: 0,
        maximumFractionDigits: 2,
      })
    );
  }

  function selectedProducts() {
    var list = $("ciChartProductList");
    var allBox = $("ciChartProductAll");
    if (!list || !allBox || allBox.checked) return null;
    var picked = [];
    list.querySelectorAll("input[type=checkbox]:checked").forEach(function (cb) {
      picked.push(cb.value);
    });
    return picked;
  }

  function updateProductButton() {
    var btn = $("ciChartProductBtn");
    if (!btn) return;
    var picked = selectedProducts();
    if (!picked) btn.textContent = "All products";
    else if (!picked.length) btn.textContent = "No products";
    else if (picked.length === 1) btn.textContent = picked[0];
    else btn.textContent = picked.length + " products";
  }

  function baseFiltersOk(r) {
    var variant = $("ciChartVariant").value;
    var products = selectedProducts();
    if (variant !== "all" && (r.variant || "gbinc") !== variant) return false;
    if (products && products.indexOf(r.product || "—") < 0) return false;
    return true;
  }

  function periodSpec(prefix) {
    return {
      kind: ($("ci" + prefix + "Kind") || {}).value || "all",
      month: ($("ci" + prefix + "Month") || {}).value || "",
      quarter: ($("ci" + prefix + "Quarter") || {}).value || "",
      year: ($("ci" + prefix + "Year") || {}).value || "",
      fy: ($("ci" + prefix + "Fy") || {}).value || "",
      from: (($("ci" + prefix + "From") || {}).value || "").slice(0, 10),
      to: (($("ci" + prefix + "To") || {}).value || "").slice(0, 10),
    };
  }

  function matchesPeriod(d, spec) {
    if (!spec || spec.kind === "all") return true;
    if (!d) return false;
    if (spec.kind === "custom") {
      if (spec.from && d.iso < spec.from) return false;
      if (spec.to && d.iso > spec.to) return false;
      return true;
    }
    if (spec.kind === "month") return monthKey(d) === spec.month;
    if (spec.kind === "quarter") return quarterKey(d) === spec.quarter;
    if (spec.kind === "year") return yearKey(d) === spec.year;
    if (spec.kind === "fy") return fyKey(d) === spec.fy;
    return true;
  }

  function periodLabel(spec) {
    if (!spec || spec.kind === "all") return "All time";
    if (spec.kind === "month") return prettyBucket(spec.month, "month");
    if (spec.kind === "quarter") return spec.quarter || "Quarter";
    if (spec.kind === "year") return spec.year || "Year";
    if (spec.kind === "fy") {
      var n = parseInt(spec.fy, 10);
      return n ? fyLabel(n) : "FY";
    }
    if (spec.kind === "custom") return (spec.from || "…") + " → " + (spec.to || "…");
    return "Period";
  }

  function filterByPeriod(spec) {
    return rows.filter(function (r) {
      if (!baseFiltersOk(r)) return false;
      return matchesPeriod(parseDate(r.date), spec);
    });
  }

  function metricValue(r) {
    return $("ciChartMetric").value === "quantity"
      ? Number(r.quantity) || 0
      : Number(r.commission) || 0;
  }

  function isCompare() {
    var el = $("ciChartCompare");
    return !!(el && el.checked);
  }

  function breakdown() {
    return ($("ciChartBreakdown") || {}).value || "month";
  }

  function isTimeBreakdown(b) {
    return b === "month" || b === "quarter" || b === "year" || b === "fy";
  }

  function bucketOf(r, b) {
    var d = parseDate(r.date);
    if (!d) return "Unknown";
    if (b === "quarter") return quarterKey(d);
    if (b === "year") return yearKey(d);
    if (b === "fy") return fyKey(d);
    if (b === "product") return r.product || "—";
    if (b === "company") return r.company || "—";
    return monthKey(d);
  }

  function categoryOf(r) {
    var b = breakdown();
    if (b === "product") return r.product || "—";
    return r.company || "—";
  }

  function topKeys(totals, n) {
    var keys = Object.keys(totals).sort(function (a, b) {
      return totals[b] - totals[a];
    });
    if (n > 0 && keys.length > n) {
      var keep = keys.slice(0, n);
      var other = 0;
      keys.slice(n).forEach(function (k) {
        other += totals[k];
      });
      if (other > 0) {
        keep.push("Other");
        totals["Other"] = (totals["Other"] || 0) + other;
      }
      return keep;
    }
    return keys;
  }

  function sortTimeKeys(keys, b) {
    var sorted = keys.slice().sort();
    if (b === "fy") {
      sorted.sort(function (a, c) {
        return parseInt(a, 10) - parseInt(c, 10);
      });
    }
    return sorted;
  }

  function addMonths(y, m, n) {
    var t = y * 12 + (m - 1) + n;
    return { y: Math.floor(t / 12), m: (t % 12) + 1 };
  }

  /** Inclusive calendar-month span for an explicit period filter, or null for All time. */
  function periodMonthRange(spec) {
    if (!spec || spec.kind === "all") return null;
    if (spec.kind === "month" && spec.month && /^\d{4}-\d{2}$/.test(spec.month)) {
      var my = parseInt(spec.month.slice(0, 4), 10);
      var mm = parseInt(spec.month.slice(5, 7), 10);
      return { fromY: my, fromM: mm, toY: my, toM: mm };
    }
    if (spec.kind === "quarter" && spec.quarter) {
      var qm = /^(\d{4})-Q([1-4])$/.exec(spec.quarter);
      if (qm) {
        var qy = parseInt(qm[1], 10);
        var qn = parseInt(qm[2], 10);
        var sm = (qn - 1) * 3 + 1;
        return { fromY: qy, fromM: sm, toY: qy, toM: sm + 2 };
      }
    }
    if (spec.kind === "year" && spec.year) {
      var yy = parseInt(spec.year, 10);
      if (yy) return { fromY: yy, fromM: 1, toY: yy, toM: 12 };
    }
    if (spec.kind === "fy" && spec.fy) {
      var fy = parseInt(spec.fy, 10);
      if (fy) return { fromY: fy - 1, fromM: 4, toY: fy, toM: 3 };
    }
    if (spec.kind === "custom") {
      var fd = parseDate(spec.from);
      var td = parseDate(spec.to);
      if (fd && td) {
        if (fd.y * 12 + fd.m > td.y * 12 + td.m) {
          return { fromY: td.y, fromM: td.m, toY: fd.y, toM: fd.m };
        }
        return { fromY: fd.y, fromM: fd.m, toY: td.y, toM: td.m };
      }
      if (fd) return { fromY: fd.y, fromM: fd.m, toY: fd.y, toM: fd.m };
      if (td) return { fromY: td.y, fromM: td.m, toY: td.y, toM: td.m };
    }
    return null;
  }

  function monthRangeFromRows(filtered) {
    var minT = null;
    var maxT = null;
    filtered.forEach(function (r) {
      var d = parseDate(r.date);
      if (!d) return;
      var t = d.y * 12 + d.m;
      if (minT === null || t < minT) minT = t;
      if (maxT === null || t > maxT) maxT = t;
    });
    if (minT === null) return null;
    return {
      fromY: Math.floor((minT - 1) / 12),
      fromM: ((minT - 1) % 12) + 1,
      toY: Math.floor((maxT - 1) / 12),
      toM: ((maxT - 1) % 12) + 1,
    };
  }

  function enumerateMonthKeys(range) {
    var keys = [];
    if (!range) return keys;
    var cur = { y: range.fromY, m: range.fromM };
    var end = range.toY * 12 + range.toM;
    while (cur.y * 12 + cur.m <= end) {
      keys.push(monthKey(cur));
      cur = addMonths(cur.y, cur.m, 1);
    }
    return keys;
  }

  function enumerateQuarterKeys(range) {
    var keys = [];
    if (!range) return keys;
    var y = range.fromY;
    var q = Math.floor((range.fromM - 1) / 3) + 1;
    var endY = range.toY;
    var endQ = Math.floor((range.toM - 1) / 3) + 1;
    while (y < endY || (y === endY && q <= endQ)) {
      keys.push(y + "-Q" + q);
      q += 1;
      if (q > 4) {
        q = 1;
        y += 1;
      }
    }
    return keys;
  }

  function enumerateYearKeys(range) {
    var keys = [];
    if (!range) return keys;
    for (var y = range.fromY; y <= range.toY; y++) keys.push(String(y));
    return keys;
  }

  function enumerateFyKeys(range) {
    var keys = [];
    if (!range) return keys;
    var fromFy = range.fromM >= 4 ? range.fromY + 1 : range.fromY;
    var toFy = range.toM >= 4 ? range.toY + 1 : range.toY;
    for (var fy = fromFy; fy <= toFy; fy++) keys.push(String(fy));
    return keys;
  }

  /**
   * Continuous time buckets for the chart axis.
   * Explicit period (FY/year/…) → full span with zeros for empty slots.
   * All time → every bucket from first to last data month (no gaps in between).
   */
  function continuousTimeKeys(b, spec, filtered) {
    var range = periodMonthRange(spec) || monthRangeFromRows(filtered);
    if (!range) return [];
    if (b === "month") return enumerateMonthKeys(range);
    if (b === "quarter") return enumerateQuarterKeys(range);
    if (b === "year") return enumerateYearKeys(range);
    if (b === "fy") return enumerateFyKeys(range);
    return [];
  }

  function zeroProductDatasets(keys, stackId) {
    var picked = selectedProducts();
    var names =
      picked && picked.length
        ? picked
        : uniqueSorted(
            rows.map(function (r) {
              return r.product || "—";
            })
          ).slice(0, 1);
    if (!names.length) names = ["—"];
    return names.map(function (p) {
      return {
        label: p,
        data: keys.map(function () {
          return 0;
        }),
        backgroundColor: colorForProduct(p),
        borderWidth: 0,
        borderSkipped: false,
        stack: stackId || "products",
      };
    });
  }

  function totalsByKey(filtered, keyFn) {
    var totals = {};
    filtered.forEach(function (r) {
      var k = keyFn(r);
      totals[k] = (totals[k] || 0) + metricValue(r);
    });
    return totals;
  }

  /** Stacked series: one dataset per product (Top N + Other), stable colors. */
  function buildProductStackDatasets(filtered, bucketKeys, bucketFn, stackId) {
    var productTotals = {};
    var cell = {};
    filtered.forEach(function (r) {
      var p = r.product || "—";
      var b = bucketFn(r);
      var v = metricValue(r);
      productTotals[p] = (productTotals[p] || 0) + v;
      if (!cell[p]) cell[p] = {};
      cell[p][b] = (cell[p][b] || 0) + v;
    });
    var ranked = Object.keys(productTotals).sort(function (a, c) {
      return productTotals[c] - productTotals[a];
    });
    var topN = parseInt(($("ciChartTop") || {}).value, 10) || 0;
    var keep = ranked;
    if (topN > 0 && ranked.length > topN) {
      keep = ranked.slice(0, topN);
      var otherCell = {};
      ranked.slice(topN).forEach(function (p) {
        Object.keys(cell[p] || {}).forEach(function (b) {
          otherCell[b] = (otherCell[b] || 0) + cell[p][b];
        });
      });
      cell.Other = otherCell;
      keep = keep.concat(["Other"]);
    }
    return keep.map(function (p) {
      return {
        label: p,
        data: bucketKeys.map(function (k) {
          return Math.round(((cell[p] && cell[p][k]) || 0) * 100) / 100;
        }),
        backgroundColor: colorForProduct(p),
        borderWidth: 0,
        borderSkipped: false,
        stack: stackId || "products",
      };
    });
  }

  function buildCategoryChart(filtered, label) {
    var b = breakdown();
    if (b === "product") {
      var totals = totalsByKey(filtered, categoryOf);
      var topN = parseInt($("ciChartTop").value, 10) || 0;
      var labels = topKeys(totals, topN);
      return {
        labels: labels,
        stacked: false,
        datasets: [
          {
            label: label || "Commission",
            data: labels.map(function (k) {
              return Math.round((totals[k] || 0) * 100) / 100;
            }),
            backgroundColor: labels.map(function (k) {
              return colorForProduct(k);
            }),
            borderWidth: 0,
            borderRadius: 4,
          },
        ],
      };
    }

    // By company: each company bar stacked by product
    var companyTotals = totalsByKey(filtered, function (r) {
      return r.company || "—";
    });
    var topNCo = parseInt($("ciChartTop").value, 10) || 0;
    var companies = topKeys(companyTotals, topNCo);
    var keepCo = {};
    companies.forEach(function (c) {
      if (c !== "Other") keepCo[c] = true;
    });
    var hasOther = companies.indexOf("Other") >= 0;
    var mapped = filtered.map(function (r) {
      var c = r.company || "—";
      return Object.assign({}, r, {
        _bucket: keepCo[c] ? c : hasOther ? "Other" : c,
      });
    });
    return {
      labels: companies,
      stacked: true,
      datasets: buildProductStackDatasets(
        mapped,
        companies,
        function (r) {
          return r._bucket;
        },
        "products"
      ),
    };
  }

  function buildCompareCategory(rowsA, rowsB) {
    var totA = totalsByKey(rowsA, categoryOf);
    var totB = totalsByKey(rowsB, categoryOf);
    var combined = {};
    Object.keys(totA).forEach(function (k) {
      combined[k] = (combined[k] || 0) + totA[k];
    });
    Object.keys(totB).forEach(function (k) {
      combined[k] = (combined[k] || 0) + totB[k];
    });
    var topN = parseInt($("ciChartTop").value, 10) || 0;
    var labels = topKeys(combined, topN);
    return {
      labels: labels,
      stacked: false,
      datasets: [
        {
          label: periodLabel(periodSpec("PeriodA")),
          data: labels.map(function (k) {
            return Math.round((totA[k] || 0) * 100) / 100;
          }),
          backgroundColor: COMPARE_COLORS[0],
          borderWidth: 0,
          borderRadius: 3,
        },
        {
          label: periodLabel(periodSpec("PeriodB")),
          data: labels.map(function (k) {
            return Math.round((totB[k] || 0) * 100) / 100;
          }),
          backgroundColor: COMPARE_COLORS[1],
          borderWidth: 0,
          borderRadius: 3,
        },
      ],
    };
  }

  function buildTimeChart(filtered, label) {
    var b = breakdown();
    var keys = continuousTimeKeys(b, periodSpec("PeriodA"), filtered);
    if (!keys.length) {
      var totals = totalsByKey(filtered, function (r) {
        return bucketOf(r, b);
      });
      keys = sortTimeKeys(Object.keys(totals), b);
    }
    var datasets = buildProductStackDatasets(
      filtered,
      keys,
      function (r) {
        return bucketOf(r, b);
      },
      "products"
    );
    if (!datasets.length && keys.length) {
      datasets = zeroProductDatasets(keys, "products");
    }
    return {
      labels: keys.map(function (k) {
        return prettyBucket(k, b);
      }),
      stacked: true,
      datasets: datasets,
    };
  }

  function buildCompareTime(rowsA, rowsB) {
    var b = breakdown();
    var keysA = continuousTimeKeys(b, periodSpec("PeriodA"), rowsA);
    var keysB = continuousTimeKeys(b, periodSpec("PeriodB"), rowsB);
    var keySet = {};
    keysA.forEach(function (k) {
      keySet[k] = true;
    });
    keysB.forEach(function (k) {
      keySet[k] = true;
    });
    // Also include any data months outside the filled range (safety)
    rowsA.concat(rowsB).forEach(function (r) {
      keySet[bucketOf(r, b)] = true;
    });
    var keys = sortTimeKeys(Object.keys(keySet), b);
    var totA = totalsByKey(rowsA, function (r) {
      return bucketOf(r, b);
    });
    var totB = totalsByKey(rowsB, function (r) {
      return bucketOf(r, b);
    });
    return {
      labels: keys.map(function (k) {
        return prettyBucket(k, b);
      }),
      stacked: false,
      datasets: [
        {
          label: periodLabel(periodSpec("PeriodA")),
          data: keys.map(function (k) {
            return Math.round((totA[k] || 0) * 100) / 100;
          }),
          backgroundColor: COMPARE_COLORS[0],
          borderWidth: 0,
          borderRadius: 3,
        },
        {
          label: periodLabel(periodSpec("PeriodB")),
          data: keys.map(function (k) {
            return Math.round((totB[k] || 0) * 100) / 100;
          }),
          backgroundColor: COMPARE_COLORS[1],
          borderWidth: 0,
          borderRadius: 3,
        },
      ],
    };
  }

  function fillSelect(sel, options, labels) {
    if (!sel) return;
    var cur = sel.value;
    sel.innerHTML = "";
    options.forEach(function (v, i) {
      var opt = document.createElement("option");
      opt.value = v;
      opt.textContent = labels ? labels[i] : v;
      sel.appendChild(opt);
    });
    if (options.indexOf(cur) >= 0) sel.value = cur;
    else if (options.length) sel.value = options[options.length - 1];
  }

  function syncPeriodKindPanels(prefix) {
    var kind = ($("ci" + prefix + "Kind") || {}).value || "all";
    ["Month", "Quarter", "Year", "Fy", "Custom"].forEach(function (part) {
      var el = $("ci" + prefix + part + "Wrap");
      if (!el) return;
      var want =
        (part === "Month" && kind === "month") ||
        (part === "Quarter" && kind === "quarter") ||
        (part === "Year" && kind === "year") ||
        (part === "Fy" && kind === "fy") ||
        (part === "Custom" && kind === "custom");
      el.hidden = !want;
    });
  }

  function syncPanels() {
    var compare = isCompare();
    var b = breakdown();
    var bBlock = $("ciPeriodBBlock");
    if (bBlock) bBlock.hidden = !compare;
    var aLabel = $("ciPeriodALabel");
    if (aLabel) aLabel.textContent = compare ? "Period A" : "Time period";
    var topWrap = $("ciChartTopWrap");
    if (topWrap) {
      // Top N limits products in stacked bars (or bars when by product/company)
      topWrap.hidden = compare;
      var topLabel = topWrap.querySelector("span");
      if (topLabel) {
        topLabel.textContent =
          isTimeBreakdown(b) || b === "company" ? "Top products" : "Top N";
      }
    }
    syncPeriodKindPanels("PeriodA");
    syncPeriodKindPanels("PeriodB");
  }

  function populateProductMultiSelect() {
    var list = $("ciChartProductList");
    var allBox = $("ciChartProductAll");
    if (!list) return;
    var products = uniqueSorted(
      rows.map(function (r) {
        return r.product || "—";
      })
    );
    list.innerHTML = "";
    products.forEach(function (name) {
      var label = document.createElement("label");
      var cb = document.createElement("input");
      cb.type = "checkbox";
      cb.value = name;
      var span = document.createElement("span");
      span.textContent = name;
      label.appendChild(cb);
      label.appendChild(span);
      list.appendChild(label);
      cb.addEventListener("change", function () {
        if (allBox) allBox.checked = false;
        updateProductButton();
        render();
      });
    });
    if (allBox) {
      allBox.checked = true;
      allBox.addEventListener("change", function () {
        if (allBox.checked) {
          list.querySelectorAll("input[type=checkbox]").forEach(function (cb) {
            cb.checked = false;
          });
        }
        updateProductButton();
        render();
      });
    }
    updateProductButton();
  }

  function wireProductDropdown() {
    var btn = $("ciChartProductBtn");
    var panel = $("ciChartProductPanel");
    if (!btn || !panel) return;
    btn.addEventListener("click", function (e) {
      e.stopPropagation();
      var open = panel.hidden;
      panel.hidden = !open;
      btn.setAttribute("aria-expanded", open ? "true" : "false");
    });
    panel.addEventListener("click", function (e) {
      e.stopPropagation();
    });
    document.addEventListener("click", function () {
      panel.hidden = true;
      btn.setAttribute("aria-expanded", "false");
    });
  }

  function populateSelectors() {
    var months = [];
    var quarters = [];
    var years = [];
    var fys = [];
    rows.forEach(function (r) {
      var d = parseDate(r.date);
      if (!d) return;
      months.push(monthKey(d));
      quarters.push(quarterKey(d));
      years.push(yearKey(d));
      fys.push(fyKey(d));
    });
    optionCache.months = uniqueSorted(months);
    optionCache.quarters = uniqueSorted(quarters);
    optionCache.years = uniqueSorted(years);
    optionCache.fys = uniqueSorted(fys);
    var monthLabels = optionCache.months.map(function (k) {
      return prettyBucket(k, "month");
    });
    var fyLabels = optionCache.fys.map(function (y) {
      return fyLabel(parseInt(y, 10));
    });

    ["PeriodA", "PeriodB"].forEach(function (prefix) {
      fillSelect($("ci" + prefix + "Month"), optionCache.months, monthLabels);
      fillSelect($("ci" + prefix + "Quarter"), optionCache.quarters);
      fillSelect($("ci" + prefix + "Year"), optionCache.years);
      fillSelect($("ci" + prefix + "Fy"), optionCache.fys, fyLabels);
    });

    var fyA = $("ciPeriodAFy");
    var fyB = $("ciPeriodBFy");
    if (optionCache.fys.length >= 2 && fyA && fyB) {
      fyA.value = optionCache.fys[optionCache.fys.length - 1];
      fyB.value = optionCache.fys[optionCache.fys.length - 2];
    } else if (optionCache.fys.length && fyA) {
      fyA.value = optionCache.fys[optionCache.fys.length - 1];
    }

    populateProductMultiSelect();
    wireProductDropdown();
  }

  function syncTable(unionRows, sumA, sumB, compare) {
    var table = $("ciSummaryTable");
    if (!table) return;
    var visible = 0;
    var sum = 0;
    table.querySelectorAll("tr.ci-summary-row").forEach(function (tr) {
      var meta = {
        date: tr.getAttribute("data-date") || "",
        product: tr.getAttribute("data-product") || "—",
        variant: tr.getAttribute("data-variant") || "gbinc",
        commission: Number(tr.getAttribute("data-commission") || 0),
      };
      var ok = unionRows.some(function (r) {
        return (
          (r.date || "") === meta.date &&
          (r.product || "—") === meta.product &&
          (r.variant || "gbinc") === meta.variant &&
          Math.abs((Number(r.commission) || 0) - meta.commission) < 0.001
        );
      });
      tr.hidden = !ok;
      if (ok) {
        visible += 1;
        sum += meta.commission;
      }
    });
    var countEl = $("ciTableCount");
    var totalCell = $("ciTableTotal");
    if (countEl) countEl.textContent = String(visible);
    if (totalCell) totalCell.textContent = money(sum);

    if (totalEl) {
      if (compare) {
        totalEl.textContent =
          periodLabel(periodSpec("PeriodA")) +
          " " +
          money(sumA) +
          "  ·  " +
          periodLabel(periodSpec("PeriodB")) +
          " " +
          money(sumB);
      } else if ($("ciChartMetric").value === "quantity") {
        totalEl.textContent =
          sum.toLocaleString(undefined, { maximumFractionDigits: 2 }) +
          " qty · " +
          visible +
          " lines";
      } else {
        totalEl.textContent = money(sum) + " · " + visible + " lines";
      }
    }
  }

  function render() {
    syncPanels();
    var compare = isCompare();
    var b = breakdown();
    var rowsA = filterByPeriod(periodSpec("PeriodA"));
    var rowsB = compare ? filterByPeriod(periodSpec("PeriodB")) : [];
    var union = compare ? rowsA.concat(rowsB) : rowsA;

    var sumA = rowsA.reduce(function (a, r) {
      return a + metricValue(r);
    }, 0);
    var sumB = rowsB.reduce(function (a, r) {
      return a + metricValue(r);
    }, 0);
    syncTable(union, sumA, sumB, compare);

    if (!union.length) {
      var canShowZeros =
        isTimeBreakdown(b) &&
        (periodMonthRange(periodSpec("PeriodA")) ||
          (compare && periodMonthRange(periodSpec("PeriodB"))) ||
          continuousTimeKeys(b, periodSpec("PeriodA"), rows).length > 0);
      if (!canShowZeros) {
        if (emptyEl) emptyEl.hidden = false;
        if (canvas) canvas.style.display = "none";
        if (chart) {
          chart.destroy();
          chart = null;
        }
        setDownloadEnabled(false);
        return;
      }
    }
    if (emptyEl) emptyEl.hidden = true;
    if (canvas) canvas.style.display = "block";

    var data;
    if (isTimeBreakdown(b)) {
      data = compare ? buildCompareTime(rowsA, rowsB) : buildTimeChart(rowsA);
    } else {
      data = compare
        ? buildCompareCategory(rowsA, rowsB)
        : buildCategoryChart(rowsA, periodLabel(periodSpec("PeriodA")));
    }
    if (!data.labels || !data.labels.length) {
      if (emptyEl) emptyEl.hidden = false;
      if (canvas) canvas.style.display = "none";
      if (chart) {
        chart.destroy();
        chart = null;
      }
      setDownloadEnabled(false);
      return;
    }

    var metricLabel =
      $("ciChartMetric").value === "quantity" ? "Quantity" : "Commission (USD)";
    var stacked = !!data.stacked;

    if (chart) chart.destroy();
    chart = new Chart(canvas, {
      type: "bar",
      data: data,
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            display: stacked || compare || breakdown() === "product",
            position: "bottom",
            labels: { boxWidth: 12, font: { size: 11 }, padding: 10 },
          },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                var v = ctx.parsed.y;
                if (v == null || v === 0) return null;
                var prefix = ctx.dataset.label ? ctx.dataset.label + ": " : "";
                if ($("ciChartMetric").value === "quantity") return prefix + v;
                return prefix + money(v);
              },
              footer: function (items) {
                if (!stacked || !items.length) return "";
                var sum = items.reduce(function (a, it) {
                  return a + (it.parsed.y || 0);
                }, 0);
                if ($("ciChartMetric").value === "quantity")
                  return "Total: " + sum;
                return "Total: " + money(sum);
              },
            },
          },
        },
        scales: {
          x: {
            stacked: stacked,
            ticks: { maxRotation: 45, minRotation: 0, font: { size: 11 } },
            grid: { display: false },
          },
          y: {
            stacked: stacked,
            beginAtZero: true,
            title: { display: true, text: metricLabel, font: { size: 11 } },
            ticks: {
              callback: function (v) {
                if ($("ciChartMetric").value === "quantity") return v;
                if (Math.abs(v) >= 1000)
                  return "$" + (v / 1000).toFixed(v >= 10000 ? 0 : 1) + "k";
                return "$" + v;
              },
            },
          },
        },
      },
    });
    setDownloadEnabled(true);
  }

  function setDownloadEnabled(on) {
    ["ciChartDownloadPng", "ciChartDownloadCsv"].forEach(function (id) {
      var el = $(id);
      if (el) el.disabled = !on;
    });
  }

  function chartTitle() {
    var b = breakdown();
    var names = {
      month: "Monthly",
      quarter: "Quarterly",
      year: "Yearly",
      fy: "By fiscal year",
      company: "By company",
      product: "By product",
    };
    var metric = $("ciChartMetric").value === "quantity" ? "Quantity" : "Commission";
    var title = metric + " · " + (names[b] || b);
    var a = periodLabel(periodSpec("PeriodA"));
    if (isCompare()) title += " · " + a + " vs " + periodLabel(periodSpec("PeriodB"));
    else title += " · " + a;
    return title;
  }

  function slugFilename(ext) {
    var raw = "commission-chart-" + chartTitle();
    var slug = raw.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
    return (slug.slice(0, 80) || "commission-chart") + "." + ext;
  }

  function csvCell(v) {
    var s = v == null ? "" : String(v);
    if (/[",\n]/.test(s)) return '"' + s.replace(/"/g, '""') + '"';
    return s;
  }

  function downloadBlob(filename, mime, text) {
    var blob = new Blob([text], { type: mime });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
    setTimeout(function () {
      URL.revokeObjectURL(a.href);
    }, 1000);
  }

  function downloadCsv() {
    if (!chart) return;
    var labels = chart.data.labels || [];
    var sets = chart.data.datasets || [];
    var header = ["Label"].concat(
      sets.map(function (ds) {
        return ds.label || "Value";
      })
    );
    var lines = [header.map(csvCell).join(",")];
    labels.forEach(function (lab, i) {
      var row = [lab];
      sets.forEach(function (ds) {
        var v = (ds.data || [])[i];
        row.push(v == null ? "" : v);
      });
      lines.push(row.map(csvCell).join(","));
    });
    downloadBlob(slugFilename("csv"), "text/csv;charset=utf-8", lines.join("\n"));
  }

  function downloadPng() {
    if (!chart || !canvas) return;
    var srcW = canvas.width;
    var srcH = canvas.height;
    if (!srcW || !srcH) return;
    var TARGET_W = 1400;
    var scale = TARGET_W / srcW;
    var chartH = Math.round(srcH * scale);
    var PAD = 28;
    var TOPBAR = 72;
    var FOOTER = 32;
    var off = document.createElement("canvas");
    off.width = TARGET_W;
    off.height = TOPBAR + chartH + FOOTER;
    var ctx = off.getContext("2d");
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, off.width, off.height);
    ctx.fillStyle = "#1C5631";
    ctx.fillRect(0, 0, off.width, TOPBAR - 8);
    ctx.fillStyle = "#ffffff";
    ctx.font = "bold 18px system-ui, sans-serif";
    ctx.fillText("GBInc  —  Commission", PAD, 28);
    ctx.font = "14px system-ui, sans-serif";
    var title = chartTitle();
    ctx.fillText(title, PAD, 52);
    ctx.drawImage(canvas, 0, 0, srcW, srcH, 0, TOPBAR, TARGET_W, chartH);
    ctx.fillStyle = "#94a3b8";
    ctx.font = "11px system-ui, sans-serif";
    ctx.fillText(
      "Generated " + new Date().toLocaleDateString(),
      PAD,
      TOPBAR + chartH + 20
    );
    var a = document.createElement("a");
    a.download = slugFilename("png");
    a.href = off.toDataURL("image/png");
    a.click();
  }

  populateSelectors();

  var kindA = $("ciPeriodAKind");
  if (kindA && optionCache.fys.length) kindA.value = "fy";
  var kindB = $("ciPeriodBKind");
  if (kindB && optionCache.fys.length) kindB.value = "fy";

  [
    "ciChartBreakdown",
    "ciChartMetric",
    "ciChartTop",
    "ciChartVariant",
    "ciChartCompare",
    "ciPeriodAKind",
    "ciPeriodAMonth",
    "ciPeriodAQuarter",
    "ciPeriodAYear",
    "ciPeriodAFy",
    "ciPeriodAFrom",
    "ciPeriodATo",
    "ciPeriodBKind",
    "ciPeriodBMonth",
    "ciPeriodBQuarter",
    "ciPeriodBYear",
    "ciPeriodBFy",
    "ciPeriodBFrom",
    "ciPeriodBTo",
  ].forEach(function (id) {
    var el = $(id);
    if (el) el.addEventListener("change", render);
  });

  var pngBtn = $("ciChartDownloadPng");
  if (pngBtn) pngBtn.addEventListener("click", downloadPng);
  var csvBtn = $("ciChartDownloadCsv");
  if (csvBtn) csvBtn.addEventListener("click", downloadCsv);

  render();
})();
