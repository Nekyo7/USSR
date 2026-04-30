const API_BASE_CANDIDATES = [
  `${window.location.origin}/api`,
  "http://127.0.0.1:5001/api",
  "http://127.0.0.1:5000/api"
];

const state = {
  apiBase: null,
  history: [],
  latestPacket: null,
  latestAnalysis: null,
  source: "Idle",
  eventSource: null,
  serialPort: null,
  serialReader: null,
  lastPacketAt: 0,
  lastPacketSignature: "",
  currentMode: "PATROL"
};

const ui = {
  sourceLabel: document.getElementById("sourceLabel"),
  packetAge: document.getElementById("packetAge"),
  missionState: document.getElementById("missionState"),
  confidenceScore: document.getElementById("confidenceScore"),
  unitLabel: document.getElementById("unitLabel"),
  powerReadiness: document.getElementById("powerReadiness"),
  powerReadinessNote: document.getElementById("powerReadinessNote"),
  threatIndex: document.getElementById("threatIndex"),
  threatNote: document.getElementById("threatNote"),
  resilienceWindow: document.getElementById("resilienceWindow"),
  resilienceNote: document.getElementById("resilienceNote"),
  signalIntegrity: document.getElementById("signalIntegrity"),
  signalNote: document.getElementById("signalNote"),
  riskFactors: document.getElementById("riskFactors"),
  mlModelGrid: document.getElementById("mlModelGrid"),
  telemetryGrid: document.getElementById("telemetryGrid"),
  anomalyList: document.getElementById("anomalyList"),
  actionFeed: document.getElementById("actionFeed"),
  connectSerialBtn: document.getElementById("connectSerialBtn"),
  connectDemoBtn: document.getElementById("connectDemoBtn"),
  disconnectBtn: document.getElementById("disconnectBtn"),
  trendCanvas: document.getElementById("trendCanvas"),
  faultList: document.getElementById("faultList"),
  relayScheduleList: document.getElementById("relayScheduleList"),
  mqttSchemaList: document.getElementById("mqttSchemaList"),
  simOverlayList: document.getElementById("simOverlayList"),
  modeButtons: Array.from(document.querySelectorAll("[data-mode]")),
  sectionTabs: Array.from(document.querySelectorAll("[data-section]")),
  sectionPages: Array.from(document.querySelectorAll("[data-page]")),
  activeModeLabel: document.getElementById("activeModeLabel"),
  recommendedModeLabel: document.getElementById("recommendedModeLabel"),
  panelGrid: document.getElementById("panelGrid"),
  threatRadarCanvas: document.getElementById("threatRadarCanvas"),
  relayTimelineCanvas: document.getElementById("relayTimelineCanvas"),
  riskHeatmapCanvas: document.getElementById("riskHeatmapCanvas"),
  geoIntelCanvas: document.getElementById("geoIntelCanvas"),
  operationalTrace: document.getElementById("operationalTrace"),
  faultTrace: document.getElementById("faultTrace"),
  modelConfidenceGrid: document.getElementById("modelConfidenceGrid")
};

ui.connectDemoBtn.addEventListener("click", connectDemoStream);
ui.connectSerialBtn.addEventListener("click", connectSerial);
ui.disconnectBtn.addEventListener("click", disconnectAll);
ui.modeButtons.forEach((button) => {
  button.addEventListener("click", () => setMode(button.dataset.mode));
});
ui.sectionTabs.forEach((button) => {
  button.addEventListener("click", () => setSection(button.dataset.section));
});

boot();

setInterval(() => {
  if (state.latestAnalysis?.stealthRelaySchedule) {
    drawRelayTimeline(state.latestAnalysis.stealthRelaySchedule);
  }
}, 1000);

async function boot() {
  state.apiBase = await resolveApiBase();
  await refreshSystemState();
  await loadMqttSchema();
  renderModeButtons();
  await connectBackendSerialStream({ silent: true });
}

