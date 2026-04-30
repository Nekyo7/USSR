from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Deque, Dict, List

from flask import Flask, Response, jsonify, request, send_from_directory

from ml_models import train_models

try:
    import serial
except ImportError:  # pyserial is optional until live hardware mode is used.
    serial = None


ROOT_DIR = Path(__file__).resolve().parent.parent
PUBLIC_DIR = ROOT_DIR / "public"
DATA_PATH = ROOT_DIR / "data" / "demo-telemetry.ndjson"
SERIAL_PORT = os.environ.get("APIS_SERIAL_PORT", "COM4")
BAUD_RATE = int(os.environ.get("APIS_BAUD_RATE", "115200"))

app = Flask(__name__, static_folder=str(PUBLIC_DIR), static_url_path="")
MODELS = train_models(seed=17)

MQTT_SCHEMA = {
    "broker_notes": "UI does not require MQTT to function, but these topics define backend integration contracts.",
    "topics": [
        {
            "topic": "apis/unit/{unitId}/telemetry",
            "direction": "device_to_backend",
            "qos": 1,
            "payload_fields": [
                "ts", "unitId", "battV", "battPct", "loadW", "tempC", "humidity",
                "currentA", "ambientLight", "motionDetected", "mode"
            ],
        },
        {
            "topic": "apis/unit/{unitId}/mode/set",
            "direction": "backend_to_device",
            "qos": 1,
            "payload_fields": ["mode", "reason", "issuedAt"],
        },
        {
            "topic": "apis/unit/{unitId}/relay/schedule",
            "direction": "backend_to_device",
            "qos": 1,
            "payload_fields": ["mode", "relayWindows", "refreshSec"],
        },
        {
            "topic": "apis/unit/{unitId}/faults",
            "direction": "backend_to_dashboard",
            "qos": 1,
            "payload_fields": ["faultClass", "severity", "activeFlags", "recommendedAction"],
        },
    ],
}

SYSTEM_STATE: Dict[str, object] = {
    "mode": "PATROL",
    "units": defaultdict(lambda: {"history": deque(maxlen=120), "last_analysis": None}),
    "last_mode_change": int(time.time() * 1000),
}

SERIAL_LOCK = threading.Lock()
SERIAL_STATE: Dict[str, object] = {
    "port": SERIAL_PORT,
    "baudRate": BAUD_RATE,
    "connected": False,
    "lastError": None,
    "lastLineAt": None,
    "packetCount": 0,
}
LATEST_SERIAL_ENVELOPE: Dict[str, object] | None = None


def normalize_packet(packet: Dict[str, object]) -> Dict[str, object]:
    normalized = dict(packet)
    normalized.setdefault("unitId", "ALPHA-01")
    normalized.setdefault("ts", int(time.time() * 1000))

    batt_v = float(normalized.get("battV", 0) or 0)
    current_a = float(normalized.get("currentA", 0) or 0)
    normalized.setdefault("loadW", round(batt_v * current_a, 2))

    if "battPct" not in normalized and batt_v:
        normalized["battPct"] = estimate_battery_pct(batt_v)

    return normalized


def parse_serial_line(line: str) -> Dict[str, object] | None:
    cleaned = "".join(char for char in line.strip() if char.isprintable())
    if not cleaned:
        return None

    if cleaned.startswith("{"):
        return json.loads(cleaned)

    if cleaned.startswith(("ALERT:", "Sensor Error")):
        return None

    # Current Arduino sketch format:
    # Temp: 31.5 | Humidity: 42 | Light: 640 | Voltage: 12.40 | Current: 1.90 | Motion: 1
    aliases = {
        "temp": "tempC",
        "temperature": "tempC",
        "humidity": "humidity",
        "hum": "humidity",
        "light": "ambientLight",
        "ldr": "ambientLight",
        "voltage": "battV",
        "battv": "battV",
        "battery": "battV",
        "current": "currentA",
        "currenta": "currentA",
        "motion": "motionDetected",
        "pir": "motionDetected",
    }
    values: Dict[str, object] = {}
    for match in re.finditer(r"([A-Za-z ]+)\s*:\s*(-?\d+(?:\.\d+)?)", cleaned):
        raw_key = match.group(1).strip().lower().replace(" ", "")
        key = aliases.get(raw_key)
        if not key:
            continue
        number = float(match.group(2))
        values[key] = int(number) if key in {"ambientLight", "motionDetected"} else number

    required = {"tempC", "humidity", "ambientLight", "battV", "currentA", "motionDetected"}
    if not required.issubset(values):
        raise ValueError(f"Unsupported serial line: {cleaned!r}")

    batt_v = float(values["battV"])
    current_a = float(values["currentA"])
    return {
        "ts": int(time.time() * 1000),
        "unitId": "ALPHA-01",
        "battV": batt_v,
        "battPct": estimate_battery_pct(batt_v),
        "loadW": round(batt_v * current_a, 2),
        "tempC": float(values["tempC"]),
        "humidity": float(values["humidity"]),
        "currentA": current_a,
        "ambientLight": int(values["ambientLight"]),
        "motionDetected": int(values["motionDetected"]),
        "mode": str(SYSTEM_STATE["mode"]),
    }


