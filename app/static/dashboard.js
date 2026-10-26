"use strict";

const $ = (id) => document.getElementById(id);

const targetNames = {
  "1.1.1.1": "Cloudflare DNS",
  "8.8.8.8": "Google Public DNS",
  "9.9.9.9": "Quad9 DNS",
};

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function parseDate(value) {
  if (!value) return null;
  // Treat a timezone-free database timestamp as UTC.
  const normalized = /(?:Z|[+-]\d{2}:\d{2})$/i.test(value)
    ? value
    : `${value}Z`;
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatClock(value) {
  const date = parseDate(value);
  if (!date) return "—";
  return date.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatDateTime(value) {
  const date = parseDate(value);
  if (!date) return "Time unavailable";
  return date.toLocaleString([], {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatLatency(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) {
    return "—";
  }
  return `${Number(value).toFixed(1)} ms`;
}

function formatDuration(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) {
    return "In progress";
  }

  let seconds = Math.max(0, Math.floor(Number(value)));
  const hours = Math.floor(seconds / 3600);
  seconds %= 3600;
  const minutes = Math.floor(seconds / 60);
  seconds %= 60;

  if (hours) return `${hours}h ${minutes}m`;
  if (minutes) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}

function statusLabel(status) {
  return {
    online: "Online",
    offline: "Offline",
    error: "Probe error",
    not_checked: "Not checked",
    unavailable: "Unavailable",
    pending: "Awaiting first check",
    healthy: "Healthy",
    degraded: "Degraded",
    resolved: "DNS resolved",
    failed: "DNS lookup failed",
    unhealthy: "HTTP unhealthy",
  }[status] || "Unknown";
}

function chipClass(status) {
  return {
    online: "chip-success",
    resolved: "chip-success",
    offline: "chip-danger",
    failed: "chip-danger",
    unhealthy: "chip-warning",
    error: "chip-warning",
    not_checked: "chip-muted",
    pending: "chip-muted",
    healthy: "chip-success",
    degraded: "chip-warning",
    unavailable: "chip-muted",
  }[status] || "chip-muted";
}

function makeChip(status) {
  return element("span", `status-chip ${chipClass(status)}`, statusLabel(status));
}

async function getJson(path) {
  const response = await fetch(path, {
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`${path} returned HTTP ${response.status}`);
  }
  return response.json();
}

function renderStatus(payload) {
  const status = payload.internet_status || "unknown";
  const banner = $("connection-banner");
  banner.className = `status-banner status-${status}`;

  $("status-icon").textContent =
    status === "online" ? "✓" : status === "offline" ? "!" : "?";

  $("overall-title").textContent = {
    online: "Your internet connection is online",
    offline: "No configured targets are responding",
    unknown: "Connectivity status is uncertain",
  }[status] || "Connectivity status is uncertain";

  $("status-kicker").textContent =
    status === "online" ? "CONNECTION HEALTHY" :
    status === "offline" ? "CONNECTION INTERRUPTED" :
    "MONITORING STATUS";

  $("overall-message").textContent = {
    online: "At least one configured destination responded to its latest probe.",
    offline: "Every completed probe failed. Check the network and verify the results.",
    unknown: "The monitor has insufficient results to determine connectivity.",
  }[status] || "Waiting for a reliable connectivity result.";

  const targets = Array.isArray(payload.targets) ? payload.targets : [];
  const online = targets.filter((target) => target.status === "online").length;

  $("banner-online-count").textContent = online;
  $("reachable-count").textContent = online;
  $("reachable-detail").textContent = `${targets.length} configured target${targets.length === 1 ? "" : "s"}`;
  $("target-count").textContent = `${targets.length} target${targets.length === 1 ? "" : "s"}`;

  const latencies = targets
    .filter((target) => target.status === "online" &&
      target.latency_ms !== null &&
      Number.isFinite(Number(target.latency_ms)))
    .map((target) => Number(target.latency_ms));

  if (latencies.length) {
    const average = latencies.reduce((total, value) => total + value, 0) / latencies.length;
    $("avg-latency").textContent = formatLatency(average);
    $("latency-detail").textContent = `Across ${latencies.length} responding target${latencies.length === 1 ? "" : "s"}`;
  } else {
    $("avg-latency").textContent = "—";
    $("latency-detail").textContent = "No successful latency samples";
  }

  $("last-updated").textContent = payload.last_checked
    ? `Last check ${formatClock(payload.last_checked)}`
    : "Waiting for first check";

  $("active-incidents").textContent = payload.active_outage ? "1" : "0";
  $("incident-detail").textContent = payload.active_outage
    ? "An internet outage is unresolved"
    : "No unresolved internet outage";
  renderTargets(targets);
}

function renderTargets(targets) {
  const list = $("target-list");
  list.replaceChildren();

  if (!targets.length) {
    list.append(element("div", "loading-row", "No monitoring targets are configured."));
    return;
  }

  for (const target of targets) {
    const row = element("article", "target-card");
    const left = element("div");
    const heading = element("div", "target-heading");
    const mark = element("span", "target-mark", "⌁");
    const copy = element("div", "target-copy");
    const name = element(
      "span", "target-name",
      targetNames[target.target] || target.target
    );
    const purpose = element("span", "target-purpose", target.target);
    const chip = makeChip(target.status);

    copy.append(name, purpose);
    heading.append(mark, copy);
    left.append(heading, chip);

    const latency = element("div", "target-latency", formatLatency(target.latency_ms));
    const latencyLabel = element(
      "small", "", target.timestamp ? `Checked ${formatClock(target.timestamp)}` : "Awaiting check"
    );
    latency.append(latencyLabel);

    row.append(left, latency);
    list.append(row);
  }
}

function renderHistory(history) {
  const items = Array.isArray(history.items) ? history.items : [];
  $("recent-checks").textContent = items.length;
  $("chart-range").textContent = `${items.length} recent samples`;
  renderActivity(items);
  drawChart(items);
}

function renderActivity(items) {
  const tbody = $("activity-list");
  tbody.replaceChildren();

  if (!items.length) {
    const row = element("tr");
    const cell = element("td", "loading-row", "No check records yet.");
    cell.colSpan = 3;
    row.append(cell);
    tbody.append(row);
    return;
  }

  for (const item of items.slice(0, 6)) {
    const row = element("tr");
    const destination = element("td", "", item.target);
    const cellStatus = element("td");
    const probeError = item.error_message &&
      item.error_message.startsWith("PROBE_ERROR:");
    cellStatus.append(
      makeChip(probeError ? "error" : item.is_up ? "online" : "offline")
    );
    const latency = element(
      "td", "", item.is_up ? formatLatency(item.latency_ms) : "—"
    );
    row.append(destination, cellStatus, latency);
    tbody.append(row);
  }
}

function drawChart(items) {
  const canvas = $("latency-chart");
  const empty = $("chart-empty");

  const points = items
    .filter((item) => item.is_up &&
      item.latency_ms !== null &&
      Number.isFinite(Number(item.latency_ms)) &&
      parseDate(item.timestamp))
    .slice()
    .reverse();

  if (!points.length) {
    canvas.hidden = true;
    empty.hidden = false;
    return;
  }

  canvas.hidden = false;
  empty.hidden = true;

  const bounds = canvas.getBoundingClientRect();
  const width = Math.max(bounds.width, 220);
  const height = Math.max(bounds.height, 150);
  const ratio = Math.max(1, window.devicePixelRatio || 1);

  canvas.width = Math.round(width * ratio);
  canvas.height = Math.round(height * ratio);

  const context = canvas.getContext("2d");
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  context.clearRect(0, 0, width, height);

  const left = 43;
  const right = 12;
  const top = 12;
  const bottom = height - 28;
  const plotWidth = width - left - right;
  const plotHeight = bottom - top;

  const values = points.map((point) => Number(point.latency_ms));
  let min = Math.max(0, Math.floor((Math.min(...values) - 10) / 10) * 10);
  let max = Math.ceil((Math.max(...values) + 10) / 10) * 10;
  if (max <= min) max = min + 10;

  context.font = "10px system-ui, sans-serif";
  context.lineWidth = 1;
  context.strokeStyle = "#26364b";
  context.fillStyle = "#8193ac";

  for (let i = 0; i <= 3; i++) {
    const y = top + (plotHeight / 3) * i;
    context.beginPath();
    context.moveTo(left, y);
    context.lineTo(width - right, y);
    context.stroke();

    const value = max - ((max - min) / 3) * i;
    context.fillText(`${value.toFixed(0)}`, 5, y + 3);
  }

  const coords = values.map((value, index) => ({
    x: left + (points.length === 1
      ? plotWidth / 2
      : (index / (points.length - 1)) * plotWidth),
    y: bottom - ((value - min) / (max - min)) * plotHeight,
  }));

  if (coords.length > 1) {
    const gradient = context.createLinearGradient(0, top, 0, bottom);
    gradient.addColorStop(0, "rgba(76, 224, 196, 0.20)");
    gradient.addColorStop(1, "rgba(76, 224, 196, 0.00)");

    context.beginPath();
    context.moveTo(coords[0].x, bottom);
    for (const point of coords) context.lineTo(point.x, point.y);
    context.lineTo(coords[coords.length - 1].x, bottom);
    context.closePath();
    context.fillStyle = gradient;
    context.fill();
  }

  context.beginPath();
  coords.forEach((point, index) => {
    if (index === 0) context.moveTo(point.x, point.y);
    else context.lineTo(point.x, point.y);
  });
  context.strokeStyle = "#4ce0c4";
  context.lineWidth = 2;
  context.lineJoin = "round";
  context.lineCap = "round";
  context.stroke();

  if (coords.length === 1) {
    context.beginPath();
    context.arc(coords[0].x, coords[0].y, 3, 0, Math.PI * 2);
    context.fillStyle = "#4ce0c4";
    context.fill();
  }

  context.fillStyle = "#8193ac";
  context.font = "10px system-ui, sans-serif";
  context.textAlign = "left";
  context.fillText(formatClock(points[0].timestamp), left, height - 7);
  context.textAlign = "right";
  context.fillText(formatClock(points[points.length - 1].timestamp), width - right, height - 7);
  context.textAlign = "left";
}

function renderOutages(payload) {
  const items = Array.isArray(payload.items) ? payload.items : [];
  const list = $("outage-list");
  list.replaceChildren();
  $("outage-count").textContent = `${items.length} record${items.length === 1 ? "" : "s"}`;

  if (!items.length) {
    list.append(element("div", "loading-row", "No outages have been recorded."));
    return;
  }

  for (const outage of items.slice(0, 6)) {
    const row = element("div", "outage-item");
    const resolved = Boolean(outage.is_resolved);
    const marker = element(
      "span", `outage-marker${resolved ? " resolved" : ""}`,
      resolved ? "✓" : "!"
    );
    const copy = element("div", "outage-copy");
    const title = element(
      "div", "outage-title",
      `${outage.type || "Network"} outage`
    );
    const meta = element(
      "div", "outage-meta",
      `${formatDateTime(outage.start_time)}${outage.end_time ? ` · Recovered ${formatClock(outage.end_time)}` : " · Still unresolved"}`
    );
    copy.append(title, meta);

    const side = element("div", "outage-end");
    side.append(element("div", "outage-duration", formatDuration(outage.duration_seconds)));
    const state = element(
      "div", "outage-state status-chip " + (resolved ? "chip-success" : "chip-warning"),
      resolved ? "Resolved" : "Active"
    );
    side.append(state);

    row.append(marker, copy, side);
    list.append(row);
  }
}


function renderServices(payload) {
  const items = Array.isArray(payload.items) ? payload.items : [];
  const root = $("service-list");
  root.replaceChildren();

  $("service-count").textContent =
    `${items.length} service${items.length === 1 ? "" : "s"}`;

  if (!items.length) {
    root.append(element(
      "div",
      "service-empty",
      "No HTTP services are configured. Add SERVICE_URLS to your local .env and restart the monitor."
    ));
    return;
  }

  for (const service of items) {
    const card = element("article", "service-card");
    const top = element("div", "service-card-top");
    const url = element("strong", "service-url", service.service_url);
    top.append(url, makeChip(service.status || "pending"));

    const metrics = element("div", "service-metrics");
    const statusDetail = service.http_status_code
      ? `HTTP ${service.http_status_code}`
      : service.status === "online"
        ? "Successful response"
        : service.status === "pending"
          ? "Waiting for scheduled check"
          : "No HTTP response";
    metrics.append(element("span", "", statusDetail));
    if (service.response_time_ms !== null && service.response_time_ms !== undefined) {
      metrics.append(element("span", "", `${formatLatency(service.response_time_ms)} response time`));
    }

    const metaText = service.timestamp
      ? `Last checked ${formatDateTime(service.timestamp)}`
      : "No check has been recorded yet";
    card.append(top, metrics, element("small", "service-meta", metaText));

    if (service.error_message) {
      card.append(element("small", "service-error", service.error_message));
    }

    root.append(card);
  }
}

function renderServiceOutages(payload) {
  const items = Array.isArray(payload.items) ? payload.items : [];
  const root = $("service-outage-list");
  root.replaceChildren();
  $("service-incident-count").textContent =
    `${items.length} incident${items.length === 1 ? "" : "s"}`;

  if (!items.length) {
    root.append(element("div", "loading-row", "No confirmed service incidents recorded."));
    return;
  }

  for (const incident of items.slice(0, 5)) {
    const row = element("div", "service-incident");
    const marker = element(
      "span",
      `outage-marker${incident.is_resolved ? " resolved" : ""}`,
      incident.is_resolved ? "✓" : "!"
    );
    const copy = element("div", "service-incident-copy");
    copy.append(
      element("strong", "service-incident-url", incident.service_url),
      element(
        "small",
        "service-meta",
        `${formatDateTime(incident.start_time)}${incident.end_time ? ` · Recovered ${formatClock(incident.end_time)}` : " · Still unresolved"}`
      )
    );
    const side = element("div", "service-incident-side");
    side.append(
      element("strong", "outage-duration", formatDuration(incident.duration_seconds)),
      element(
        "span",
        `status-chip ${incident.is_resolved ? "chip-success" : "chip-warning"}`,
        incident.is_resolved ? "Recovered" : "Active"
      )
    );
    row.append(marker, copy, side);
    root.append(row);
  }
}


function renderNetworkQuality(payload) {
  const items = Array.isArray(payload.items) ? payload.items : [];
  const root = $("quality-list");
  root.replaceChildren();
  $("quality-target-count").textContent =
    `${items.length} target${items.length === 1 ? "" : "s"}`;

  if (!items.length) {
    root.append(element("div", "service-empty", "No network targets are configured."));
    return;
  }

  for (const item of items) {
    const card = element("article", "quality-card");
    const top = element("div", "quality-card-top");
    top.append(
      element("strong", "quality-target", item.target),
      makeChip(item.status || "pending")
    );

    const metrics = element("div", "quality-metrics");
    const loss = item.packet_loss_percent;
    const sent = item.packets_sent;
    const received = item.packets_received;
    const lossText = loss === null || loss === undefined
      ? "Packet loss unavailable"
      : `${Number(loss).toFixed(1)}% loss · ${received}/${sent} replies`;
    metrics.append(element("span", "", lossText));
    metrics.append(element(
      "span", "",
      `Avg latency ${formatLatency(item.latency_avg_ms)}`
    ));
    metrics.append(element(
      "span", "",
      `Jitter ${formatLatency(item.latency_jitter_ms)}`
    ));

    card.append(top, metrics);
    card.append(element(
      "small", "service-meta",
      item.timestamp ? `Last sample ${formatDateTime(item.timestamp)}` : "Waiting for first sample"
    ));
    if (item.error_message) card.append(element("small", "service-error", item.error_message));
    root.append(card);
  }
}

function renderQualityIncidents(payload) {
  const items = Array.isArray(payload.items) ? payload.items : [];
  const root = $("quality-incident-list");
  root.replaceChildren();
  $("quality-incident-count").textContent =
    `${items.length} incident${items.length === 1 ? "" : "s"}`;

  if (!items.length) {
    root.append(element("div", "loading-row", "No sustained quality incidents recorded."));
    return;
  }

  for (const incident of items.slice(0, 5)) {
    const row = element("div", "service-incident");
    row.append(element(
      "span",
      `outage-marker${incident.is_resolved ? " resolved" : ""}`,
      incident.is_resolved ? "✓" : "!"
    ));
    const copy = element("div", "service-incident-copy");
    const details = [
      incident.peak_packet_loss_percent !== null && incident.peak_packet_loss_percent !== undefined
        ? `Peak loss ${Number(incident.peak_packet_loss_percent).toFixed(1)}%`
        : null,
      incident.peak_latency_ms !== null && incident.peak_latency_ms !== undefined
        ? `Peak average latency ${formatLatency(incident.peak_latency_ms)}`
        : null,
    ].filter(Boolean).join(" · ");
    copy.append(
      element("strong", "service-incident-url", incident.target),
      element(
        "small", "service-meta",
        `${formatDateTime(incident.start_time)}${incident.end_time ? ` · Recovered ${formatClock(incident.end_time)}` : " · Still unresolved"}`
      ),
      element("small", "service-meta", details || "Quality threshold exceeded")
    );
    const side = element("div", "service-incident-side");
    side.append(
      element("strong", "outage-duration", formatDuration(incident.duration_seconds)),
      element(
        "span",
        `status-chip ${incident.is_resolved ? "chip-success" : "chip-warning"}`,
        incident.is_resolved ? "Recovered" : "Active"
      )
    );
    row.append(copy, side);
    root.append(row);
  }
}


function renderReliabilityReport(payload) {
  const root = $("reliability-summary");
  root.replaceChildren();

  const network = payload.network || {};
  const services = payload.services || {};
  const quality = payload.network_quality || {};
  const serviceItems = Array.isArray(services.items) ? services.items : [];
  const successes = serviceItems.reduce(
    (sum, item) => sum + Number(item.successful_checks || 0), 0
  );
  const failures = serviceItems.reduce(
    (sum, item) => sum + Number(item.failed_checks || 0), 0
  );
  const attempts = successes + failures;
  const serviceSuccessRate = attempts
    ? `${(100 * successes / attempts).toFixed(1)}%`
    : "No samples";
  const qualityItems = Array.isArray(quality.items) ? quality.items : [];
  const degradedSamples = qualityItems.reduce(
    (sum, item) => sum + Number(item.degraded_samples || 0), 0
  );
  const serviceIncidents = services.incidents || {};
  const qualityIncidents = quality.incidents || {};
  const networkIncidents = network.outages || {};
  const totalIncidents =
    Number(networkIncidents.count || 0) +
    Number(serviceIncidents.count || 0) +
    Number(qualityIncidents.count || 0);

  const cards = [
    {
      label: "OBSERVED NETWORK UPTIME",
      value: network.uptime_percentage === null || network.uptime_percentage === undefined
        ? "No data"
        : `${Number(network.uptime_percentage).toFixed(2)}%`,
      note: `Measured coverage ${Number(network.measurement_coverage_percentage || 0).toFixed(1)}% · unmonitored gaps excluded`,
    },
    {
      label: "SERVICE CHECK SUCCESS RATE",
      value: serviceSuccessRate,
      note: `${successes} successful / ${attempts} completed checks · sample-based, not time-based uptime`,
    },
    {
      label: "DEGRADED QUALITY SAMPLES",
      value: `${degradedSamples} / ${Number(quality.sample_count || 0)}`,
      note: `${Number(qualityIncidents.count || 0)} sustained quality incident(s) in the window`,
    },
    {
      label: "CONFIRMED INCIDENTS",
      value: String(totalIncidents),
      note: `${Number(networkIncidents.count || 0)} internet · ${Number(serviceIncidents.count || 0)} service · ${Number(qualityIncidents.count || 0)} quality`,
    },
  ];

  for (const item of cards) {
    const card = element("article", "reliability-card");
    card.append(
      element("span", "reliability-label", item.label),
      element("strong", "reliability-value", item.value),
      element("small", "reliability-note", item.note)
    );
    root.append(card);
  }
}


function renderStatistics(payload) {
  const hours = Number(payload.window_hours) || 24;
  const uptime = payload.uptime_percentage;

  $("chart-range").textContent = uptime === null || uptime === undefined
    ? `Uptime unavailable · ${hours}h`
    : `${Number(uptime).toFixed(2)}% observed uptime · ${hours}h`;

  const latency = payload.latency || {};
  $("avg-latency").textContent = formatLatency(latency.average_ms);

  if (latency.sample_count > 0) {
    $("latency-detail").textContent =
      `${latency.sample_count} samples · min ${formatLatency(latency.minimum_ms)} · max ${formatLatency(latency.maximum_ms)}`;
  } else {
    $("latency-detail").textContent =
      "No successful latency samples in this period";
  }

  const measured = Number(payload.measurement_coverage_percentage);
  const known = Number(payload.known_status_coverage_percentage);

  $("stats-coverage").textContent =
    `Measured ${Number.isFinite(measured) ? measured.toFixed(1) : "0.0"}% · known state ${Number.isFinite(known) ? known.toFixed(1) : "0.0"}%`;
}


function renderDiagnosis(payload) {
  const root = $("diagnosis-result");
  root.replaceChildren();

  const diagnosis = payload.diagnosis || {};
  root.append(
    element("h3", "diagnosis-title", diagnosis.title || "Diagnosis complete"),
    element("p", "diagnosis-summary", diagnosis.summary || "No summary is available."),
    element("p", "diagnosis-next", `Recommended next step: ${diagnosis.next_step || "Review the check details and try again."}`)
  );

  appendDiagnosisGroup(root, "Gateway and public targets", [
    { label: "Local gateway", probe: payload.gateway || {} },
    ...(payload.external_targets || []).map((probe) => ({
      label: probe.target || "Public target",
      probe,
    })),
  ]);

  appendDiagnosisGroup(root, "DNS resolution", (payload.dns_checks || []).map((probe) => ({
    label: probe.host || "DNS hostname",
    probe,
    kind: "dns",
  })));

  appendDiagnosisGroup(root, "Configured HTTP services", (payload.service_checks || []).map((probe) => ({
    label: probe.url || "HTTP service",
    probe,
    kind: "http",
  })));

  root.append(element("p", "diagnosis-note", payload.note || "These checks are clues, not proof of root cause."));
}

function appendDiagnosisGroup(root, title, items) {
  if (!items.length) return;
  root.append(element("h4", "diagnosis-group-title", title));
  const grid = element("div", "diagnosis-probes");
  for (const item of items) {
    grid.append(makeProbeCard(item.label, item.probe || {}, item.kind));
  }
  root.append(grid);
}

function makeProbeCard(label, probe, kind) {
  const card = element("div", "diagnosis-probe");
  card.append(
    element("strong", "", label || "Target"),
    makeChip(probe.status || "error")
  );

  let detail = probe.error_message || "No additional details";
  if (kind === "dns" && probe.status === "resolved") {
    detail = `${probe.address_count} address(es) resolved`;
  } else if (kind === "http" && probe.http_status_code !== null && probe.http_status_code !== undefined) {
    detail = `HTTP ${probe.http_status_code}`;
  } else if (probe.latency_ms !== null && probe.latency_ms !== undefined) {
    detail = formatLatency(probe.latency_ms);
  }

  card.append(element("small", "", detail));
  return card;
}

async function runDiagnosis() {
  const button = $("diagnose-button");
  const root = $("diagnosis-result");
  button.disabled = true;
  button.textContent = "Checking…";
  root.replaceChildren(element("p", "diagnosis-placeholder", "Checking gateway, public targets, DNS and configured HTTP services…"));
  try {
    const result = await getJson("/api/diagnose");
    renderDiagnosis(result);
  } catch (error) {
    console.error("Connectivity diagnosis failed:", error);
    root.replaceChildren(element("p", "diagnosis-error", "Diagnosis could not run. Check the server terminal and try again."));
  } finally {
    button.disabled = false;
    button.textContent = "Run diagnosis";
  }
}

async function refreshDashboard() {
  const button = $("refresh-button");
  const icon = $("refresh-icon");

  button.disabled = true;
  icon.classList.add("spinning");

  try {
    const [
      status, history, outages, statistics, services, serviceOutages,
      quality, qualityIncidents, reliability,
    ] = await Promise.all([
      getJson("/api/status"),
      getJson("/api/history?limit=90"),
      getJson("/api/outages?limit=10"),
      getJson("/api/statistics?hours=24"),
      getJson("/api/services"),
      getJson("/api/service-outages?limit=10"),
      getJson("/api/quality"),
      getJson("/api/quality-incidents?limit=10"),
      getJson("/api/reports/reliability?hours=24"),
    ]);

    renderStatus(status);
    renderHistory(history);
    renderOutages(outages);
    renderStatistics(statistics);
    renderServices(services);
    renderServiceOutages(serviceOutages);
    renderNetworkQuality(quality);
    renderQualityIncidents(qualityIncidents);
    renderReliabilityReport(reliability);
    $("last-updated").textContent =
      `Updated ${new Date().toLocaleTimeString([], {
        hour: "2-digit", minute: "2-digit", second: "2-digit"
      })}`;
  } catch (error) {
    console.error("Dashboard refresh failed:", error);
    $("status-kicker").textContent = "DATA CONNECTION ERROR";
    $("overall-title").textContent = "Cannot load monitoring data";
    $("overall-message").textContent =
      "Check that the EthioNet Pulse server is running, then refresh.";
    $("connection-banner").className = "status-banner status-unknown";
    $("status-icon").textContent = "!";
    $("last-updated").textContent = "Refresh failed";
  } finally {
    button.disabled = false;
    icon.classList.remove("spinning");
  }
}

$("refresh-button").addEventListener("click", refreshDashboard);
$("diagnose-button").addEventListener("click", runDiagnosis);
window.addEventListener("resize", () => {
  // Refreshing redraws the chart using its new container dimensions.
  refreshDashboard();
});

refreshDashboard();
window.setInterval(refreshDashboard, 30_000);
