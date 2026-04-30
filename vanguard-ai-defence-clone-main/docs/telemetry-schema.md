# Telemetry Schema

The UI expects one JSON object per line from the Arduino over USB serial at `115200`.

Live hardware schema for your actual sensors:

```json
{
  "ts": 1714411273000,
  "unitId": "ALPHA-01",
  "battV": 12.4,
  "battPct": 86,
  "loadW": 24.0,
  "tempC": 31.5,
  "humidity": 42,
  "currentA": 1.9,
  "ambientLight": 640,
  "motionDetected": 1,
  "mode": "PATROL"
}
```

Sensor mapping:

- `battV`: `0-25V DC voltage sensor`
- `currentA`: `ACS712`
- `loadW`: derived as `battV * currentA`
- `tempC`, `humidity`: `DHT11`
- `ambientLight`: `KY-018`
- `motionDetected`: `HC-SR501`

Optional simulation-only overlay fields for demo mode:

```json
{
  "simSolarW": 22,
  "simSmokePpm": 5
}
```

Notes:

- live mode should only send real sensors plus honest derived values
- simulation overlay fields are optional and must be described as simulated
- `ESP32` is not required by the UI data path and can stay dedicated to LCD-side work
