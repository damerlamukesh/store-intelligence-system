const storeId = "STORE_BLR_002";

const pct = (value) => `${Math.round((value || 0) * 100)}%`;

async function getJson(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${path} returned ${response.status}`);
  return response.json();
}

function renderMetrics(metrics) {
  document.querySelector("#visitors").textContent = metrics.unique_visitors;
  document.querySelector("#conversion").textContent = pct(metrics.conversion_rate);
  document.querySelector("#queue").textContent = metrics.current_queue_depth;
  document.querySelector("#abandonment").textContent = pct(metrics.abandonment_rate);
}

function renderHeatmap(heatmap) {
  const root = document.querySelector("#heatmap");
  root.innerHTML = "";
  for (const zone of heatmap.zones) {
    const node = document.createElement("div");
    node.className = "zone";
    node.style.setProperty("--heat", `${Math.min(100, zone.heat)}%`);
    node.innerHTML = `<strong>${zone.zone_id}</strong><span>${zone.visits} visits · ${zone.avg_dwell_seconds}s avg dwell</span>`;
    root.appendChild(node);
  }
}

function renderFunnel(funnel) {
  const max = Math.max(...funnel.stages.map((stage) => stage.count), 1);
  const root = document.querySelector("#funnel");
  root.innerHTML = "";
  for (const stage of funnel.stages) {
    const width = Math.round((stage.count / max) * 100);
    const node = document.createElement("div");
    node.className = "bar";
    node.innerHTML = `<label>${stage.stage}: ${stage.count}</label><div class="track"><div class="fill" style="width:${width}%"></div></div><span>${pct(stage.drop_off_from_previous)} drop-off</span>`;
    root.appendChild(node);
  }
}

function renderAnomalies(data) {
  const root = document.querySelector("#anomalies");
  root.innerHTML = "";
  for (const item of data.anomalies) {
    const node = document.createElement("div");
    node.className = "anomaly";
    node.innerHTML = `<strong>${item.severity} · ${item.type}</strong><span>${item.suggested_action}</span>`;
    root.appendChild(node);
  }
}

async function refresh() {
  const [metrics, heatmap, funnel, anomalies, health] = await Promise.all([
    getJson(`/stores/${storeId}/metrics`),
    getJson(`/stores/${storeId}/heatmap`),
    getJson(`/stores/${storeId}/funnel`),
    getJson(`/stores/${storeId}/anomalies`),
    getJson("/health"),
  ]);
  renderMetrics(metrics);
  renderHeatmap(heatmap);
  renderFunnel(funnel);
  renderAnomalies(anomalies);
  document.querySelector("#status").textContent = `${health.status} · updated ${new Date().toLocaleTimeString()}`;
}

document.querySelector("#refresh").addEventListener("click", refresh);
refresh();
setInterval(refresh, 2500);
