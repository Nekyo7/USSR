# APIS Expo UI

Fresh standalone repo for your tech expo demo.

## What it does

- uses a brand-new codebase with no dependency on your previous projects
- treats the Arduino as the only compute source from hardware
- connects the browser directly to Arduino serial using Web Serial
- includes demo mode for rehearsals using the same telemetry schema
- uses Flask handlers as the analytics and control backend
- exposes MQTT topics for broker-based integration

## Real analytics included

- operational-state decision tree trained on synthetic random mission data
- fault-classification decision tree trained on synthetic random mission data
- rolling anomaly detection using z-score deviation
- fused threat index from temperature, humidity, battery/load stress, PIR activity, and ambient light
- battery depletion forecast using linear trend estimation
- telemetry confidence scoring based on packet freshness and live sensor completeness
- stealth mode relay scheduling with duty-cycle windows
- action feed generated from current operational state
- night-watch and low-light intrusion logic from HC-SR501 + KY-018
- power draw estimation from ACS712 + DC voltage sensing

## Run

```bash
cd /Users/uditsinghi/Documents/New\ project/apis-expo-ui
python3 -m pip install -r backend/requirements.txt
python3 backend/app.py
```

Open `http://127.0.0.1:5001`.

Do not use `npm run dev` for the full demo path. The Flask backend is the real runtime because it serves the dashboard, reads Arduino serial, runs analytics, and streams telemetry to the browser.

## Live Arduino Serial

The backend reads Arduino JSON lines over USB serial using PySerial.

Defaults:

- port: `COM4`
- baud rate: `9600`

Override them if needed:

```bash
APIS_SERIAL_PORT=COM5 APIS_BAUD_RATE=9600 python3 backend/app.py
```

On Windows PowerShell:

```powershell
$env:APIS_SERIAL_PORT="COM5"
$env:APIS_BAUD_RATE="9600"
python backend/app.py
```

When you click `Connect Arduino`, the dashboard connects to Flask's `/api/serial-stream` endpoint. If that endpoint is unavailable, the browser falls back to direct Web Serial mode in Chrome or Edge.

The backend accepts both the recommended JSON format and the current Arduino sketch's labeled serial line format:

```text
Temp: 31.5 | Humidity: 42 | Light: 640 | Voltage: 12.40 | Current: 1.90 | Motion: 1
```

## Demo tomorrow

1. Start with `Run Demo Stream` so the judges immediately see motion.
2. Then switch to `Connect Arduino` and select your Arduino serial port in Chrome or Edge.
3. Make sure your Arduino prints one JSON packet per line using the schema in [docs/telemetry-schema.md](./docs/telemetry-schema.md).
4. Keep the ESP32 only for LCD-side work; it is not required for the UI to function.
5. Live mode should use only your real sensors: ACS712, HC-SR501, DHT11, KY-018, and the 0-25V voltage sensor.
6. Scenario overlay values such as simulated solar or smoke should be described as simulated future expansion, not live hardware.

Model notes are in [docs/ai-models.md](./docs/ai-models.md), and MQTT topics are in [docs/mqtt-schema.md](./docs/mqtt-schema.md).
