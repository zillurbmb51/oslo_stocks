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
let requestVersion = 0;
let activeTicker = "";
let busy = false;
const saved = (key, fallback) => { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; } };
const persist = (key, value) => { try { localStorage.setItem(key, JSON.stringify(value)); } catch {} };
let watchlist = saved("osl-watchlist", []);
if (!Array.isArray(watchlist)) watchlist = [];
const money = value => Number.isFinite(value) ? value.toLocaleString("en-GB", {maximumFractionDigits: 2, minimumFractionDigits: 2}) : "—";
function renderWatchlist() {
  const container = document.getElementById("watchlist");
  container.replaceChildren();
  watchlist.filter(ticker => tickerMetrics.some(item => item.ticker === ticker)).forEach(ticker => {
    const button = document.createElement("button");
    button.textContent = ticker;
    button.onclick = () => { tickerSearch.value = ""; renderTickerOptions(ticker); updateTicker(ticker); };
    container.append(button);
  });
  const watching = watchlist.includes(activeTicker);
  document.getElementById("watch-toggle").textContent = watching ? "★ Saved ticker" : "☆ Save ticker";
  document.getElementById("watch-toggle").setAttribute("aria-pressed", String(watching));
}
function renderInsights(ticker, forecast, history, actual) {
  const observations = [
    ...(history?.dates || []).map((date, i) => ({date, value: history.closes?.[i]})),
    ...(actual?.dates || []).map((date, i) => ({date, value: actual.prices?.[i]}))
  ].filter(point => point.date && Number.isFinite(point.value)).sort((a,b) => a.date.localeCompare(b.date));
  const latest = observations.at(-1);
  const runs = (forecast.runs || []).map((run, index) => {
    const end = Math.min(run.values?.length || 0, run.horizons?.length || 0) - 1;
    return {label: getRunLabel(run, index), value: run.values?.[end], horizon: run.horizons?.[end], color: getColor(index)};
  }).filter(run => Number.isFinite(run.value));
  const values = runs.map(run => run.value).sort((a,b) => a-b);
  const median = values.length ? (values[Math.floor((values.length - 1)/2)] + values[Math.floor(values.length/2)])/2 : null;
  const low = values[0], high = values.at(-1);
  const audited = actual?.source === "validated_snapshot";
  const change = !audited && latest?.value > 0 && median !== null ? (median/latest.value - 1)*100 : null;
  const cards = [
    ["Last observed price", money(latest?.value), latest ? `Observed ${latest.date}` : "No price history available", "#7fdac8"],
    [audited ? "Archived model endpoint" : "Median model endpoint", money(median), "Archived runs; not refreshed daily", "#b8a4ff"],
    [audited ? "Price validation" : "Endpoint difference", audited ? (actual.validation_status === "accepted" ? "Passed" : "Excluded") : change === null ? "—" : `${change >= 0 ? "+" : ""}${change.toFixed(1)}%`, audited ? "No comparison across unverified price bases" : "Median endpoint vs. last observed price", change !== null && change < 0 ? "#ff95a3" : "#7fdac8"],
    ["Available model runs", String(runs.length), `Endpoint range ${money(low)} – ${money(high)}`, "#f7ca7e"]
  ];
  const container = document.getElementById("metrics"); container.replaceChildren();
  cards.forEach(([label,value,note,color]) => {
    const card = document.createElement("article"); card.className = "metric"; card.style.setProperty("--tone", color);
    [ ["small",label], ["strong",value], ["p",note] ].forEach(([tag,text]) => {const node = document.createElement(tag); node.textContent = text; card.append(node);});
    container.append(card);
  });
  document.getElementById("chart-heading").textContent = `${ticker} · History & forecasts`;
  document.getElementById("insight").textContent = runs.length ? `${runs.length} model runs have final projections between ${money(low)} and ${money(high)}. ${latest ? `The latest available observation is ${money(latest.value)} on ${latest.date}.` : "No observed price is available for comparison."} These endpoints may cover different horizons; their range describes model variation, not a confidence interval.` : "No usable model endpoints are available for this ticker.";
  if (audited) document.getElementById("insight").textContent = latest
    ? `${ticker}: latest validated close ${money(latest.value)} NOK on ${latest.date}. These prices passed provider consistency checks. Archived model runs are not refreshed or rebased to this price series; their implied returns are not compared here.`
    : `${ticker} is excluded from the validated price snapshot. Review the data-quality status above; archived projections remain available for reference.`;
  const rows = document.getElementById("model-rows"); rows.replaceChildren();
  runs.forEach(run => {
    const row = document.createElement("tr");
    const delta = !audited && latest?.value > 0 ? (run.value/latest.value - 1)*100 : null;
    [run.label, run.horizon, money(run.value), delta === null ? (audited ? "Not rebased" : "—") : `${delta >= 0 ? "+" : ""}${delta.toFixed(1)}%`].forEach((text,index) => {
      const cell = document.createElement("td"); cell.textContent = text;
      if(index === 0) { const dot = document.createElement("span"); dot.className = "model-dot"; dot.style.background = run.color; cell.prepend(dot); }
      if(index === 3 && delta !== null) cell.className = delta >= 0 ? "positive" : "negative";
      row.append(cell);
    }); rows.append(row);
  });
}

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

  if (filtered.length && !filtered.some(item => item.ticker === selectedTicker)) {
    const prompt = document.createElement("option");
    prompt.value = "";
    prompt.textContent = "Choose a match or press Enter";
    prompt.selected = true;
    tickerSelect.appendChild(prompt);
  }

  filtered.forEach((item) => {
    const option = document.createElement("option");
    option.value = item.ticker;
    option.textContent = `${item.ticker} · ${item.validation_status === "accepted" ? "Validated prices" : item.validation_status || "Legacy data"}`;
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

async function loadTickers() {
  try {
    const data = await fetchJSON(`${API_BASE}/api/ticker-metrics`);
    tickerMetrics = data.tickers || [];
    const preferred = saved("osl-ticker", "");
    const selected = tickerMetrics.some(item => item.ticker === preferred) ? preferred : sortTickerMetrics(tickerMetrics).find(item => item.validation_status === "accepted")?.ticker || tickerMetrics[0]?.ticker;
    renderTickerOptions(selected || "");
    document.getElementById("universe-count").textContent = tickerMetrics.length;
    renderWatchlist();

    if (tickerMetrics.length > 0) {
      await updateTicker(selected);
    } else {
      commentaryDiv.textContent = "No tickers available.";
      document.getElementById("load-status").textContent = "No tickers available in the current dataset.";
    }
  } catch (err) {
    console.error(err);
    tickerSelect.replaceChildren();
    const unavailable = document.createElement("option");
    unavailable.textContent = "Data service unavailable";
    tickerSelect.append(unavailable);
    commentaryDiv.textContent = "Error loading tickers from backend.";
    document.getElementById("load-status").textContent = "Could not connect to the data service. Use Refresh to retry.";
  }
}

async function updateChart(ticker, version) {
  const [forecast, history, actual] = await Promise.all([
    fetchJSON(`${API_BASE}/api/forecast/${ticker}`),
    fetch(`${API_BASE}/api/history/${ticker}`)
      .then((resp) => (resp.ok ? resp.json() : null))
      .catch(() => null),
    fetch(`${API_BASE}/api/actual/${ticker}`)
      .then((resp) => (resp.ok ? resp.json() : { dates: [], prices: [] }))
      .catch(() => ({ dates: [], prices: [] })),
  ]);

  if (version !== requestVersion) return;
  renderInsights(ticker, forecast, history, actual);
  await window.MarketExplorer.load(ticker, forecast, () => version === requestVersion);
}

async function updateCommentary(ticker, version) {
  commentaryDiv.textContent = `Loading commentary for ${ticker}…`;
  const resp = await fetch(`${API_BASE}/api/commentary/${ticker}`);

  if (version !== requestVersion) return false;
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
  if (version !== requestVersion) return false;
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
  const version = ++requestVersion;
  activeTicker = ticker;
  busy = true;
  persist("osl-ticker", ticker);
  renderWatchlist();
  document.getElementById("refresh").disabled = true;
  document.getElementById("load-status").textContent = `Loading ${ticker}…`;
  document.getElementById("ticker-quality").textContent = `Checking ${ticker} validation…`;
  chartDiv.style.opacity = "0.4";
  try {
    await Promise.all([updateCommentary(ticker, version), updateChart(ticker, version), updateMarketStatus(ticker, version)]);
    if (version !== requestVersion) return;
    document.getElementById("load-status").textContent = `${ticker} · Checked at ${new Date().toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"})} · Observation dates are shown below.`;
  } catch (error) {
    if (version !== requestVersion) return;
    document.getElementById("load-status").textContent = `Could not load ${ticker}. Use Refresh to retry.`;
    document.getElementById("metrics").replaceChildren();
    document.getElementById("model-rows").replaceChildren();
    document.getElementById("insight").textContent = "Insights unavailable until the data loads successfully.";
    if (window.Plotly) { Plotly.purge(chartDiv); Plotly.purge(document.getElementById("indicator-chart")); }
    console.error(error);
  } finally {
    if (version === requestVersion) {busy = false; chartDiv.style.opacity = "1"; document.getElementById("refresh").disabled = false;}
  }
}

document.getElementById("watch-toggle").onclick = () => {
  if (!activeTicker) return;
  watchlist = watchlist.includes(activeTicker) ? watchlist.filter(ticker => ticker !== activeTicker) : [...watchlist, activeTicker];
  persist("osl-watchlist", watchlist); renderWatchlist();
};
document.getElementById("refresh").onclick = () => activeTicker ? updateTicker(activeTicker) : loadTickers();
const autoRefresh = document.getElementById("auto-refresh");
autoRefresh.checked = saved("osl-auto-refresh", true) === true;
autoRefresh.onchange = () => persist("osl-auto-refresh", autoRefresh.checked);
setInterval(() => {
  if (autoRefresh.checked && !document.hidden && !busy && activeTicker) updateTicker(activeTicker);
}, 5 * 60 * 1000);

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

async function updateMarketStatus(ticker, version) {
  try {
    const data = await fetchJSON(`${API_BASE}/api/market-status?ticker=${encodeURIComponent(ticker)}`);
    if (version !== requestVersion) return;
    const panel = document.querySelector(".automation-panel");
    panel.classList.toggle("stale", data.stale || !data.available);
    document.getElementById("data-freshness").textContent = data.available
      ? `${data.stale ? "Awaiting newer data" : "Current snapshot"} · ${data.cutoff}` : "Market snapshot unavailable";
    document.getElementById("automation-status").textContent = data.available
      ? `${data.counts.accepted} tickers accepted · ${data.counts.quarantined} quarantined · ${data.counts.unavailable} unavailable. Updates run weekdays at 17:35 UTC (18:35 winter / 19:35 summer in Oslo). No daily GitHub push required.${data.error ? " The last download failed; showing the last good snapshot." : ""}`
      : "No validated snapshot is available. Check the update runs for a failed or disabled workflow.";
    const quality = data.ticker_status;
    document.getElementById("ticker-quality").textContent = quality
      ? `${ticker}: ${quality.status === "accepted" ? `passed provider checks; latest close ${quality.last_accepted_date}` : `${quality.status} — ${(quality.issues || []).join(", ").replaceAll("_", " ")}`}. Checks do not independently verify every corporate action.`
      : `${ticker}: no validation record available.`;
    const body = document.getElementById("backtest-rows"); body.replaceChildren();
    document.getElementById("backtest-date").textContent = data.backtest ? `Data through ${data.backtest.as_of}` : "Unavailable";
    for (const horizon of [1,5,20,30,60,100]) {
      const baseline = data.backtest?.summary.find(row => row.horizon_days === horizon && row.model === "no_change");
      const adaptive = data.backtest?.summary.find(row => row.horizon_days === horizon && row.model === "adaptive_ensemble");
      if (!baseline || !adaptive) continue;
      const row = document.createElement("tr");
      [horizon, baseline.mae_log_return_pct.toFixed(3), adaptive.mae_log_return_pct.toFixed(3),
       adaptive.mae_log_return_pct < baseline.mae_log_return_pct ? "Adaptive lower error" : "No-change lower / equal error"].forEach(value => {
        const cell=document.createElement("td"); cell.textContent=value; row.append(cell);
      }); body.append(row);
    }
  } catch {
    if (version !== requestVersion) return;
    document.getElementById("data-freshness").textContent = "Freshness check failed";
    document.getElementById("ticker-quality").textContent = "Validation status unavailable; retry Refresh.";
  }
}
