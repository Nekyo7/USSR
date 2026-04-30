# MQTT Schema

These topics complement the dashboard and Flask backend. The UI can still run without MQTT, but this is the schema if you want broker-based integration.

## Topics

- `apis/unit/{unitId}/telemetry`
  Device to backend telemetry packets from Arduino-side computation.
- `apis/unit/{unitId}/mode/set`
  Backend to device mode control messages.
- `apis/unit/{unitId}/relay/schedule`
  Backend-generated relay duty-cycle windows, especially for stealth mode.
- `apis/unit/{unitId}/faults`
  Backend fault classification and active flags for subscribers.

## Why this matches your hardware

- Arduino remains the compute source for sensor fusion and field logic.
- Flask backend performs dashboard-side ML classification and control recommendation.
- ESP32 can remain dedicated to the LCD path and does not need to own inference.