setInterval(() => {
  if (!state.lastPacketAt) {
    ui.packetAge.textContent = "No data";
    return;
  }
  const seconds = Math.max(0, Math.round((Date.now() - state.lastPacketAt) / 1000));
  ui.packetAge.textContent = `${seconds}s ago`;
}, 1000);

setInterval(() => {
  if (state.source === "Flask Serial") {
    pollLatestTelemetry();
  }
}, 1000);

async function resolveApiBase() {
  for (const base of API_BASE_CANDIDATES) {
    try {
      const [health, systemState, mqttSchema] = await Promise.all([
        fetch(`${base}/health`),
        fetch(`${base}/system-state`),
        fetch(`${base}/mqtt-schema`)
      ]);
      if (health.ok && systemState.ok && mqttSchema.ok) {
        return base;
      }
    } catch (error) {
      console.debug("API base probe failed", base, error);
    }
  }
  return API_BASE_CANDIDATES[API_BASE_CANDIDATES.length - 1];
}

async function refreshSystemState() {
  try {
    const response = await fetch(`${state.apiBase}/system-state`);
    const data = await response.json();
    state.currentMode = data.mode;
    ui.activeModeLabel.textContent = data.mode;
    renderModeButtons();
  } catch (error) {
    console.error("Failed to load system state", error);
  }
}

async function loadMqttSchema() {
  try {
    const response = await fetch(`${state.apiBase}/mqtt-schema`);
    const data = await response.json();
    ui.mqttSchemaList.innerHTML = data.topics.map((topic) => `
      <article class="metric-item">
        <span>${topic.direction}</span>
        <strong>${topic.topic}</strong>
        <span>QoS ${topic.qos} | ${topic.payload_fields.join(", ")}</span>
      </article>
    `).join("");
  } catch (error) {
    ui.mqttSchemaList.innerHTML = `<article class="event-item"><div><strong>MQTT schema unavailable</strong><span>${error.message}</span></div></article>`;
  }
}

async function setMode(mode) {
  try {
    const response = await fetch(`${state.apiBase}/mode`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode, reason: "dashboard_mode_switch" })
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || "Mode switch failed");
    }
    state.currentMode = data.mode;
    ui.activeModeLabel.textContent = data.mode;
    renderModeButtons();
  } catch (error) {
    console.error("Mode switch failed", error);
  }
}

function renderModeButtons() {
  ui.modeButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.mode === state.currentMode);
  });
}

function setSection(section) {
  ui.sectionTabs.forEach((button) => {
    button.classList.toggle("active", button.dataset.section === section);
  });
  ui.sectionPages.forEach((page) => {
    page.classList.toggle("active", page.dataset.page === section);
  });
}

async function connectDemoStream() {
  await disconnectAll();
  state.source = "Demo SSE";
  ui.sourceLabel.textContent = state.source;
  const eventSource = new EventSource(`${state.apiBase}/demo-stream`);
  state.eventSource = eventSource;
  eventSource.onmessage = (event) => {
    const payload = JSON.parse(event.data);
    handleEnvelope(payload);
  };
}

async function connectSerial() {
  const connectedToBackend = await connectBackendSerialStream();
  if (connectedToBackend) {
    return;
  }

  await connectBrowserSerial();
}

async function connectBackendSerialStream(options = {}) {
  try {
    const statusResponse = await fetch(`${state.apiBase}/serial-status`);
    if (!statusResponse.ok) {
      return false;
    }

    await disconnectAll();
    state.source = "Flask Serial";
    ui.sourceLabel.textContent = options.silent ? "Waiting for serial" : state.source;

    const eventSource = new EventSource(`${state.apiBase}/serial-stream`);
    state.eventSource = eventSource;
    eventSource.onmessage = (event) => {
      const payload = JSON.parse(event.data);
      handleEnvelope(payload);
    };
    eventSource.addEventListener("status", (event) => {
      const status = JSON.parse(event.data);
      ui.sourceLabel.textContent = status.connected
        ? `Flask Serial ${status.port}`
        : `Waiting for ${status.port}`;
    });
    eventSource.onerror = () => {
      ui.sourceLabel.textContent = "Flask serial unavailable";
    };
    return true;
  } catch (error) {
    console.debug("Backend serial stream unavailable, trying browser serial", error);
    return false;
  }
}

