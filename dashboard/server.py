from flask import Flask, jsonify, render_template_string
import serial
import serial.tools.list_ports
import threading
import re
import time

# --------------------------------------------------
# FIND AVAILABLE SERIAL PORTS
# --------------------------------------------------
ports = list(serial.tools.list_ports.comports())

if not ports:
    raise Exception("No serial ports found. Plug the board in. The machine cannot read the thoughts of your Arduino no matter how desperately humans want wires to become magic.")

print("Available ports:")
for p in ports:
    print(f"  {p.device}")

# Change this to the correct COM port if needed
PORT = "COM4"

print(f"\nConnecting to {PORT} ...")

ser = serial.Serial(PORT, 9600, timeout=1)

# Give Arduino time to reset after opening serial
time.sleep(2)

# --------------------------------------------------
# FLASK APP
# --------------------------------------------------
app = Flask(__name__)

latest_data = {
    "temp": "--",
    "humidity": "--",
    "light": "--"
}


def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def build_energy_state(sensor_data):
    temp = safe_float(sensor_data.get("temp"), 0.0)
    humidity = safe_float(sensor_data.get("humidity"), 0.0)
    light = safe_int(sensor_data.get("light"), 0)

    solar = max(0.0, (light - 200) / 8)
    battery = max(10, min(100, int(solar + 20)))

    loads = {
        "living_room_light": light < 150,
        "bedroom_light": light < 150,
        "kitchen_light": light < 150,
        "outdoor_lights": light < 90,
        "fan_ac": temp > 32,
        "water_heater": battery >= 30,
        "tv": battery >= 30,
        "washing_machine": solar > 60,
        "exhaust_fan": humidity > 75,
    }

    if temp < 20:
        loads["fan_ac"] = False

    if battery < 30:
        loads["tv"] = False
        loads["water_heater"] = False
        loads["bedroom_light"] = light < 120
        loads["kitchen_light"] = False

    if battery < 15:
        loads["living_room_light"] = light < 120
        loads["bedroom_light"] = False
        loads["kitchen_light"] = False
        loads["outdoor_lights"] = False
        loads["washing_machine"] = False

    recommendations = []

    if temp > 32:
        recommendations.append("Turn ON fan or AC in living room")
    elif temp < 20:
        recommendations.append("Turn OFF fan and keep windows closed")

    if humidity > 75:
        recommendations.append("High humidity detected. Run exhaust fan or dehumidifier")

    if light < 150:
        recommendations.append("Turn ON indoor lights")
    else:
        recommendations.append("Turn OFF indoor lights, enough sunlight available")

    if solar > 60:
        recommendations.append("Run washing machine now, solar generation is high")
        recommendations.append("Bright sunlight available. Use solar power and charge battery")

    if battery < 30:
        recommendations.append("Battery low: disable TV and extra lighting")
        recommendations.append("Delay washing machine until solar generation increases")

    if battery < 15:
        recommendations.append("Critical loads only: fan + one light")

    active_loads = [name for name, enabled in loads.items() if enabled]
    load_usage = int((len(active_loads) / len(loads)) * 100)

    if battery < 20:
        ai_mode = "Battery Protection"
        confidence = 92
    elif solar > 60:
        ai_mode = "High Solar Utilization"
        confidence = 88
    elif battery < 35 or light < 150:
        ai_mode = "Energy Saving"
        confidence = 84
    else:
        ai_mode = "Balanced Efficiency"
        confidence = 81

    return {
        "temp": round(temp, 1),
        "humidity": round(humidity, 1),
        "light": light,
        "solar": round(solar, 1),
        "battery": battery,
        "load_usage": load_usage,
        "ai_mode": ai_mode,
        "confidence": confidence,
        "loads": loads,
        "active_loads": active_loads,
        "recommendations": recommendations,
    }

# --------------------------------------------------
# SERIAL READER THREAD
# Expected line format:
# Temp: 27.5 °C | Hum: 68 % | Light: 420
# --------------------------------------------------
def read_serial():
    global latest_data

    while True:
        try:
            line = ser.readline().decode("utf-8", errors="ignore").strip()

            if line:
                print("Received:", line)

                temp_match = re.search(r"Temp:\s*([\d.]+)", line)
                hum_match = re.search(r"Humidity:\s*([\d.]+)", line)
                light_match = re.search(r"Light:\s*(\d+)", line)

                if temp_match:
                    latest_data["temp"] = temp_match.group(1)

                if hum_match:
                    latest_data["humidity"] = hum_match.group(1)

                if light_match:
                    latest_data["light"] = light_match.group(1)

        except Exception as e:
            print("Serial read error:", e)

