/* Shared Chart.js chrome: title + legend for Finance charts. */
(function (global) {
  function moneyTick(v) {
    return "$" + Number(v).toLocaleString(undefined, {
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    });
  }

  function chartPlugins(title, extras) {
    extras = extras || {};
    return Object.assign(
      {
        title: {
          display: !!title,
          text: title || "",
          color: "#1C5631",
          font: { size: 15, weight: "600", family: "system-ui, sans-serif" },
          padding: { top: 4, bottom: 12 },
        },
        legend: {
          display: true,
          position: extras.legendPosition || "bottom",
          labels: { boxWidth: 12, font: { size: 11 }, padding: 10 },
        },
      },
      extras.plugins || {}
    );
  }

  function moneyScaleY(beginAtZero) {
    return {
      beginAtZero: beginAtZero !== false,
      ticks: { callback: moneyTick },
    };
  }

  /** Capture a Chart.js canvas as PNG data URL with branded header. */
  function chartToDataUrl(canvasId, title) {
    var canvas = document.getElementById(canvasId);
    if (!canvas) return null;
    var TARGET_W = 1400;
    var scale = TARGET_W / canvas.width;
    var chartH = Math.round(canvas.height * scale);
    var PAD = 28;
    var TOPBAR = 68;
    var FOOTER = 28;
    var off = document.createElement("canvas");
    off.width = TARGET_W;
    off.height = TOPBAR + chartH + FOOTER + PAD;
    var ctx = off.getContext("2d");
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, off.width, off.height);
    ctx.fillStyle = "#1C5631";
    ctx.fillRect(0, 0, off.width, TOPBAR - 8);
    ctx.fillStyle = "#ffffff";
    ctx.font = "bold 18px system-ui, sans-serif";
    ctx.fillText("GBInc  —  Finance", PAD, 26);
    ctx.font = "15px system-ui, sans-serif";
    ctx.fillText(title || "", PAD, 50);
    ctx.drawImage(canvas, 0, 0, canvas.width, canvas.height, 0, TOPBAR, TARGET_W, chartH);
    ctx.fillStyle = "#aaaaaa";
    ctx.font = "11px system-ui, sans-serif";
    ctx.fillText(
      "Generated " + new Date().toLocaleDateString(),
      PAD,
      TOPBAR + chartH + FOOTER
    );
    return off.toDataURL("image/png");
  }

  function addChartToPresentation(canvasId, title, btn) {
    if (!global.PresentationDeck) {
      alert("Presentation deck not loaded.");
      return;
    }
    var dataUrl = chartToDataUrl(canvasId, title);
    if (!dataUrl) {
      alert("Chart not ready.");
      return;
    }
    global.PresentationDeck.addSlide({
      title: title || "Finance chart",
      subtitle: "Finance",
      source: "finance",
      image: dataUrl,
    })
      .then(function () {
        global.PresentationDeck.flashButton(btn, "Added ✓");
      })
      .catch(function (err) {
        alert((err && err.message) || "Could not add slide");
      });
  }

  function addChartToReport(canvasId, title, btn) {
    if (!global.ReportDeck) {
      alert("Report deck not loaded.");
      return;
    }
    var dataUrl = chartToDataUrl(canvasId, title);
    if (!dataUrl) {
      alert("Chart not ready.");
      return;
    }
    global.ReportDeck.addSlide({
      title: title || "Finance chart",
      subtitle: "Finance",
      source: "finance",
      image: dataUrl,
    })
      .then(function () {
        global.ReportDeck.flashButton(btn, "Added ✓");
      })
      .catch(function (err) {
        alert((err && err.message) || "Could not add to report");
      });
  }

  function downloadChart(canvasId, filename, title) {
    var dataUrl = chartToDataUrl(canvasId, title);
    if (!dataUrl) {
      alert("Chart not ready.");
      return;
    }
    var a = document.createElement("a");
    a.download = filename || "GBInc-chart.png";
    a.href = dataUrl;
    a.click();
  }

  global.FinanceCharts = {
    chartPlugins: chartPlugins,
    moneyScaleY: moneyScaleY,
    moneyTick: moneyTick,
    chartToDataUrl: chartToDataUrl,
    addChartToPresentation: addChartToPresentation,
    addChartToReport: addChartToReport,
    downloadChart: downloadChart,
  };
})(window);