async function pollLatestTelemetry() {
  try {
    const response = await fetch(`${state.apiBase}/telemetry`);
    if (!response.ok) {
      return;
    }
    const envelope = await response.json();
    handleEnvelope(envelope);
  } catch (error) {
    console.debug("Latest telemetry poll failed", error);
  }
}

async function connectBrowserSerial() {
  if (!("serial" in navigator)) {
    alert("Web Serial is not supported in this browser. Use Chrome or Edge for live Arduino mode.");
    return;
  }

  await disconnectAll();

  try {
    const port = await navigator.serial.requestPort();
    await port.open({ baudRate: 115200 });
    state.serialPort = port;
    state.source = "Arduino Serial";
    ui.sourceLabel.textContent = state.source;

    const decoder = new TextDecoderStream();
    port.readable.pipeTo(decoder.writable).catch(() => {});
    const reader = decoder.readable.getReader();
    state.serialReader = reader;

    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += value;
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines) {
        const clean = line.trim();
        if (!clean) continue;
        try {
          const packet = JSON.parse(clean);
          const envelope = await analyzePacket(packet);
          handleEnvelope(envelope);
        } catch (error) {
          console.warn("Skipped malformed serial line", clean, error);
        }
      }
    }
  } catch (error) {
    console.error("Serial connection failed:", error);
    ui.sourceLabel.textContent = "Serial unavailable";
  }
}

async function analyzePacket(packet) {
  const response = await fetch(`${state.apiBase}/telemetry`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(packet)
  });
  return response.json();
}

async function disconnectAll() {
  if (state.eventSource) {
    state.eventSource.close();
    state.eventSource = null;
  }
  if (state.serialReader) {
    try {
      await state.serialReader.cancel();
    } catch (error) {
      console.debug("Reader cancel ignored", error);
    }
    state.serialReader = null;
  }
  if (state.serialPort) {
    try {
      await state.serialPort.close();
    } catch (error) {
      console.debug("Port close ignored", error);
    }
    state.serialPort = null;
  }
  state.source = "Idle";
  ui.sourceLabel.textContent = state.source;
  state.lastPacketSignature = "";
}

function handleEnvelope(envelope) {
  const packet = envelope.packet;
  const analysis = envelope.analysis;
  const system = envelope.system;

  if (!packet || !analysis || !system) {
    return;
  }

  const packetSignature = JSON.stringify(packet);
  if (packetSignature === state.lastPacketSignature) {
    return;
  }
  state.lastPacketSignature = packetSignature;

  state.latestPacket = packet;
  state.latestAnalysis = analysis;
  state.lastPacketAt = Date.now();
  state.currentMode = system.mode;
  if (state.source === "Flask Serial") {
    ui.sourceLabel.textContent = "Flask Serial";
  }
  state.history.push(packet);
  if (state.history.length > 120) {
    state.history.shift();
  }

  ui.activeModeLabel.textContent = system.mode;
  ui.recommendedModeLabel.textContent = analysis.modeControl.recommendedMode;
  renderModeButtons();
  render(packet, analysis);
}