# Start background serial reader
threading.Thread(target=read_serial, daemon=True).start()

# --------------------------------------------------
# DASHBOARD HTML
# --------------------------------------------------
HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Arduino Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>

    <style>
        body {
            margin: 0;
            padding: 32px 20px 48px;
            min-height: 100vh;
            background:
                radial-gradient(circle at top, rgba(0, 255, 208, 0.12), transparent 30%),
                linear-gradient(180deg, #0f1117 0%, #090b11 100%);
            color: white;
            font-family: "Segoe UI", Arial, sans-serif;
            text-align: center;
        }

        * {
            box-sizing: border-box;
        }

        h1 {
            margin-top: 16px;
            color: #00ffd0;
            font-size: 42px;
        }

        .subtitle {
            color: #888;
            margin-bottom: 40px;
        }

        .dashboard {
            display: flex;
            justify-content: center;
            gap: 30px;
            flex-wrap: wrap;
            padding: 20px;
            max-width: 1100px;
            margin: 0 auto;
        }

        .card {
            background: #1b1f2a;
            border-radius: 20px;
            padding: 30px;
            width: 220px;
            box-shadow: 0 0 25px rgba(0,255,208,0.15);
            transition: transform 0.2s;
        }

        .card:hover {
            transform: translateY(-5px);
        }

        .label {
            font-size: 22px;
            color: #9aa0aa;
            margin-bottom: 15px;
        }

        .value {
            font-size: 46px;
            color: #00ffd0;
            font-weight: bold;
        }

        .unit {
            font-size: 20px;
            color: #9aa0aa;
        }

        .layout-grid {
            max-width: 1200px;
            margin: 28px auto 0;
            display: grid;
            grid-template-columns: 1.1fr 0.9fr;
            gap: 24px;
        }

        .recommend-box,
        .loads-box,
        .ai-panel,
        .house-panel {
            background: #151925;
            border-radius: 24px;
            padding: 28px;
            box-shadow: 0 0 30px rgba(0, 255, 208, 0.08);
            text-align: left;
        }

        .recommend-box h2,
        .loads-box h2,
        .ai-panel h2,
        .house-panel h2,
        .charts-panel h2,
        .gauges-panel h2 {
            margin-top: 0;
            color: #00ffd0;
        }

        .recommend-box ul,
        .loads-grid {
            margin: 0;
            padding: 0;
        }

        .recommend-box li {
            list-style: none;
            margin: 12px 0;
            padding: 14px 16px;
            border-radius: 14px;
            background: #1d2331;
            color: #e7edf7;
        }

        .loads-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 14px;
        }

        .load-pill {
            padding: 14px 16px;
            border-radius: 14px;
            background: #1d2331;
            color: #c8d1de;
        }

        .load-pill.active {
            background: rgba(0, 255, 208, 0.12);
            color: #00ffd0;
            border: 1px solid rgba(0, 255, 208, 0.35);
        }

        .ai-mode {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 16px;
            background: linear-gradient(135deg, rgba(0, 255, 208, 0.14), rgba(255, 204, 0, 0.08));
            border-radius: 18px;
            padding: 18px 20px;
            margin-top: 12px;
        }

        .ai-mode-name {
            font-size: 28px;
            font-weight: bold;
            color: #f6fbff;
        }

        .ai-meta {
            color: #b8c3d1;
            font-size: 15px;
        }

        .confidence-badge {
            min-width: 86px;
            text-align: center;
            padding: 12px 14px;
            border-radius: 999px;
            background: rgba(255, 204, 0, 0.18);
            color: #ffcc00;
            font-weight: bold;
        }

        .house {
            display: grid;
            grid-template-columns: repeat(3, minmax(140px, 1fr));
            gap: 16px;
            margin-top: 18px;
        }

        .room {
            min-height: 110px;
            border-radius: 18px;
            background: #222936;
            border: 1px solid rgba(255, 255, 255, 0.05);
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 8px;
            transition: all 0.4s ease;
            color: #cfd8e4;
            text-align: center;
            padding: 12px;
        }

        .room-icon {
            font-size: 28px;
        }

        .room.active {
            background: #ffcc00;
            color: black;
            box-shadow: 0 0 20px rgba(255, 204, 0, 0.55);
            transform: translateY(-4px);
        }

        .room.fan-active .room-icon {
            animation: spin 1.1s linear infinite;
        }

        .gauges-panel,
        .charts-panel {
            max-width: 1200px;
            margin: 24px auto 0;
            background: #151925;
            border-radius: 24px;
            padding: 28px;
            box-shadow: 0 0 30px rgba(0, 255, 208, 0.08);
            text-align: left;
        }

        .gauge-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(220px, 1fr));
            gap: 24px;
            align-items: center;
        }

        .gauge-card {
            background: #1b1f2a;
            border-radius: 20px;
            padding: 18px;
            text-align: center;
        }

        .gauge-card canvas {
            width: 100% !important;
            max-width: 240px;
            height: 220px !important;
            margin: 0 auto;
        }

        .charts {
            display: grid;
            grid-template-columns: repeat(2, minmax(280px, 1fr));
            gap: 24px;
            margin-top: 20px;
        }

        .chart-card {
            background: #1b1f2a;
            border-radius: 20px;
            padding: 16px;
        }

        .chart-card canvas {
            width: 100% !important;
            height: 300px !important;
        }

        @keyframes spin {
            from { transform: rotate(0deg); }
            to { transform: rotate(360deg); }
        }

        @media (max-width: 980px) {
            .layout-grid,
            .charts,
            .gauge-grid {
                grid-template-columns: 1fr;
            }

            .house {
                grid-template-columns: repeat(2, minmax(140px, 1fr));
            }
        }

        @media (max-width: 640px) {
            h1 {
                font-size: 34px;
            }

            .card {
                width: 100%;
                max-width: 320px;
            }

            .house {
                grid-template-columns: 1fr;
            }
        }

        /* ── Neural Network Panel ── */
        .neural-panel {
            max-width: 1200px;
            margin: 28px auto 60px;
            background: #0d1017;
            border-radius: 24px;
            padding: 28px 28px 32px;
            box-shadow: 0 0 40px rgba(0,255,208,0.10), inset 0 0 60px rgba(0,0,0,0.4);
            text-align: left;
            position: relative;
            overflow: hidden;
        }

        .neural-panel::before {
            content: '';
            position: absolute;
            inset: 0;
            background: radial-gradient(ellipse at 30% 50%, rgba(0,255,208,0.04) 0%, transparent 60%),
                        radial-gradient(ellipse at 70% 50%, rgba(168,85,247,0.04) 0%, transparent 60%);
            pointer-events: none;
        }

        .neural-panel h2 {
            margin-top: 0;
            color: #00ffd0;
            position: relative;
            z-index: 1;
        }

        .neural-panel .neural-subtitle {
            color: #556;
            font-size: 13px;
            margin: -6px 0 18px;
            position: relative;
            z-index: 1;
        }

        #neuralCanvas {
            display: block;
            width: 100%;
            border-radius: 16px;
            position: relative;
            z-index: 1;
        }

        .nn-legend {
            display: flex;
            gap: 24px;
            flex-wrap: wrap;
            margin-top: 20px;
            position: relative;
            z-index: 1;
        }

        .nn-legend-item {
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 12px;
            color: #778;
        }

        .nn-legend-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
        }
    </style>
