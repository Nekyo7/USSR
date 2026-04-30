# Hardware Flow

Expo-safe architecture for your setup:

1. Sensors feed the Arduino.
2. Arduino performs all computation, filtering, thresholds, and any onboard fusion you already built.
3. Arduino emits newline-delimited JSON over USB serial.
4. The browser UI connects directly to the Arduino using Web Serial.
5. Flask backend computes higher-level analytics and control logic:
   - synthetic-random-trained decision tree state classification
   - synthetic-random-trained decision tree fault detection
   - rolling anomaly detection
   - threat fusion index
   - battery depletion forecast
   - signal confidence score
   - stealth relay scheduling
   - mission guidance feed
6. ESP32 remains out of the compute path and can continue handling LCD-side duties only.

This separation is good for the expo because it makes the story easy:

- hardware intelligence is real and runs on Arduino
- UI analytics are real and run in-browser
- no fake cloud AI is needed
- demo mode uses the same schema as live mode