function render(packet, analysis) {
  const visibilityIndex = clamp(Math.round((Number(packet.ambientLight ?? 0) / 1023) * 100), 0, 100);

  ui.unitLabel.textContent = `${packet.unitId ?? "UNKNOWN"} | ${packet.mode ?? "UNSPECIFIED"}`;
  ui.missionState.textContent = analysis.operationalModel.predictedState;
  ui.confidenceScore.textContent = `${analysis.confidence}%`;

  ui.powerReadiness.textContent = analysis.powerReadiness;
  ui.powerReadinessNote.textContent = `${packet.battPct ?? 0}% battery | ${Number(packet.loadW ?? 0).toFixed(1)}W live load`;
  ui.threatIndex.textContent = analysis.threatIndex;
  ui.threatNote.textContent = `Decision tree fault class: ${analysis.faultDetection.faultClass}`;
  ui.signalIntegrity.textContent = visibilityIndex;
  ui.signalNote.textContent = `${packet.ambientLight ?? 0} ambient light units`;
  ui.resilienceWindow.textContent = analysis.batteryForecastMinutes ? `${analysis.batteryForecastMinutes}m` : "Stable";
  ui.resilienceNote.textContent = analysis.batteryForecastMinutes
    ? "Projected time until 20% battery"
    : "Battery trend currently flat";

  renderRiskFactors(packet, analysis);
  renderMlModels(analysis);
  renderTelemetry(packet);
  renderEvents(ui.anomalyList, analysis.anomalies.map((item) => ({
    title: item.name,
    detail: item.description,
    level: item.severity > 75 ? "high" : item.severity > 50 ? "medium" : "low"
  })), "No anomalies detected yet.");
  renderEvents(ui.actionFeed, analysis.actions, "No guidance generated yet.");
  renderFaults(analysis.faultDetection);
  renderRelaySchedule(analysis.stealthRelaySchedule);
  renderPanelGrid(analysis.dashboardPanels);
  renderDecisionTrace(ui.operationalTrace, analysis.operationalModel.treeTrace);
  renderDecisionTrace(ui.faultTrace, analysis.faultDetection.treeTrace);
  renderModelConfidence(analysis);
  drawTrendChart(state.history);
  drawThreatRadar(packet, analysis);
  drawRelayTimeline(analysis.stealthRelaySchedule);
  drawRiskHeatmap(analysis.riskHeatmap);
  drawGeoIntel(analysis.geoIntel);
  renderSimulationOverlay(packet);
}

function renderRiskFactors(packet, analysis) {
  const items = [
    { label: "Thermal Stress", value: `${Number(packet.tempC ?? 0).toFixed(1)} C`, score: clamp((packet.tempC - 30) * 6, 0, 100) },
    { label: "Power Draw", value: `${Number(packet.currentA ?? 0).toFixed(2)} A`, score: clamp((packet.currentA - 1.5) * 35, 0, 100) },
    { label: "Ambient Light", value: `${packet.ambientLight ?? 0}`, score: clamp((260 - Number(packet.ambientLight ?? 1023)) / 2.6, 0, 100) },
    { label: "PIR Activity", value: Number(packet.motionDetected ?? 0) ? "Detected" : "Clear", score: Number(packet.motionDetected ?? 0) ? 85 : 20 },
    { label: "Fault Severity", value: analysis.faultDetection.faultClass, score: analysis.faultDetection.severity === "high" ? 90 : analysis.faultDetection.severity === "medium" ? 60 : 25 }
  ];

  ui.riskFactors.innerHTML = items.map((item) => `
    <article class="metric-item">
      <span>${item.label}</span>
      <strong>${item.value}</strong>
      <span>Risk score ${Math.round(item.score)}/100</span>
    </article>
  `).join("");
}