def publish_serial_packet(packet: Dict[str, object]) -> Dict[str, object]:
    global LATEST_SERIAL_ENVELOPE

    envelope = process_packet(normalize_packet(packet))
    with SERIAL_LOCK:
        SERIAL_STATE["packetCount"] = int(SERIAL_STATE["packetCount"]) + 1
        SERIAL_STATE["lastLineAt"] = int(time.time() * 1000)
        SERIAL_STATE["lastError"] = None
        LATEST_SERIAL_ENVELOPE = envelope
    return envelope


def serial_reader() -> None:
    if serial is None:
        with SERIAL_LOCK:
            SERIAL_STATE["lastError"] = "pyserial is not installed. Run: pip install -r backend/requirements.txt"
        return

    while True:
        try:
            with serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1) as ser:
                with SERIAL_LOCK:
                    SERIAL_STATE["connected"] = True
                    SERIAL_STATE["lastError"] = None
                print(f"Connected to Arduino serial on {SERIAL_PORT} at {BAUD_RATE} baud")

                while True:
                    raw_line = ser.readline()
                    if not raw_line:
                        continue

                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue

                    try:
                        packet = parse_serial_line(line)
                        if packet is None:
                            continue
                        publish_serial_packet(packet)
                        print(f"Telemetry: {line}")
                    except json.JSONDecodeError:
                        with SERIAL_LOCK:
                            SERIAL_STATE["lastError"] = f"Invalid JSON from serial: {line[:120]!r}"
                        print(f"Invalid JSON from serial: {line!r}")
                    except ValueError as error:
                        with SERIAL_LOCK:
                            SERIAL_STATE["lastError"] = str(error)
                        print(error)
                    except Exception as error:
                        with SERIAL_LOCK:
                            SERIAL_STATE["lastError"] = str(error)
                        print(f"Serial packet processing failed: {error}")
        except Exception as error:
            with SERIAL_LOCK:
                SERIAL_STATE["connected"] = False
                SERIAL_STATE["lastError"] = str(error)
            print(f"Serial connection failed on {SERIAL_PORT}: {error}")
            time.sleep(2)


def start_serial_thread() -> None:
    thread = threading.Thread(target=serial_reader, daemon=True, name="arduino-serial-reader")
    thread.start()


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return response


@app.route("/api/health")
def health():
    with SERIAL_LOCK:
        serial_state = dict(SERIAL_STATE)
    return jsonify(
        {
            "ok": True,
            "app": "apis-expo-ui-flask",
            "mode": SYSTEM_STATE["mode"],
            "synthetic_training": MODELS["training"],
            "serial": serial_state,
        }
    )


@app.route("/api/mqtt-schema")
def mqtt_schema():
    return jsonify(MQTT_SCHEMA)


@app.route("/api/system-state")
def system_state():
    return jsonify(
        {
            "mode": SYSTEM_STATE["mode"],
            "lastModeChange": SYSTEM_STATE["last_mode_change"],
            "syntheticTraining": MODELS["training"],
        }
    )