</head>
<body>

    <h1>Live Sensor Dashboard</h1>
    <div class="subtitle">Tiny glowing numbers extracted from the void of Serial communication. Civilization remains undefeated somehow.</div>

    <div class="dashboard">

        <div class="card">
            <div class="label">Temperature</div>
            <div class="value">
                <span id="temp">--</span>
                <span class="unit">°C</span>
            </div>
        </div>

        <div class="card">
            <div class="label">Humidity</div>
            <div class="value">
                <span id="humidity">--</span>
                <span class="unit">%</span>
            </div>
        </div>

        <div class="card">
            <div class="label">Light</div>
            <div class="value">
                <span id="light">--</span>
            </div>
        </div>

        <div class="card">
            <div class="label">Solar Generation</div>
            <div class="value">
                <span id="solar">--</span>
                <span class="unit">W</span>
            </div>
        </div>

        <div class="card">
            <div class="label">Battery</div>
            <div class="value">
                <span id="battery">--</span>
                <span class="unit">%</span>
            </div>
        </div>

        <div class="card">
            <div class="label">AI Mode</div>
            <div class="value">
                <span id="aiModeCard">--</span>
            </div>
        </div>

    </div>

    <div class="layout-grid">
        <div class="recommend-box">
            <h2>AI Recommendations</h2>
            <ul id="recommendations"></ul>
        </div>

        <div class="ai-panel">
            <h2>AI Status Panel</h2>
            <div class="ai-mode">
                <div>
                    <div class="ai-meta">AI Mode</div>
                    <div class="ai-mode-name" id="aiMode">Balanced Efficiency</div>
                    <div class="ai-meta" id="aiSummary">Controller is balancing comfort and energy use.</div>
                </div>
                <div class="confidence-badge">
                    <span id="confidence">--</span>%
                </div>
            </div>
            <div class="loads-box" style="margin-top: 18px; padding: 20px;">
                <h2>Active House Loads</h2>
                <div class="loads-grid" id="loads"></div>
            </div>
        </div>
    </div>

    <div class="house-panel" style="max-width: 1200px; margin: 24px auto 0;">
        <h2>Smart House Layout</h2>
        <div class="house">
            <div class="room" id="livingRoom">
                <div class="room-icon">LGT</div>
                <div>Living Room Light</div>
            </div>
            <div class="room" id="bedroom">
                <div class="room-icon">FAN</div>
                <div>Bedroom Fan / AC</div>
            </div>
            <div class="room" id="kitchen">
                <div class="room-icon">KIT</div>
                <div>Kitchen Appliance</div>
            </div>
            <div class="room" id="tvRoom">
                <div class="room-icon">TV</div>
                <div>TV Load</div>
            </div>
            <div class="room" id="laundry">
                <div class="room-icon">WM</div>
                <div>Washing Machine</div>
            </div>
            <div class="room" id="outdoor">
                <div class="room-icon">OUT</div>
                <div>Outdoor Lights</div>
            </div>
        </div>
    </div>

    <div class="gauges-panel">
        <h2>Control Gauges</h2>
        <div class="gauge-grid">
            <div class="gauge-card">
                <h3>Battery Charge</h3>
                <canvas id="batteryGauge"></canvas>
            </div>
            <div class="gauge-card">
                <h3>Solar Generation</h3>
                <canvas id="solarGauge"></canvas>
            </div>
            <div class="gauge-card">
                <h3>Load Usage</h3>
                <canvas id="loadGauge"></canvas>
            </div>
        </div>
    </div>

    <div class="charts-panel">
        <h2>Live Grid Analytics</h2>
        <div class="charts">
            <div class="chart-card"><canvas id="tempChart"></canvas></div>
            <div class="chart-card"><canvas id="humidityChart"></canvas></div>
            <div class="chart-card"><canvas id="solarChart"></canvas></div>
            <div class="chart-card"><canvas id="batteryChart"></canvas></div>
        </div>
    </div>

    <!-- ═══════════════════════════════════════════════
         NEURAL NETWORK PANEL  (added below charts)
    ═══════════════════════════════════════════════ -->
    <div class="neural-panel">
        <h2>&#9889; AI Neural Decision Network</h2>
        <div class="neural-subtitle">
            Live neural pathways — sensor inputs stream through the AI decision core and activate field systems in real time.
            Glowing connections carry command signals; particles flow only when a system is operational.
        </div>
        <canvas id="neuralCanvas"></canvas>
        <div class="nn-legend">
            <div class="nn-legend-item">
                <div class="nn-legend-dot" style="background:#00ffd0"></div>
                <span>Sensor Input Layer</span>
            </div>
            <div class="nn-legend-item">
                <div class="nn-legend-dot" style="background:#a855f7"></div>
                <span>AI Hidden Layers</span>
            </div>
            <div class="nn-legend-item">
                <div class="nn-legend-dot" style="background:#ffcc00"></div>
                <span>Active Field System</span>
            </div>
            <div class="nn-legend-item">
                <div class="nn-legend-dot" style="background:#2d3447; border:1px solid #445"></div>
                <span>Standby / Offline</span>
            </div>
            <div class="nn-legend-item">
                <div style="width:24px;height:3px;border-radius:2px;background:linear-gradient(90deg,#00ffd0,transparent)"></div>
                <span>Command Signal</span>
            </div>
        </div>
    </div>

    <script>
        const recommendationList = document.getElementById("recommendations");
        const loadsGrid = document.getElementById("loads");
        const labels = [];
        const tempHistory = [];
        const humidityHistory = [];
        const solarHistory = [];
        const batteryHistory = [];

        function formatLoadName(name) {
            return name
                .split("_")
                .map(word => word.charAt(0).toUpperCase() + word.slice(1))
                .join(" ");
        }

        function createLineChart(id, label, color, background, maxY) {
            return new Chart(document.getElementById(id), {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [{
                        label: label,
                        data: [],
                        borderColor: color,
                        backgroundColor: background,
                        fill: true,
                        tension: 0.35
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            labels: { color: '#d7dce5' }
                        }
                    },
                    scales: {
                        x: {
                            ticks: { color: '#9aa0aa' },
                            grid: { color: 'rgba(255,255,255,0.06)' }
                        },
                        y: {
                            min: 0,
                            max: maxY,
                            ticks: { color: '#9aa0aa' },
                            grid: { color: 'rgba(255,255,255,0.06)' }
                        }
                    }
                }
            });
        }

        function createGauge(id, label, value, color) {
            return new Chart(document.getElementById(id), {
                type: 'doughnut',
                data: {
                    labels: [label, 'Remaining'],
                    datasets: [{
                        data: [value, Math.max(0, 100 - value)],
                        backgroundColor: [color, 'rgba(255,255,255,0.08)'],
                        borderWidth: 0
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    cutout: '72%',
                    plugins: {
                        legend: {
                            labels: { color: '#d7dce5' }
                        }
                    }
                }
            });
        }

        const tempChart = createLineChart('tempChart', 'Temperature vs Time', '#00ffd0', 'rgba(0,255,208,0.10)', 50);
        const humidityChart = createLineChart('humidityChart', 'Humidity vs Time', '#4db8ff', 'rgba(77,184,255,0.10)', 100);
        const solarChart = createLineChart('solarChart', 'Light / Solar vs Time', '#ff9f1c', 'rgba(255,159,28,0.10)', 120);
        const batteryChart = createLineChart('batteryChart', 'Battery Percentage vs Time', '#ffcc00', 'rgba(255,204,0,0.10)', 100);

        tempChart.data.datasets[0].data = tempHistory;
        humidityChart.data.datasets[0].data = humidityHistory;
        solarChart.data.datasets[0].data = solarHistory;
        batteryChart.data.datasets[0].data = batteryHistory;

        const batteryGauge = createGauge('batteryGauge', 'Battery', 0, '#ffcc00');
        const solarGauge = createGauge('solarGauge', 'Solar', 0, '#00ffd0');
        const loadGauge = createGauge('loadGauge', 'Load Usage', 0, '#ff6b6b');

        function updateGauge(chart, value) {
            chart.data.datasets[0].data = [value, Math.max(0, 100 - value)];
            chart.update();
        }

        function setRoomState(id, active, fanMode) {
            const room = document.getElementById(id);
            room.classList.toggle('active', active);
            room.classList.toggle('fan-active', !!fanMode && active);
        }

        function updateHouse(data) {
            setRoomState('livingRoom', data.loads.living_room_light, false);
            setRoomState('bedroom', data.loads.fan_ac, true);
            setRoomState('kitchen', data.loads.kitchen_light || data.loads.water_heater, false);
            setRoomState('tvRoom', data.loads.tv, false);
            setRoomState('laundry', data.loads.washing_machine, false);
            setRoomState('outdoor', data.loads.outdoor_lights, false);
        }

        function updateAiPanel(data) {
            document.getElementById('aiMode').innerText = data.ai_mode;
            document.getElementById('aiModeCard').innerText = data.ai_mode;
            document.getElementById('confidence').innerText = data.confidence;

            let summary = 'Controller is balancing comfort and energy use.';
            if (data.ai_mode === 'Battery Protection') {
                summary = 'Battery reserve is low, so only essential loads should stay active.';
            } else if (data.ai_mode === 'High Solar Utilization') {
                summary = 'Solar generation is strong, so the system is prioritizing productive loads.';
            } else if (data.ai_mode === 'Energy Saving') {
                summary = 'The controller is trimming non-essential usage to reduce demand.';
            }

            document.getElementById('aiSummary').innerText = summary;
        }

        async function updateDashboard() {
            try {
                const response = await fetch("/data");
                const data = await response.json();

                document.getElementById("temp").innerText = data.temp;
                document.getElementById("humidity").innerText = data.humidity;
                document.getElementById("light").innerText = data.light;
                document.getElementById("solar").innerText = data.solar;
                document.getElementById("battery").innerText = data.battery;
                updateAiPanel(data);

                recommendationList.innerHTML = "";
                data.recommendations.forEach(item => {
                    const li = document.createElement("li");
                    li.innerText = item;
                    recommendationList.appendChild(li);
                });

                if (data.recommendations.length === 0) {
                    const li = document.createElement("li");
                    li.innerText = "System stable: no special load changes recommended right now";
                    recommendationList.appendChild(li);
                }

                loadsGrid.innerHTML = "";
                Object.entries(data.loads).forEach(([name, enabled]) => {
                    const div = document.createElement("div");
                    div.className = enabled ? "load-pill active" : "load-pill";
                    div.innerText = `${formatLoadName(name)}: ${enabled ? "ON" : "OFF"}`;
                    loadsGrid.appendChild(div);
                });

                updateHouse(data);

                const currentTime = new Date().toLocaleTimeString();
                labels.push(currentTime);
                tempHistory.push(data.temp);
                humidityHistory.push(data.humidity);
                solarHistory.push(data.solar);
                batteryHistory.push(data.battery);

                if (labels.length > 10) {
                    labels.shift();
                    tempHistory.shift();
                    humidityHistory.shift();
                    solarHistory.shift();
                    batteryHistory.shift();
                }

                tempChart.update();
                humidityChart.update();
                solarChart.update();
                batteryChart.update();

                updateGauge(batteryGauge, data.battery);
                updateGauge(solarGauge, Math.min(100, data.solar));
                updateGauge(loadGauge, data.load_usage);

                /* ── feed the neural network ── */
                if (window._nnUpdate) window._nnUpdate(data);
            }
            catch (err) {
                console.log("Failed to fetch dashboard data:", err);
            }
        }

        updateDashboard();
        setInterval(updateDashboard, 1000);
    </script>

    <!-- ═══════════════════════════════════════════════
         NEURAL NETWORK CANVAS SCRIPT
    ═══════════════════════════════════════════════ -->
    <script>
    (function () {
        /* ────────────────────────────────────────────
           Colour helpers
        ──────────────────────────────────────────── */
        const PAL = {
            cyan:   [0,   255, 208],
            purple: [168,  85, 247],
            yellow: [255, 204,   0],
            blue:   [ 77, 184, 255],
            red:    [255,  80,  80],
            teal:   [  0, 210, 180],
            orange: [255, 159,  28],
            green:  [ 80, 220, 100],
            gray:   [ 55,  65,  88],
            dimgray:[30,  36,  50],
        };
        const rgba = (c, a) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;

        /* ────────────────────────────────────────────
           Node definitions  (x / y filled at layout time)
        ──────────────────────────────────────────── */
        const INP = [
            { lines: ['Temperature'], unit: 'C',  val: '--', col: PAL.cyan   },
            { lines: ['Humidity'],    unit: '%',   val: '--', col: PAL.blue   },
            { lines: ['Light'],       unit: '',    val: '--', col: PAL.orange },
        ];
        const H1 = [
            { lines: ['Pattern',   'Analyser'],  col: PAL.purple },
            { lines: ['Threshold', 'Logic'],     col: PAL.purple },
            { lines: ['Load',      'Predictor'], col: PAL.purple },
            { lines: ['Mode',      'Selector'],  col: PAL.purple },
        ];
        const H2 = [
            { lines: ['Threat',   'Evaluator'],  col: PAL.purple },
            { lines: ['Resource', 'Allocator'],  col: PAL.purple },
            { lines: ['Mission',  'Optimizer'],  col: PAL.purple },
        ];

        /* ── ARMY OUTPUT NODES ──────────────────────────────────────────
           Keys stay identical to backend load keys so loadsState
           lookups work without any backend change whatsoever.
        ───────────────────────────────────────────────────────────────── */
        const OUT = [
            { lines: ['Perimeter',   'Lights'],   key: 'living_room_light', col: PAL.yellow },
            { lines: ['Guard',       'Towers'],   key: 'bedroom_light',     col: PAL.yellow },
            { lines: ['Radar',       'Array'],    key: 'kitchen_light',     col: PAL.cyan   },
            { lines: ['Surveillance','Grid'],     key: 'outdoor_lights',    col: PAL.teal   },
            { lines: ['Comms',       'Tower'],    key: 'fan_ac',            col: PAL.blue   },
            { lines: ['Alert',       'Siren'],    key: 'water_heater',      col: PAL.red    },
            { lines: ['Drone',       'Bay'],      key: 'tv',                col: PAL.orange },
            { lines: ['Field',       'Hospital'], key: 'washing_machine',   col: PAL.green  },
            { lines: ['Ammo',        'Bunker'],   key: 'exhaust_fan',       col: PAL.purple },
        ];

        /* ────────────────────────────────────────────
           Canvas setup
        ──────────────────────────────────────────── */
        const canvas = document.getElementById('neuralCanvas');
        const ctx    = canvas.getContext('2d');
        let W = 1, H = 1;
        const NODE_R = 30;

        function layout() {
            const place = (arr, xFrac) => {
                const cx = W * xFrac;
                arr.forEach((n, i) => {
                    n.x = cx;
                    n.y = H * (i + 1) / (arr.length + 1);
                });
            };
            place(INP, 0.06);
            place(H1,  0.32);
            place(H2,  0.60);
            place(OUT, 0.90);
        }

        function resize() {
            const rect = canvas.parentElement.getBoundingClientRect();
            W = Math.max(400, rect.width - 56);
            H = Math.max(520, Math.min(680, W * 0.52));
            canvas.width  = W;
            canvas.height = H;
            layout();
            buildParticles();
        }

        window.addEventListener('resize', resize);

        /* ────────────────────────────────────────────
           Particle system
        ──────────────────────────────────────────── */
        let particles = [];
        let loadsState = {};

        function bz(t, x0, y0, x1, y1, x2, y2, x3, y3) {
            const m = 1 - t;
            return {
                x: m*m*m*x0 + 3*m*m*t*x1 + 3*m*t*t*x2 + t*t*t*x3,
                y: m*m*m*y0 + 3*m*m*t*y1 + 3*m*t*t*y2 + t*t*t*y3,
            };
        }

        function mkPart(from, to, col, outKey, count) {
            for (let k = 0; k < count; k++) {
                particles.push({
                    from, to,
                    t: Math.random(),
                    speed: 0.0028 + Math.random() * 0.004,
                    col,
                    outKey: outKey || null,
                    sz: 2.2 + Math.random() * 1.4,
                });
            }
        }

        function buildParticles() {
            particles = [];
            INP.forEach(inp => H1.forEach(h  => mkPart(inp, h,  PAL.cyan,   null,    3)));
            H1.forEach(h1  => H2.forEach(h2  => mkPart(h1,  h2, PAL.purple, null,    3)));
            H2.forEach(h2  => OUT.forEach(out => mkPart(h2,  out, out.col,  out.key, 2)));
        }

        /* ────────────────────────────────────────────
           Drawing helpers
        ──────────────────────────────────────────── */
        function connPts(a, b) {
            const ax = a.x + NODE_R, ay = a.y;
            const bx = b.x - NODE_R, by = b.y;
            const dx = (bx - ax) * 0.42;
            return { ax, ay, bx, by, cx1: ax + dx, cy1: ay, cx2: bx - dx, cy2: by };
        }

        function drawConn(a, b, col, alpha, lw) {
            const { ax, ay, bx, by, cx1, cy1, cx2, cy2 } = connPts(a, b);
            ctx.beginPath();
            ctx.moveTo(ax, ay);
            ctx.bezierCurveTo(cx1, cy1, cx2, cy2, bx, by);
            ctx.strokeStyle = rgba(col, alpha);
            ctx.lineWidth   = lw;
            ctx.stroke();
        }

        function drawNode(node, active) {
            const { x, y, lines, col, val, unit } = node;
            const c = active ? col : PAL.dimgray;
            const glowA   = active ? 0.28 : 0.04;
            const fillA   = active ? 0.16 : 0.06;
            const strokeA = active ? 0.90 : 0.25;
            const textCol = active ? '#d7dce5' : rgba(PAL.gray, 0.6);

            const grd = ctx.createRadialGradient(x, y, 0, x, y, NODE_R * 3);
            grd.addColorStop(0,   rgba(c, glowA));
            grd.addColorStop(0.5, rgba(c, glowA * 0.3));
            grd.addColorStop(1,   rgba(c, 0));
            ctx.fillStyle = grd;
            ctx.beginPath(); ctx.arc(x, y, NODE_R * 3, 0, Math.PI*2); ctx.fill();

            ctx.beginPath(); ctx.arc(x, y, NODE_R, 0, Math.PI*2);
            ctx.fillStyle   = rgba(c, fillA); ctx.fill();
            ctx.strokeStyle = rgba(c, strokeA);
            ctx.lineWidth   = active ? 2 : 1;
            ctx.stroke();

            ctx.beginPath(); ctx.arc(x, y, 5, 0, Math.PI*2);
            ctx.fillStyle = rgba(c, active ? 0.85 : 0.25); ctx.fill();

            ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
            ctx.fillStyle = textCol;
            const lCount = lines.filter(l => l.trim()).length;
            if (lCount === 1) {
                ctx.font = 'bold 10px "Segoe UI",Arial';
                ctx.fillText(lines[0], x, y);
            } else {
                ctx.font = 'bold 9px "Segoe UI",Arial';
                ctx.fillText(lines[0], x, y - 7);
                ctx.fillText(lines[1], x, y + 7);
            }

            if (val !== undefined) {
                ctx.fillStyle = rgba(c, active ? 0.95 : 0.35);
                ctx.font = 'bold 11px "Segoe UI",Arial';
                ctx.fillText(val + unit, x, y + NODE_R + 15);
            }
        }

        /* ────────────────────────────────────────────
           Render loop
        ──────────────────────────────────────────── */
        let frame = 0;

        function render() {
            requestAnimationFrame(render);
            frame++;
            ctx.clearRect(0, 0, W, H);

            ctx.textAlign = 'center';
            ctx.font = '10px "Segoe UI",Arial';
            ctx.fillStyle = '#334';
            const layerLabels = [
                ['INPUT LAYER',    INP],
                ['HIDDEN LAYER 1', H1 ],
                ['HIDDEN LAYER 2', H2 ],
                ['OUTPUT LAYER',   OUT],
            ];
            layerLabels.forEach(([lbl, arr]) => {
                if (arr[0]) ctx.fillText(lbl, arr[0].x, 16);
            });

            ctx.lineCap = 'round';
            INP.forEach(inp => H1.forEach(h  => drawConn(inp, h,  PAL.cyan,   0.055, 0.8)));
            H1.forEach(h1  => H2.forEach(h2  => drawConn(h1,  h2, PAL.purple, 0.055, 0.8)));
            H2.forEach(h2  => OUT.forEach(out => {
                const on = !!loadsState[out.key];
                drawConn(h2, out, on ? out.col : PAL.gray, on ? 0.22 : 0.03, on ? 1.5 : 0.5);
            }));

            particles.forEach(p => {
                const active = p.outKey ? !!loadsState[p.outKey] : true;
                if (!active) return;

                p.t += p.speed;
                if (p.t > 1) p.t -= 1;

                const a = p.from, b = p.to;
                const { ax, ay, bx, by, cx1, cy1, cx2, cy2 } = connPts(a, b);
                const pt = bz(p.t, ax, ay, cx1, cy1, cx2, cy2, bx, by);

                const grd2 = ctx.createRadialGradient(pt.x, pt.y, 0, pt.x, pt.y, p.sz * 4);
                grd2.addColorStop(0,   rgba(p.col, 0.45));
                grd2.addColorStop(0.5, rgba(p.col, 0.10));
                grd2.addColorStop(1,   rgba(p.col, 0));
                ctx.fillStyle = grd2;
                ctx.beginPath(); ctx.arc(pt.x, pt.y, p.sz * 4, 0, Math.PI*2); ctx.fill();

                ctx.beginPath(); ctx.arc(pt.x, pt.y, p.sz, 0, Math.PI*2);
                ctx.fillStyle = rgba(p.col, 0.90); ctx.fill();
            });

            const pulse = 0.5 + 0.5 * Math.sin(frame * 0.022);
            ;[...H1, ...H2].forEach((h, i) => {
                const r = NODE_R + 6 + 4 * Math.sin(frame * 0.018 + i * 0.9);
                ctx.beginPath(); ctx.arc(h.x, h.y, r, 0, Math.PI*2);
                ctx.strokeStyle = rgba(PAL.purple, 0.10 + 0.06 * pulse);
                ctx.lineWidth = 1.5; ctx.stroke();
            });

            INP.forEach(n => drawNode(n, true));
            H1.forEach(n  => drawNode(n, true));
            H2.forEach(n  => drawNode(n, true));
            OUT.forEach(n => drawNode(n, !!loadsState[n.key]));

            H2.forEach(h2 => OUT.forEach(out => {
                if (!loadsState[out.key]) return;
                drawConn(h2, out, out.col, 0.35, 1.5);
            }));
        }

        /* ────────────────────────────────────────────
           Public API — called from updateDashboard()
        ──────────────────────────────────────────── */
        window._nnUpdate = function (data) {
            loadsState = data.loads || {};
            if (INP[0]) { INP[0].val = data.temp; }
            if (INP[1]) { INP[1].val = data.humidity; }
            if (INP[2]) { INP[2].val = data.light; }
        };

        resize();
        render();
    })();
    </script>

</body>
</html>
"""

# --------------------------------------------------
# ROUTES
# --------------------------------------------------
@app.route("/")
def home():
    return render_template_string(HTML)

@app.route("/data")
def data():
    return jsonify(build_energy_state(latest_data))

# --------------------------------------------------
# RUN SERVER
# --------------------------------------------------
if __name__ == "__main__":
    print("\nDashboard running at:")
    print("http://127.0.0.1:5000\n")

    app.run(host="0.0.0.0", port=5000, debug=False)