function renderMlModels(analysis) {
  const items = [
    {
      model: "Operational Decision Tree",
      output: analysis.operationalModel.predictedState,
      algorithm: "Decision tree | synthetic random training",
      note: analysis.operationalModel.treeTrace.slice(0, 2).join(" | ")
    },
    {
      model: "Fault Decision Tree",
      output: analysis.faultDetection.faultClass,
      algorithm: "Decision tree | synthetic random training",
      note: analysis.faultDetection.treeTrace.slice(0, 2).join(" | ")
    },
    {
      model: "Battery Forecaster",
      output: analysis.batteryForecastMinutes ? `${analysis.batteryForecastMinutes}m to 20%` : "Flat discharge trend",
      algorithm: "Linear regression",
      note: "Recent battery slope estimate"
    },
    {
      model: "Anomaly Detector",
      output: analysis.anomalies.length ? `${analysis.anomalies[0].name} anomaly` : "Nominal baseline",
      algorithm: "Rolling z-score",
      note: `${analysis.anomalies.length} active anomalies`
    },
    {
      model: "Night Watch Heuristic",
      output: Number(state.latestPacket?.motionDetected ?? 0) && Number(state.latestPacket?.ambientLight ?? 1023) < 220 ? "Triggered" : "Idle",
      algorithm: "PIR + low-light fusion",
      note: "Low-visibility intrusion cue"
    }
  ];

  ui.mlModelGrid.innerHTML = items.map((item) => `
    <article class="metric-item">
      <span>${item.model}</span>
      <strong>${item.output}</strong>
      <span>${item.algorithm} | ${item.note}</span>
    </article>
  `).join("");
}

function renderTelemetry(packet) {
  const fields = [
    ["Battery", `${packet.battV ?? "--"} V`],
    ["Battery %", `${packet.battPct ?? "--"} %`],
    ["Load", `${packet.loadW ?? "--"} W`],
    ["Temperature", `${packet.tempC ?? "--"} C`],
    ["Humidity", `${packet.humidity ?? "--"} %`],
    ["Current", `${packet.currentA ?? "--"} A`],
    ["PIR Motion", `${Number(packet.motionDetected ?? 0) ? "Detected" : "Clear"}`],
    ["Ambient Light", `${packet.ambientLight ?? "--"}`],
    ["Power Rail", `${classifyVoltageBand(Number(packet.battV ?? 0))}`]
  ];

  ui.telemetryGrid.innerHTML = fields.map(([label, value]) => `
    <article class="telemetry-item">
      <span>${label}</span>
      <strong>${value}</strong>
    </article>
  `).join("");
}

function renderSimulationOverlay(packet) {
  const simItems = [];
  if (packet.simSolarW !== undefined) {
    simItems.push(["Simulated Solar", `${packet.simSolarW} W`, "Scenario-only future solar input"]);
  }
  if (packet.simSmokePpm !== undefined) {
    simItems.push(["Simulated Smoke", `${packet.simSmokePpm} ppm`, "Scenario-only future smoke input"]);
  }

  if (!simItems.length) {
    ui.simOverlayList.innerHTML = `<article class="event-item"><div><strong>No simulation overlay active</strong><span>Live hardware only on this packet.</span></div></article>`;
    return;
  }

  ui.simOverlayList.innerHTML = simItems.map(([label, value, note]) => `
    <article class="metric-item">
      <span>${label}</span>
      <strong>${value}</strong>
      <span>${note}</span>
    </article>
  `).join("");
}

function renderFaults(faultDetection) {
  renderEvents(ui.faultList, faultDetection.activeFlags.map((flag) => ({
    title: flag,
    detail: `Fault class ${faultDetection.faultClass} | severity ${faultDetection.severity}`,
    level: faultDetection.severity
  })), "No active fault flags.");
}

function renderRelaySchedule(schedule) {
  ui.relayScheduleList.innerHTML = schedule.relayWindows.map((relay) => `
    <article class="metric-item">
      <span>${relay.relay}</span>
      <strong>${relay.onSec}s ON / ${relay.offSec}s OFF</strong>
      <span>${relay.state} now | cycle ${relay.cycleSec}s | pressure ${Math.round((schedule.adaptivePressure || 0) * 100)}%</span>
    </article>
  `).join("");
}

function renderPanelGrid(panels) {
  ui.panelGrid.innerHTML = panels.map((panel) => `
    <article class="metric-item">
      <span>${panel.title}</span>
      <strong>${panel.value}</strong>
      <span>${panel.detail}</span>
    </article>
  `).join("");
}

