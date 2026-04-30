# AI And ML Features

These are real, explainable models in the expo stack. They do not pretend to be cloud AI or a large model.

Important:

- the two decision trees are trained on synthetic random mission data because you specifically asked for random-data training
- this must be presented honestly to judges as simulation-trained logic, not field-trained production intelligence

## 1. Rolling anomaly detector

- Method: rolling z-score on live telemetry windows
- Inputs: battery, temperature, vibration, current, signal strength
- Output: which signal has deviated from its recent baseline

## 2. Battery depletion forecaster

- Method: linear regression on recent battery percentage history
- Inputs: time-ordered battery samples
- Output: estimated minutes until 20 percent battery

## 3. Operational state classifier

- Method: nearest-centroid classification
- Inputs: battery risk, thermal risk, vibration risk, current risk, signal penalty, enclosure tamper state
- Output: `Stable`, `Strained`, or `Compromised`

## 4. Threat fusion model

- Method: weighted multi-sensor scoring
- Inputs: thermal, vibration, current, signal, smoke, tamper, and power stress indicators
- Output: threat index from 0 to 100

## 5. Fault classifier

- Method: decision tree classifier
- Training data: synthetic random mission samples with rule-based labels
- Output: `NO_FAULT`, `POWER_FAULT`, `THERMAL_FAULT`, `SIGNAL_FAULT`, or `TAMPER_FAULT`

## Why this is not fake AI

- every model runs locally and deterministically
- every output is traceable to live sensor inputs
- no random text generation is used
- no internet or cloud inference is required
- the same models work on demo data and live Arduino data