@app.route("/api/mode", methods=["POST"])
def set_mode():
    payload = request.get_json(force=True, silent=True) or {}
    mode = str(payload.get("mode", "")).upper()
    if mode not in {"PATROL", "SURVEILLANCE", "STEALTH", "ALERT"}:
        return jsonify({"ok": False, "error": "Unsupported mode"}), 400

    SYSTEM_STATE["mode"] = mode
    SYSTEM_STATE["last_mode_change"] = int(time.time() * 1000)
    reason = payload.get("reason", "operator_switch")
    return jsonify({"ok": True, "mode": mode, "reason": reason})


@app.route("/api/serial-status")
def serial_status():
    with SERIAL_LOCK:
        serial_state = dict(SERIAL_STATE)
        has_packet = LATEST_SERIAL_ENVELOPE is not None
    serial_state["hasPacket"] = has_packet
    return jsonify(serial_state)


@app.route("/api/telemetry", methods=["GET", "POST"])
def telemetry():
    if request.method == "GET":
        with SERIAL_LOCK:
            envelope = LATEST_SERIAL_ENVELOPE
            serial_state = dict(SERIAL_STATE)
        if envelope is None:
            return jsonify({"ok": False, "error": "No serial telemetry available", "serial": serial_state}), 404
        return jsonify(envelope)

    packet = normalize_packet(request.get_json(force=True, silent=True) or {})
    result = process_packet(packet)
    return jsonify(result)


@app.route("/api/serial-stream")
def serial_stream():
    def generate():
        last_seen_count = -1
        while True:
            with SERIAL_LOCK:
                envelope = LATEST_SERIAL_ENVELOPE
                serial_state = dict(SERIAL_STATE)
                packet_count = int(SERIAL_STATE["packetCount"])

            if envelope is not None and packet_count != last_seen_count:
                last_seen_count = packet_count
                yield f"data: {json.dumps(envelope)}\n\n"
            elif envelope is None:
                yield f"event: status\ndata: {json.dumps(serial_state)}\n\n"

            time.sleep(0.25)

    return Response(generate(), mimetype="text/event-stream")