function renderDecisionTrace(container, trace) {
  container.innerHTML = trace.map((step, index) => `
    <article class="trace-step">
      <strong>Step ${index + 1}</strong>
      <span>${step}</span>
    </article>
  `).join("");
}

function renderModelConfidence(analysis) {
  const groups = [
    {
      title: "Operational State",
      values: analysis.operationalModel.probabilities || {}
    },
    {
      title: "Fault Class",
      values: analysis.faultProbabilities || {}
    }
  ];

  ui.modelConfidenceGrid.innerHTML = groups.map((group) => `
    <article class="confidence-card">
      <span>${group.title}</span>
      ${Object.entries(group.values).map(([label, value]) => `
        <div class="confidence-row">
          <label><span>${label}</span><span>${value}%</span></label>
          <div class="confidence-bar"><i style="width:${value}%"></i></div>
        </div>
      `).join("")}
    </article>
  `).join("");
}

function renderEvents(container, items, emptyText) {
  if (!items.length) {
    container.innerHTML = `<article class="event-item"><div><strong>${emptyText}</strong></div></article>`;
    return;
  }

  container.innerHTML = items.map((item) => `
    <article class="event-item">
      <div>
        <strong>${item.title}</strong>
        <span>${item.detail}</span>
      </div>
      <div class="event-tag ${item.level}">${item.level.toUpperCase()}</div>
    </article>
  `).join("");
}

function drawTrendChart(history) {
  const canvas = ui.trendCanvas;
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);

  ctx.strokeStyle = "rgba(255,255,255,0.07)";
  ctx.lineWidth = 1;
  for (let i = 1; i < 5; i += 1) {
    const y = (height / 5) * i;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(width, y);
    ctx.stroke();
  }

  drawSeries(ctx, history.map((sample) => Number(sample.battPct ?? 0)), width, height, "#9cff6b", 100);
  drawSeries(ctx, history.map((sample) => Number(sample.loadW ?? 0) * 2), width, height, "#ffb14d", 100);
  drawSeries(ctx, history.map((sample) => clamp((Number(sample.ambientLight ?? 0) / 1023) * 100, 0, 100)), width, height, "#ff7a59", 100);
}

