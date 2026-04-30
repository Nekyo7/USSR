/*
  Reference serializer for your actual sensor set:
  - ACS712
  - HC-SR501
  - DHT11
  - KY-018
  - 0-25V DC voltage sensor

  Keep your own wiring and sensor reads.
  The UI only needs one JSON object per line.
*/

unsigned long lastPacket = 0;

void setup() {
  Serial.begin(115200);
}

void loop() {
  if (millis() - lastPacket < 900) {
    return;
  }
  lastPacket = millis();

  // Replace these with your real sensor values.
  float battV = 12.3;
  int battPct = 82;
  float currentA = 1.90;
  float loadW = battV * currentA;
  float tempC = 32.1;
  float humidity = 44.0;
  int ambientLight = 540;
  int motionDetected = 1;
  const char* mode = "PATROL";

  Serial.print("{\"ts\":");
  Serial.print(millis());
  Serial.print(",\"unitId\":\"ALPHA-01\"");
  Serial.print(",\"battV\":");
  Serial.print(battV, 2);
  Serial.print(",\"battPct\":");
  Serial.print(battPct);
  Serial.print(",\"loadW\":");
  Serial.print(loadW, 1);
  Serial.print(",\"tempC\":");
  Serial.print(tempC, 1);
  Serial.print(",\"humidity\":");
  Serial.print(humidity, 1);
  Serial.print(",\"currentA\":");
  Serial.print(currentA, 2);
  Serial.print(",\"ambientLight\":");
  Serial.print(ambientLight);
  Serial.print(",\"motionDetected\":");
  Serial.print(motionDetected);
  Serial.print(",\"mode\":\"");
  Serial.print(mode);
  Serial.println("\"}");
}