@app.route("/api/demo-stream")
def demo_stream():
    def generate():
        frames = []
        if DATA_PATH.exists():
            frames.extend(
                json.loads(line)
                for line in DATA_PATH.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
        if not frames:
            frames.append({"unitId": "ALPHA-01", "battPct": 80, "tempC": 31, "mode": "PATROL"})

        index = 0
        while True:
            packet = dict(frames[index % len(frames)])
            packet["ts"] = int(time.time() * 1000)
            result = process_packet(packet)
            yield f"data: {json.dumps(result)}\n\n"
            index += 1
            time.sleep(0.9)

    return Response(generate(), mimetype="text/event-stream")


@app.route("/")
def root():
    return send_from_directory(PUBLIC_DIR, "index.html")


@app.route("/<path:path>")
def static_proxy(path: str):
    target = PUBLIC_DIR / path
    if target.exists():
        return send_from_directory(PUBLIC_DIR, path)
    return send_from_directory(PUBLIC_DIR, "index.html")


def process_packet(packet: Dict[str, object]) -> Dict[str, object]:
    unit_id = str(packet.get("unitId", "ALPHA-01"))
    unit_state = SYSTEM_STATE["units"][unit_id]
    history: Deque[Dict[str, object]] = unit_state["history"]
    history.append(packet)

    analysis = analyze_packet(packet, list(history), str(SYSTEM_STATE["mode"]))
    unit_state["last_analysis"] = analysis

    return {
        "packet": packet,
        "analysis": analysis,
        "system": {
            "mode": SYSTEM_STATE["mode"],
            "lastModeChange": SYSTEM_STATE["last_mode_change"],
            "syntheticTraining": MODELS["training"],
        },
    }


def analyze_packet(packet: Dict[str, object], history: List[Dict[str, object]], active_mode: str) -> Dict[str, object]:
    operational_tree = MODELS["operational_tree"]
    fault_tree = MODELS["fault_tree"]

    feature_vector = to_features(packet)
    op_label, op_trace, op_probabilities = operational_tree.predict_details(feature_vector)
    fault_label, fault_trace, fault_probabilities = fault_tree.predict_details(feature_vector)

    threat_index = compute_threat_index(packet)
    confidence = compute_confidence(packet, history)
    power_readiness = compute_power_readiness(packet)
    battery_forecast = forecast_battery_minutes(history)
    anomalies = detect_anomalies(history)
    active_faults = build_fault_flags(packet, fault_label, anomalies)
    stealth_schedule = build_relay_schedule(active_mode, packet, threat_index, battery_forecast, confidence)
    mode_recommendation = recommend_mode(active_mode, threat_index, power_readiness, fault_label)

    return {
        "powerReadiness": power_readiness,
        "threatIndex": threat_index,
        "confidence": confidence,
        "batteryForecastMinutes": battery_forecast,
        "anomalies": anomalies,
        "faultDetection": {
            "faultClass": fault_label,
            "treeTrace": fault_trace,
            "activeFlags": active_faults,
            "severity": fault_severity(fault_label, anomalies),
        },
        "operationalModel": {
            "predictedState": op_label,
            "treeTrace": op_trace,
            "probabilities": op_probabilities,
            "training": MODELS["training"],
        },
        "faultProbabilities": fault_probabilities,
        "modeControl": {
            "activeMode": active_mode,
            "recommendedMode": mode_recommendation,
        },
        "stealthRelaySchedule": stealth_schedule,
        "dashboardPanels": build_dashboard_panels(packet, op_label, fault_label, active_faults, anomalies, stealth_schedule),
        "riskHeatmap": build_risk_heatmap(packet, threat_index, active_mode),
        "geoIntel": build_geo_intel(packet, history, threat_index),
        "actions": build_actions(active_mode, mode_recommendation, fault_label, anomalies, battery_forecast, packet),
        "mqttTopics": MQTT_SCHEMA["topics"],
    }


def to_features(packet: Dict[str, object]) -> Dict[str, float]:
    batt_v = float(packet.get("battV", 0))
    current_a = float(packet.get("currentA", 0))
    return {
        "battPct": float(packet.get("battPct", estimate_battery_pct(batt_v))),
        "battV": batt_v,
        "tempC": float(packet.get("tempC", 0)),
        "humidity": float(packet.get("humidity", 0)),
        "currentA": current_a,
        "loadW": float(packet.get("loadW", batt_v * current_a)),
        "ambientLight": float(packet.get("ambientLight", 0)),
        "motionDetected": float(packet.get("motionDetected", 0)),
    }


def compute_threat_index(packet: Dict[str, object]) -> int:
    batt_v = float(packet.get("battV", 0))
    batt_pct = float(packet.get("battPct", estimate_battery_pct(batt_v)))
    batt_risk = clamp(100 - batt_pct, 0, 100)
    temp_risk = clamp((float(packet.get("tempC", 0)) - 30) * 6, 0, 100)
    humidity_risk = clamp((float(packet.get("humidity", 0)) - 65) * 3, 0, 100)
    current_risk = clamp((float(packet.get("currentA", 0)) - 1.4) * 38, 0, 100)
    load_risk = clamp((float(packet.get("loadW", batt_v * float(packet.get("currentA", 0)))) - 18) * 4, 0, 100)
    light_risk = clamp((260 - float(packet.get("ambientLight", 1023))) / 2.6, 0, 100)
    motion_risk = 88 if int(float(packet.get("motionDetected", 0))) and float(packet.get("ambientLight", 1023)) < 240 else 42 if int(float(packet.get("motionDetected", 0))) else 0
    return round(
        0.19 * batt_risk
        + 0.18 * temp_risk
        + 0.12 * humidity_risk
        + 0.16 * current_risk
        + 0.14 * load_risk
        + 0.10 * light_risk
        + 0.11 * motion_risk
    )


def compute_confidence(packet: Dict[str, object], history: List[Dict[str, object]]) -> int:
    age_seconds = max(0, (time.time() * 1000 - float(packet.get("ts", time.time() * 1000))) / 1000)
    missing_penalty = 0
    for key in ("battV", "currentA", "tempC", "humidity", "ambientLight", "motionDetected"):
        if key not in packet:
            missing_penalty += 8
    anomaly_penalty = min(30, len(detect_anomalies(history)) * 8)
    return round(clamp(100 - age_seconds * 5 - missing_penalty - anomaly_penalty, 18, 99))


def compute_power_readiness(packet: Dict[str, object]) -> int:
    batt_v = float(packet.get("battV", 0))
    batt_pct = float(packet.get("battPct", estimate_battery_pct(batt_v)))
    load_w = float(packet.get("loadW", batt_v * float(packet.get("currentA", 0))))
    current_a = float(packet.get("currentA", 0))
    return round(
        clamp(
            0.55 * batt_pct
            + 0.15 * clamp(batt_v * 7.4, 0, 100)
            + 0.15 * clamp(100 - load_w * 2.2, 0, 100)
            + 0.15 * clamp(100 - current_a * 22, 0, 100),
            0,
            100,
        )
    )


def forecast_battery_minutes(history: List[Dict[str, object]]) -> int | None:
    if len(history) < 8:
        return None
    points = [{"x": idx, "y": float(sample.get("battPct", 0))} for idx, sample in enumerate(history)]
    x_mean = sum(point["x"] for point in points) / len(points)
    y_mean = sum(point["y"] for point in points) / len(points)

    num = sum((point["x"] - x_mean) * (point["y"] - y_mean) for point in points)
    den = sum((point["x"] - x_mean) ** 2 for point in points) or 1
    slope = num / den
    if slope >= -0.01:
        return None

    samples_to_critical = (points[-1]["y"] - 20) / abs(slope)
    return max(0, round(samples_to_critical * 0.9))


def detect_anomalies(history: List[Dict[str, object]]) -> List[Dict[str, object]]:
    if len(history) < 8:
        return []

    fields = {
        "Battery": "battPct",
        "Temperature": "tempC",
        "Humidity": "humidity",
        "Current": "currentA",
        "Light": "ambientLight",
    }
    anomalies: List[Dict[str, object]] = []

    for name, key in fields.items():
        series = [float(sample.get(key, 0)) for sample in history]
        baseline = series[-8:-1]
        if not baseline:
            continue
        mean = sum(baseline) / len(baseline)
        variance = sum((value - mean) ** 2 for value in baseline) / len(baseline)
        std_dev = math.sqrt(variance) or 0.01
        latest = series[-1]
        z_score = abs((latest - mean) / std_dev)
        if z_score >= 1.9:
            anomalies.append(
                {
                    "name": name,
                    "score": round(z_score, 2),
                    "severity": round(clamp(z_score * 25, 0, 100)),
                    "description": f"{name} deviated {z_score:.1f} sigma from rolling baseline",
                }
            )

    anomalies.sort(key=lambda item: item["severity"], reverse=True)
    return anomalies


def build_fault_flags(packet: Dict[str, object], fault_label: str, anomalies: List[Dict[str, object]]) -> List[str]:
    flags: List[str] = []
    if fault_label != "NO_FAULT":
        flags.append(fault_label)
    if float(packet.get("tempC", 0)) > 40:
        flags.append("THERMAL_PEAK")
    if float(packet.get("battPct", estimate_battery_pct(float(packet.get("battV", 0))))) < 25:
        flags.append("LOW_BATTERY")
    if float(packet.get("motionDetected", 0)) > 0:
        flags.append("PIR_ACTIVITY")
    if float(packet.get("ambientLight", 1023)) < 220:
        flags.append("LOW_VISIBILITY")
    flags.extend(f"ANOMALY_{item['name'].upper()}" for item in anomalies[:2])
    return list(dict.fromkeys(flags))


def fault_severity(fault_label: str, anomalies: List[Dict[str, object]]) -> str:
    if fault_label in {"INTRUSION_ALERT", "THERMAL_FAULT"}:
        return "high"
    if fault_label in {"POWER_FAULT", "LOW_VISIBILITY_WATCH"} or anomalies:
        return "medium"
    return "low"


def recommend_mode(active_mode: str, threat_index: int, power_readiness: int, fault_label: str) -> str:
    if threat_index > 75 or fault_label in {"INTRUSION_ALERT", "THERMAL_FAULT"}:
        return "ALERT"
    if power_readiness < 40:
        return "STEALTH"
    if active_mode == "PATROL" and (threat_index > 45 or fault_label == "LOW_VISIBILITY_WATCH"):
        return "SURVEILLANCE"
    return active_mode


def build_relay_schedule(
    active_mode: str,
    packet: Dict[str, object],
    threat_index: int,
    battery_forecast: int | None,
    confidence: int,
):
    batt_pct = float(packet.get("battPct", 0))
    current_a = float(packet.get("currentA", 0))
    ambient_light = float(packet.get("ambientLight", 1023))
    load_w = float(packet.get("loadW", float(packet.get("battV", 0)) * current_a))
    dynamic_pressure = clamp(
        (threat_index / 100) * 0.42
        + (1 - batt_pct / 100) * 0.28
        + clamp(load_w / 32, 0, 1) * 0.2
        + clamp((260 - ambient_light) / 260, 0, 1) * 0.1,
        0,
        1,
    )

    if active_mode == "STEALTH":
        radio_window = round(8 + (1 - dynamic_pressure) * 8)
        sleep_window = round(28 + dynamic_pressure * 28)
        lcd_window = round(6 + (threat_index / 100) * 8)
    elif active_mode == "ALERT":
        radio_window = round(30 + (threat_index / 100) * 18)
        sleep_window = round(4 + (100 - confidence) / 25)
        lcd_window = round(20 + (threat_index / 100) * 14)
    elif active_mode == "SURVEILLANCE":
        radio_window = round(18 + (threat_index / 100) * 10)
        sleep_window = round(12 + dynamic_pressure * 10)
        lcd_window = round(14 + (threat_index / 100) * 8)
    else:
        radio_window = round(16 + (threat_index / 100) * 8)
        sleep_window = round(14 + dynamic_pressure * 14)
        lcd_window = round(12 + (confidence / 100) * 8)

    generated_at = int(time.time())

    relay_windows = [
        {"relay": "RADIO", "onSec": radio_window, "offSec": sleep_window},
        {"relay": "LCD", "onSec": lcd_window, "offSec": max(6, sleep_window - 4)},
        {
            "relay": "AUX_SENSOR_BUS",
            "onSec": round(10 + (threat_index / 100) * 7) if active_mode == "STEALTH" else round(16 + (threat_index / 100) * 6),
            "offSec": round(20 + dynamic_pressure * 12) if active_mode == "STEALTH" else round(10 + dynamic_pressure * 8),
        },
    ]

    for relay in relay_windows:
        cycle_length = relay["onSec"] + relay["offSec"]
        phase_sec = generated_at % cycle_length
        relay["cycleSec"] = cycle_length
        relay["phaseSec"] = phase_sec
        relay["state"] = "ON" if phase_sec < relay["onSec"] else "OFF"

    return {
        "strategy": "duty_cycled_relays",
        "refreshSec": 1,
        "generatedAtSec": generated_at,
        "adaptivePressure": round(dynamic_pressure, 2),
        "estimatedBatteryWindowMinutes": battery_forecast,
        "relayWindows": relay_windows,
    }


def build_dashboard_panels(packet, op_label, fault_label, active_faults, anomalies, stealth_schedule):
    batt_v = float(packet.get("battV", 0))
    current_a = float(packet.get("currentA", 0))
    return [
        {
            "title": "Decision Tree State",
            "value": op_label,
            "detail": "Synthetic-random-data trained operational classifier",
        },
        {
            "title": "Fault Class",
            "value": fault_label,
            "detail": ", ".join(active_faults[:3]) if active_faults else "No active fault flags",
        },
        {
            "title": "Power Draw",
            "value": f"{float(packet.get('loadW', batt_v * current_a)):.1f}W",
            "detail": "Derived from live voltage and ACS712 current",
        },
        {
            "title": "Night Watch",
            "value": f"{stealth_schedule['relayWindows'][0]['onSec']}s/{stealth_schedule['relayWindows'][0]['offSec']}s",
            "detail": "RADIO stealth duty cycle",
        },
        {
            "title": "Light Condition",
            "value": classify_light_band(float(packet.get("ambientLight", 0))),
            "detail": f"{int(float(packet.get('ambientLight', 0)))} analog units",
        },
    ]


def build_risk_heatmap(packet, threat_index: int, active_mode: str):
    base = clamp(threat_index / 100, 0, 1)
    mode_bias = {"PATROL": 0.05, "SURVEILLANCE": 0.1, "STEALTH": 0.16, "ALERT": 0.24}.get(active_mode, 0.08)
    thermal = clamp((float(packet.get("tempC", 0)) - 28) / 18, 0, 1)
    humidity = clamp((float(packet.get("humidity", 0)) - 40) / 40, 0, 1)
    motion = clamp(float(packet.get("motionDetected", 0)), 0, 1)
    low_light = clamp((260 - float(packet.get("ambientLight", 1023))) / 260, 0, 1)

    grid = []
    for row in range(4):
        row_values = []
        for col in range(4):
            spatial_bias = ((row + 1) * 0.04) + ((col + 1) * 0.03)
            value = clamp(base * 0.4 + thermal * 0.16 + humidity * 0.1 + motion * 0.18 + low_light * 0.08 + spatial_bias + mode_bias, 0, 1)
            row_values.append(round(value, 2))
        grid.append(row_values)
    return grid


def build_geo_intel(packet, history: List[Dict[str, object]], threat_index: int):
    recent = history[-12:]
    trail = []
    for idx, sample in enumerate(recent):
        ambient = float(sample.get("ambientLight", 0))
        motion = float(sample.get("motionDetected", 0))
        temp = float(sample.get("tempC", 0))
        humidity = float(sample.get("humidity", 0))
        x = clamp(ambient / 1023, 0, 1)
        y = clamp((temp + humidity / 4) / 65, 0, 1)
        trail.append({
            "lat": x + idx * 0.0004,
            "lng": y + (0.0012 if motion > 0 else 0.0002),
            "threat": clamp(compute_threat_index(sample), 0, 100),
        })
    return {
        "center": {"lat": trail[-1]["lat"] if trail else 0.5, "lng": trail[-1]["lng"] if trail else 0.5},
        "trail": trail,
        "zoneRadiusMeters": round(40 + threat_index * 2.4),
        "headingDeg": 90 if float(packet.get("motionDetected", 0)) > 0 else 35,
    }


def build_actions(active_mode, recommended_mode, fault_label, anomalies, battery_forecast, packet):
    actions = []
    if recommended_mode != active_mode:
        actions.append(
            {
                "title": f"Switch to {recommended_mode}",
                "detail": f"Backend controller recommends {recommended_mode} based on faults and mission stress.",
                "level": "high" if recommended_mode == "ALERT" else "medium",
            }
        )
    if fault_label == "POWER_FAULT":
        actions.append(
            {
                "title": "Shed non-critical load",
                "detail": "Power fault classification indicates the load is unsustainable.",
                "level": "medium",
            }
        )
    if battery_forecast and battery_forecast < 45:
        actions.append(
            {
                "title": "Preserve reserve power",
                "detail": f"Estimated time to 20 percent battery is {battery_forecast} minutes.",
                "level": "medium",
            }
        )
    if float(packet.get("motionDetected", 0)) > 0 and float(packet.get("ambientLight", 1023)) < 220:
        actions.append(
            {
                "title": "Engage low-light intrusion response",
                "detail": "PIR activity has been detected under low ambient light conditions.",
                "level": "medium",
            }
        )
    if float(packet.get("ambientLight", 1023)) < 180:
        actions.append(
            {
                "title": "Switch to night-watch profile",
                "detail": "Low KY-018 light level suggests low-visibility monitoring conditions.",
                "level": "low",
            }
        )
    if anomalies and not actions:
        actions.append(
            {
                "title": "Inspect anomaly spike",
                "detail": anomalies[0]["description"],
                "level": "low",
            }
        )
    if not actions:
        actions.append(
            {
                "title": "Maintain mission profile",
                "detail": "Current telemetry is within the learned control envelope.",
                "level": "low",
            }
        )
    return actions


def estimate_battery_pct(batt_v: float) -> int:
    return round(clamp((batt_v - 10.8) / (13.0 - 10.8) * 100, 0, 100))


def classify_light_band(light_level: float) -> str:
    if light_level < 140:
        return "Dark"
    if light_level < 320:
        return "Dim"
    if light_level < 700:
        return "Guarded"
    return "Bright"


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


if __name__ == "__main__":
    start_serial_thread()
    app.run(host="127.0.0.1", port=5001, debug=False)