function drawThreatRadar(packet, analysis) {
  const canvas = ui.threatRadarCanvas;
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  const cx = width / 2;
  const cy = height / 2;
  const radius = Math.min(width, height) * 0.34;
  const metrics = [
    { label: "Power", value: clamp(100 - Number(packet.battPct ?? 0), 0, 100), color: "#9cff6b" },
    { label: "Thermal", value: clamp((Number(packet.tempC ?? 0) - 30) * 6, 0, 100), color: "#ff7a59" },
    { label: "Humidity", value: clamp((Number(packet.humidity ?? 0) - 40) * 2, 0, 100), color: "#ffcc66" },
    { label: "Motion", value: Number(packet.motionDetected ?? 0) ? 85 : 15, color: "#ff8b68" },
    { label: "Light", value: clamp((260 - Number(packet.ambientLight ?? 1023)) / 2.6, 0, 100), color: "#ffd66e" },
    { label: "Threat", value: clamp(Number(analysis.threatIndex ?? 0), 0, 100), color: "#72f0c8" }
  ];

  ctx.clearRect(0, 0, width, height);
  ctx.strokeStyle = "rgba(255,255,255,0.08)";
  ctx.fillStyle = "rgba(255,255,255,0.45)";
  ctx.lineWidth = 1;

  for (let ring = 1; ring <= 4; ring += 1) {
    ctx.beginPath();
    ctx.arc(cx, cy, (radius / 4) * ring, 0, Math.PI * 2);
    ctx.stroke();
  }

  metrics.forEach((metric, index) => {
    const angle = (-Math.PI / 2) + (index / metrics.length) * Math.PI * 2;
    const axisX = cx + Math.cos(angle) * radius;
    const axisY = cy + Math.sin(angle) * radius;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(axisX, axisY);
    ctx.stroke();
    ctx.fillText(metric.label, cx + Math.cos(angle) * (radius + 18), cy + Math.sin(angle) * (radius + 18));
  });

  ctx.beginPath();
  metrics.forEach((metric, index) => {
    const angle = (-Math.PI / 2) + (index / metrics.length) * Math.PI * 2;
    const r = radius * (metric.value / 100);
    const x = cx + Math.cos(angle) * r;
    const y = cy + Math.sin(angle) * r;
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.closePath();
  ctx.fillStyle = "rgba(114, 240, 200, 0.18)";
  ctx.strokeStyle = "#ffb14d";
  ctx.lineWidth = 2.5;
  ctx.fill();
  ctx.stroke();
}

function drawRelayTimeline(schedule) {
  const canvas = ui.relayTimelineCanvas;
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);

  const nowSec = Math.floor(Date.now() / 1000);
  const rowHeight = 62;
  const barX = 96;
  const totalWidth = width - barX - 26;
  const colors = ["#ff5a3d", "#ffb14d", "#ff855f"];

  ctx.fillStyle = "rgba(255,241,235,0.7)";
  ctx.font = "12px Segoe UI";
  ctx.fillText(`Adaptive pressure ${Math.round((schedule.adaptivePressure || 0) * 100)}%`, 16, 18);

  schedule.relayWindows.forEach((relay, index) => {
    const y = 36 + index * rowHeight;
    const total = relay.onSec + relay.offSec;
    const basePhase = relay.phaseSec ?? 0;
    const generatedAt = schedule.generatedAtSec ?? nowSec;
    const livePhase = ((basePhase + (nowSec - generatedAt)) % total + total) % total;
    const isOn = livePhase < relay.onSec;
    const onWidth = totalWidth * (relay.onSec / total);
    const offWidth = totalWidth - onWidth;

    ctx.fillStyle = "rgba(255,241,235,0.68)";
    ctx.fillText(relay.relay, 16, y + 16);

    ctx.fillStyle = colors[index % colors.length];
    roundRect(ctx, barX, y, onWidth, 18, 8);
    ctx.fill();

    ctx.fillStyle = "rgba(255,255,255,0.12)";
    roundRect(ctx, barX + onWidth, y, offWidth, 18, 8);
    ctx.fill();

    ctx.fillStyle = "rgba(255,241,235,0.78)";
    ctx.fillText(`${relay.onSec}s on`, barX + 8, y + 13);
    ctx.fillText(`${relay.offSec}s off`, barX + onWidth + 8, y + 13);

    const markerX = barX + (livePhase / total) * totalWidth;
    ctx.strokeStyle = isOn ? "#fff4e8" : "rgba(255,241,235,0.55)";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(markerX, y - 6);
    ctx.lineTo(markerX, y + 24);
    ctx.stroke();

    ctx.fillStyle = isOn ? "#fff4e8" : "rgba(255,241,235,0.75)";
    ctx.beginPath();
    ctx.arc(markerX, y + 9, 4.5, 0, Math.PI * 2);
    ctx.fill();

    ctx.fillStyle = isOn ? "#ffd9c7" : "rgba(255,241,235,0.72)";
    ctx.fillText(`${relay.state} | phase ${livePhase}s`, barX, y + 36);
  });
}

function drawRiskHeatmap(grid) {
  const canvas = ui.riskHeatmapCanvas;
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);

  const rows = grid.length;
  const cols = grid[0]?.length || 0;
  const cellW = (width - 40) / cols;
  const cellH = (height - 40) / rows;

  for (let row = 0; row < rows; row += 1) {
    for (let col = 0; col < cols; col += 1) {
      const value = grid[row][col];
      const red = Math.round(255 * value);
      const green = Math.round(220 * (1 - value));
      ctx.fillStyle = `rgba(${red}, ${green}, 90, 0.88)`;
      roundRect(ctx, 18 + col * cellW, 18 + row * cellH, cellW - 8, cellH - 8, 10);
      ctx.fill();
      ctx.fillStyle = "rgba(7, 17, 31, 0.9)";
      ctx.fillText(`${Math.round(value * 100)}`, 30 + col * cellW, 38 + row * cellH);
    }
  }
}

