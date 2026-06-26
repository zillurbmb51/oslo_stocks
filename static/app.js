const API_BASE = window.APP_API_BASE || window.location.origin;
const tickerSearch = document.getElementById("ticker-search");
const tickerSelect = document.getElementById("ticker-select");
const chartDiv = document.getElementById("chart");
const commentaryDiv = document.getElementById("commentary");
let resizeTimer = null;
const HISTORY_WIDTH_RATIO = 0.5;
const FORECAST_LABELS = {
  1: "FinGPT1",
  2: "FinGPT2",
  3: "FinGPT3",
  4: "StatsForecast",
  5: "AutoETS",
};

let tickerMetrics = [];

function getColor(idx) {
  const palette = [
    "#38bdf8", "#f97316", "#22c55e", "#eab308", "#a855f7",
    "#ec4899", "#14b8a6", "#4ade80", "#facc15", "#ef4444",
  ];
  return palette[idx % palette.length];
}

async function fetchJSON(url) {
  const resp = await fetch(url);
  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status} ${resp.statusText} for ${url}`);
  }
  return resp.json();
}

function formatRatio(value) {
  return Number.isFinite(value) ? value.toFixed(3) : "0.000";
}

function getRunLabel(run, fallbackIndex) {
  const explicitLabel = run?.run_label || run?.runLabel;
  if (explicitLabel) {
    return explicitLabel;
  }

  const runIndex = Number.isFinite(run?.run_index)
    ? run.run_index
    : Number.isFinite(run?.runIndex)
      ? run.runIndex
      : fallbackIndex + 1;

  return FORECAST_LABELS[runIndex] || `run ${runIndex}`;
}

function sortTickerMetrics(metrics) {
  const items = [...metrics];
  items.sort((a, b) => {
    if (a.prediction_ratio !== b.prediction_ratio) {
      return a.prediction_ratio - b.prediction_ratio;
    }
    return a.ticker.localeCompare(b.ticker);
  });
  return items;
}

function renderTickerOptions(selectedTicker) {
  const sorted = sortTickerMetrics(tickerMetrics);
  const query = (tickerSearch?.value || "").trim().toUpperCase();

  tickerSelect.innerHTML = "";

  const filtered = !query
    ? sorted
    : sorted.filter((item) => String(item.ticker).toUpperCase().includes(query));

  filtered.forEach((item) => {
    const option = document.createElement("option");
    option.value = item.ticker;
    option.textContent = `${item.ticker} (${formatRatio(item.prediction_ratio)})`;
    if (item.ticker === selectedTicker) {
      option.selected = true;
    }
    tickerSelect.appendChild(option);
  });

  if (filtered.length === 0) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No tickers found";
    tickerSelect.appendChild(option);
  }
}

function horizonToDaysFromToday(horizon) {
  if (horizon === null || horizon === undefined) return 0;
  if (typeof horizon === "number") return horizon;

  const value = String(horizon).trim().toLowerCase();
  if (!value) return 0;

  if (value.endsWith("h")) {
    const hours = parseFloat(value.slice(0, -1)) || 0;
    return Math.round(hours / 24);
  }
  if (value.endsWith("w")) {
    const weeks = parseFloat(value.slice(0, -1)) || 0;
    return weeks * 7;
  }
  if (value.endsWith("m")) {
    const months = parseFloat(value.slice(0, -1)) || 0;
    return months * 30;
  }
  if (value.endsWith("y")) {
    const years = parseFloat(value.slice(0, -1)) || 0;
    return years * 365;
  }

  return 0;
}

// Anchor forecast horizon dates to a fixed base date so the forecast
// segment stays stable while actual prices update daily.
// Using TimesFM base date for all models per your instruction.
const FORECAST_BASE_DATE = "2026-06-22";

function horizonLabelsToDates(horizons) {
  const base = new Date(FORECAST_BASE_DATE);
  if (Number.isNaN(base.getTime())) {
    // Fallback (should not happen): anchor to current date.
    const today = new Date();
    return (horizons || []).map((horizon) => {
      const date = new Date(today);
      date.setDate(today.getDate() + horizonToDaysFromToday(horizon));
      return date.toISOString().slice(0, 10);
    });
  }

  return (horizons || []).map((horizon) => {
    const date = new Date(base);
    date.setDate(base.getDate() + horizonToDaysFromToday(horizon));
    return date.toISOString().slice(0, 10);
  });
}

function evenlySpacedPositions(count, start, end) {
  if (count <= 0) return [];
  if (count === 1) return [start];

  const span = end - start;
  return Array.from({ length: count }, (_, idx) => start + (span * idx) / (count - 1));
}

function buildSegmentTicks(dates, positions, maxTicks = 8) {
  const tickvals = [];
  const ticktext = [];
  if (dates.length === 0 || positions.length === 0) {
    return { tickvals, ticktext };
  }

  const step = Math.max(1, Math.floor(dates.length / maxTicks));
  for (let i = 0; i < dates.length; i += step) {
    tickvals.push(positions[i]);
    ticktext.push(dates[i]);
  }

  if (tickvals[tickvals.length - 1] !== positions[positions.length - 1]) {
    tickvals.push(positions[positions.length - 1]);
    ticktext.push(dates[dates.length - 1]);
  }

  return { tickvals, ticktext };
}

function nextFrame() {
  return new Promise((resolve) => requestAnimationFrame(resolve));
}

async function loadTickers() {
  try {
    const data = await fetchJSON(`${API_BASE}/api/ticker-metrics`);
    tickerMetrics = data.tickers || [];
    renderTickerOptions(tickerMetrics[0]?.ticker || "");

    if (tickerMetrics.length > 0) {
      await updateTicker(tickerMetrics[0].ticker);
    } else {
      commentaryDiv.textContent = "No tickers available.";
    }
  } catch (err) {
    console.error(err);
    commentaryDiv.textContent = "Error loading tickers from backend.";
  }
}

async function updateChart(ticker) {
  const [forecast, history, actual] = await Promise.all([
    fetchJSON(`${API_BASE}/api/forecast/${ticker}`),
    fetch(`${API_BASE}/api/history/${ticker}`)
      .then((resp) => (resp.ok ? resp.json() : null))
      .catch(() => null),
    fetch(`${API_BASE}/api/actual/${ticker}`)
      .then((resp) => (resp.ok ? resp.json() : { dates: [], prices: [] }))
      .catch(() => ({ dates: [], prices: [] })),
  ]);

  const traces = [];
  let historyDates = [];
  let historyValues = [];

  if (history && Array.isArray(history.dates) && Array.isArray(history.closes)) {
    const count = Math.min(history.dates.length, history.closes.length);
    historyDates = history.dates.slice(0, count);
    historyValues = history.closes.slice(0, count);
  }

  const forecastRuns = [];
  (forecast.runs || []).forEach((run, idx) => {
    const horizons = Array.isArray(run.horizons) ? run.horizons : [];
    const values = Array.isArray(run.values) ? run.values : [];
    const dates = horizonLabelsToDates(horizons);
    const count = Math.min(dates.length, values.length);

    if (count === 0) return;

    forecastRuns.push({
      runIndex: run.run_index ?? idx,
      runLabel: getRunLabel(run, idx),
      dates: dates.slice(0, count),
      values: values.slice(0, count),
    });
  });

  const forecastDateSet = new Set();
  forecastRuns.forEach((run) => {
    run.dates.forEach((date) => forecastDateSet.add(date));
  });

  const actualPairs = (Array.isArray(actual?.dates) ? actual.dates : []).map((date, index) => ({
    date,
    price: Array.isArray(actual?.prices) ? actual.prices[index] : undefined,
  })).filter((item) => item.date && Number.isFinite(item.price))
    .sort((a, b) => new Date(a.date) - new Date(b.date));
  const actualDates = actualPairs.map((item) => item.date);
  const actualPrices = actualPairs.map((item) => item.price);

  const forecastDates = Array.from(forecastDateSet).sort((a, b) => new Date(a) - new Date(b));

  if (historyDates.length === 0 && forecastDates.length === 0) {
    Plotly.purge(chartDiv);
    await Plotly.newPlot(chartDiv, [], {
      title: `Forecast – ${(forecast && forecast.ticker) || ticker}`,
      paper_bgcolor: "#020617",
      plot_bgcolor: "#020617",
      font: { color: "#e5e7eb" },
    }, { responsive: true, displaylogo: false });
    Plotly.Plots.resize(chartDiv);
    return;
  }

  const hasHistory = historyDates.length > 0;
  const hasForecast = forecastDates.length > 0;

  // Keep the layout as two segments:
  // - history on the left half: 0 → HISTORY_WIDTH_RATIO
  // - forecast + actual on the right half: HISTORY_WIDTH_RATIO → 1
  //
  // For actuals, compute x-position from a continuous shared timeline
  // (Option C). This way:
  // - actual points progress gradually day-by-day
  // - when an actual date equals a forecast date, they map to the same x
  // - actual will naturally stop before forecast horizon as long as its
  //   real dates are earlier than the forecast start.

  const historyPositions = evenlySpacedPositions(
    historyDates.length,
    0,
    hasHistory && hasForecast ? HISTORY_WIDTH_RATIO : 1,
  );

  // Right-side continuous axis (real dates), based on forecast range.
  const rightTimeline = Array.from(new Set(forecastDates.slice())).sort(
    (a, b) => new Date(a) - new Date(b)
  );

  const rightStartX = hasHistory ? HISTORY_WIDTH_RATIO : 0;
  const rightEndX = 1;

  const rightIndexByDate = new Map();
  rightTimeline.forEach((d, i) => rightIndexByDate.set(d, i));

  const rightToAxisPos = (date) => {
    if (!rightTimeline.length) return rightStartX;
    const idx = rightIndexByDate.get(date);
    // If we have an exact match with a forecast date, align perfectly.
    if (idx !== undefined) {
      if (rightTimeline.length === 1) return rightStartX;
      const t = idx / (rightTimeline.length - 1);
      return rightStartX + t * (rightEndX - rightStartX);
    }

    // If actual date is between forecast dates, interpolate based on
    // position in the sorted date array.
    const actualTime = new Date(date).getTime();
    const times = rightTimeline.map((d) => new Date(d).getTime());

    // Clamp to forecast range (so actual cannot cross into the forecast).
    if (actualTime <= times[0]) return rightStartX;
    if (actualTime >= times[times.length - 1]) return rightEndX;

    // Find bracket [i, i+1]
    let i = 0;
    while (i + 1 < times.length && !(times[i] <= actualTime && actualTime <= times[i + 1])) {
      i++;
    }
    const leftT = times[i];
    const rightT = times[i + 1];
    const span = rightT - leftT;
    const frac = span === 0 ? 0 : (actualTime - leftT) / span;

    const leftIdx = i;
    const rightIdx = i + 1;
    const t = (leftIdx + frac) / (times.length - 1);

    return rightStartX + t * (rightEndX - rightStartX);
  };

  const forecastPositions = forecastDates.map(rightToAxisPos);
  const actualPositions = actualDates.map(rightToAxisPos);

  const forecastPositionByDate = new Map();
  forecastDates.forEach((date, index) => {
    forecastPositionByDate.set(date, forecastPositions[index]);
  });

  if (historyDates.length > 0) {
    traces.push({
      x: historyPositions,
      y: historyValues,
      mode: "lines",
      name: "history",
      line: { color: "#9ca3af", width: 2 },
      text: historyDates,
      hovertemplate: "%{text}<br>Price: %{y:.2f}<extra>history</extra>",
    });
  }

  forecastRuns.forEach((run, idx) => {
    traces.push({
      x: run.dates.map((date) => forecastPositionByDate.get(date)),
      y: run.values,
      mode: "lines+markers",
      name: run.runLabel,
      line: {
        color: getColor(idx),
        width: 2,
        dash: idx % 2 === 0 ? "solid" : "dash",
      },
      marker: {
        color: getColor(idx),
        size: 6,
      },
      text: run.dates,
      hovertemplate: "%{text}<br>Price: %{y:.2f}<extra>%{fullData.name}</extra>",
    });
  });

  if (actualDates.length > 0 && actualPrices.length > 0) {
    const count = Math.min(actualDates.length, actualPrices.length);
    traces.push({
      x: actualPositions.slice(0, count),
      y: actualPrices.slice(0, count),
      mode: "lines+markers",
      name: "actual",
      line: {
        color: "#3b82f6",
        width: 3,
      },
      marker: {
        color: "#3b82f6",
        size: 7,
      },
      text: actualDates.slice(0, count),
      hovertemplate: "%{text}<br>Price: %{y:.2f}<extra>actual</extra>",
    });
  }

  const historyTicks = buildSegmentTicks(historyDates, historyPositions, 8);
  const forecastTicks = buildSegmentTicks(forecastDates, forecastPositions, 5);
  const tickvals = [...historyTicks.tickvals];
  const ticktext = [...historyTicks.ticktext];

  if (hasHistory && hasForecast) {
    if (tickvals.length > 0) {
      tickvals.pop();
      ticktext.pop();
    }
  }

  tickvals.push(...forecastTicks.tickvals);
  ticktext.push(...forecastTicks.ticktext);

  const layout = {
    title: `Forecast – ${(forecast && forecast.ticker) || ticker}`,
    paper_bgcolor: "#020617",
    plot_bgcolor: "#020617",
    font: { color: "#e5e7eb" },
    autosize: true,
    margin: { l: 60, r: 20, t: 60, b: 180 },
    xaxis: {
      title: "Date",
      type: "linear",
      range: [0, 1],
      tickmode: "array",
      tickvals,
      ticktext,
      tickangle: 90,
      title_standoff: 28,
      gridcolor: "#1f2937",
      zeroline: false,
    },
    yaxis: {
      title: "Price",
      gridcolor: "#1f2937",
      automargin: false,
      tickformat: "~g",
    },
    legend: {
      orientation: "h",
      yanchor: "top",
      y: -0.55,
      xanchor: "center",
      x: 0.5,
    },
    shapes: hasHistory && hasForecast ? [
      {
        type: "line",
        x0: HISTORY_WIDTH_RATIO,
        x1: HISTORY_WIDTH_RATIO,
        y0: 0,
        y1: 1,
        xref: "x",
        yref: "paper",
        line: {
          color: "#475569",
          width: 1,
          dash: "dot",
        },
      },
    ] : [],
  };

  Plotly.purge(chartDiv);
  await Plotly.newPlot(chartDiv, traces, layout, {
    responsive: true,
    displaylogo: false,
  });
  Plotly.Plots.resize(chartDiv);
}

async function updateCommentary(ticker) {
  commentaryDiv.textContent = `Loading commentary for ${ticker}…`;
  const resp = await fetch(`${API_BASE}/api/commentary/${ticker}`);

  commentaryDiv.innerHTML = "";

  if (!resp.ok) {
    const titleSpan = document.createElement("span");
    titleSpan.className = "ticker-label";
    const textNode = document.createElement("pre");
    textNode.style.marginTop = "0.5rem";
    textNode.style.whiteSpace = "pre-wrap";
    titleSpan.textContent = `${ticker} commentary`;
    textNode.textContent = `No commentary available for ${ticker}.`;
    commentaryDiv.appendChild(titleSpan);
    commentaryDiv.appendChild(document.createElement("br"));
    commentaryDiv.appendChild(document.createElement("br"));
    commentaryDiv.appendChild(textNode);
    return false;
  }

  const data = await resp.json();
  const titleSpan = document.createElement("span");
  titleSpan.className = "ticker-label";
  titleSpan.textContent = `${data.ticker} commentary`;
  commentaryDiv.appendChild(titleSpan);

  const blocks = Array.isArray(data.commentaries) ? data.commentaries : [];
  if (blocks.length === 0) {
    const emptyNode = document.createElement("pre");
    emptyNode.style.marginTop = "0.75rem";
    emptyNode.style.whiteSpace = "pre-wrap";
    emptyNode.textContent = `No commentary available for ${ticker}.`;
    commentaryDiv.appendChild(document.createElement("br"));
    commentaryDiv.appendChild(document.createElement("br"));
    commentaryDiv.appendChild(emptyNode);
    return false;
  }

  blocks.forEach((block, index) => {
    const section = document.createElement("div");
    section.style.marginTop = index === 0 ? "0.85rem" : "1.15rem";

    const sourceTitle = document.createElement("div");
    sourceTitle.className = "ticker-label";
    sourceTitle.style.fontSize = "0.95rem";
    sourceTitle.textContent = block.source;

    const textNode = document.createElement("pre");
    textNode.style.marginTop = "0.4rem";
    textNode.style.marginBottom = "0";
    textNode.style.whiteSpace = "pre-wrap";
    textNode.textContent = block.commentary;

    section.appendChild(sourceTitle);
    section.appendChild(textNode);
    commentaryDiv.appendChild(section);
  });
  return true;
}

async function updateTicker(ticker) {
  const hasCommentary = await updateCommentary(ticker);
  if (!hasCommentary) {
    await nextFrame();
    await nextFrame();
  }
  await updateChart(ticker);
  if (!hasCommentary) {
    await nextFrame();
    await updateChart(ticker);
  }
  requestAnimationFrame(() => Plotly.Plots.resize(chartDiv));
}

tickerSelect?.addEventListener("change", async (event) => {
  const ticker = event.target.value;
  if (ticker) {
    await updateTicker(ticker);
  }
});

// Make the search box behave like the dropdown:
// - filter dropdown options as user types
// - when user hits Enter, select the first matching ticker and load it
// - also load the ticker when the user clicks an option from the dropdown
tickerSearch?.addEventListener("input", () => {
  // Keep dropdown options filtered to search results
  renderTickerOptions(tickerSelect.value);
});

tickerSearch?.addEventListener("keydown", async (event) => {
  if (event.key !== "Enter") return;

  const query = (tickerSearch.value || "").trim().toUpperCase();
  if (!query) return;

  const sorted = sortTickerMetrics(tickerMetrics);
  const filtered = sorted.filter((item) => String(item.ticker).toUpperCase().includes(query));
  if (!filtered.length) return;

  const first = filtered[0].ticker;
  tickerSelect.value = first;
  await updateTicker(first);
});

loadTickers();

window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    if (chartDiv && chartDiv.data) {
      Plotly.Plots.resize(chartDiv);
    }
  }, 120);
});