function drawGeoIntel(geoIntel) {
  const canvas = ui.geoIntelCanvas;
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);

  ctx.strokeStyle = "rgba(255,255,255,0.08)";
  for (let x = 20; x < width; x += 40) {
    ctx.beginPath();
    ctx.moveTo(x, 12);
    ctx.lineTo(x, height - 12);
    ctx.stroke();
  }
  for (let y = 20; y < height; y += 40) {
    ctx.beginPath();
    ctx.moveTo(12, y);
    ctx.lineTo(width - 12, y);
    ctx.stroke();
  }

  const trail = geoIntel.trail || [];
  if (!trail.length) return;

  const minLat = Math.min(...trail.map((p) => p.lat));
  const maxLat = Math.max(...trail.map((p) => p.lat));
  const minLng = Math.min(...trail.map((p) => p.lng));
  const maxLng = Math.max(...trail.map((p) => p.lng));
  const latSpan = Math.max(0.0002, maxLat - minLat);
  const lngSpan = Math.max(0.0002, maxLng - minLng);

  const project = (point) => ({
    x: 28 + ((point.lng - minLng) / lngSpan) * (width - 56),
    y: height - 28 - ((point.lat - minLat) / latSpan) * (height - 56)
  });

  ctx.beginPath();
  trail.forEach((point, index) => {
    const pos = project(point);
    if (index === 0) ctx.moveTo(pos.x, pos.y);
    else ctx.lineTo(pos.x, pos.y);
  });
  ctx.strokeStyle = "#74b9ff";
  ctx.lineWidth = 2.2;
  ctx.stroke();

  trail.forEach((point, index) => {
    const pos = project(point);
    const intensity = clamp(point.threat / 100, 0, 1);
    ctx.fillStyle = `rgba(${Math.round(255 * intensity)}, ${Math.round(220 * (1 - intensity))}, 120, 0.95)`;
    ctx.beginPath();
    ctx.arc(pos.x, pos.y, index === trail.length - 1 ? 7 : 4.5, 0, Math.PI * 2);
    ctx.fill();
  });

  const center = project(trail[trail.length - 1]);
  ctx.strokeStyle = "rgba(114,240,200,0.45)";
  ctx.beginPath();
  ctx.arc(center.x, center.y, clamp((geoIntel.zoneRadiusMeters || 60) / 8, 18, 52), 0, Math.PI * 2);
  ctx.stroke();
}

function roundRect(ctx, x, y, width, height, radius) {
  ctx.beginPath();
  ctx.moveTo(x + radius, y);
  ctx.lineTo(x + width - radius, y);
  ctx.quadraticCurveTo(x + width, y, x + width, y + radius);
  ctx.lineTo(x + width, y + height - radius);
  ctx.quadraticCurveTo(x + width, y + height, x + width - radius, y + height);
  ctx.lineTo(x + radius, y + height);
  ctx.quadraticCurveTo(x, y + height, x, y + height - radius);
  ctx.lineTo(x, y + radius);
  ctx.quadraticCurveTo(x, y, x + radius, y);
  ctx.closePath();
}

function drawSeries(ctx, series, width, height, color, maxY) {
  if (series.length < 2) return;
  ctx.strokeStyle = color;
  ctx.lineWidth = 2.5;
  ctx.beginPath();

  series.forEach((value, index) => {
    const x = (index / Math.max(series.length - 1, 1)) * width;
    const y = height - (clamp(value, 0, maxY) / maxY) * (height - 8) - 4;
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });

  ctx.stroke();
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function classifyVoltageBand(battV) {
  if (battV < 11.2) return "Critical";
  if (battV < 11.8) return "Low";
  if (battV < 12.4) return "Nominal";
  return "High";
}
