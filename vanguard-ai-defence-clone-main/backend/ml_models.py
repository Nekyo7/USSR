from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, List, Tuple


FEATURE_ORDER = [
    "battPct",
    "battV",
    "tempC",
    "humidity",
    "currentA",
    "loadW",
    "ambientLight",
    "motionDetected",
]


@dataclass
class TreeNode:
    feature: str | None = None
    threshold: float | None = None
    left: "TreeNode | None" = None
    right: "TreeNode | None" = None
    label: str | None = None
    counts: Dict[str, int] | None = None


class DecisionTreeClassifier:
    def __init__(self, max_depth: int = 5, min_samples_split: int = 20):
        self.max_depth = max_depth
        self.min_samples_split = min_samples_split
        self.root: TreeNode | None = None

    def fit(self, rows: List[Dict[str, float]], labels: List[str]) -> None:
        dataset = []
        for row, label in zip(rows, labels):
            sample = {feature: float(row.get(feature, 0.0)) for feature in FEATURE_ORDER}
            sample["_label"] = label
            dataset.append(sample)
        self.root = self._build(dataset, depth=0)

    def predict(self, row: Dict[str, float]) -> str:
        label, _trace, _probs = self.predict_details(row)
        return label

    def predict_with_trace(self, row: Dict[str, float]) -> Tuple[str, List[str]]:
        label, trace, _probs = self.predict_details(row)
        return label, trace

    def predict_details(self, row: Dict[str, float]) -> Tuple[str, List[str], Dict[str, float]]:
        if self.root is None:
            raise RuntimeError("Model has not been trained")

        trace: List[str] = []
        node = self.root
        while node.label is None:
            value = float(row.get(node.feature or "", 0.0))
            direction = "left" if value <= float(node.threshold) else "right"
            trace.append(f"{node.feature} {'<=' if direction == 'left' else '>'} {node.threshold:.2f} (value {value:.2f})")
            node = node.left if direction == "left" else node.right
            if node is None:
                break

        if node is None or node.label is None:
            return "UNKNOWN", trace, {}
        trace.append(f"leaf -> {node.label}")
        counts = node.counts or {}
        total = sum(counts.values()) or 1
        probabilities = {
            label: round((count / total) * 100, 1)
            for label, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)
        }
        return node.label, trace, probabilities

    def _build(self, dataset: List[Dict[str, float]], depth: int) -> TreeNode:
        labels = [row["_label"] for row in dataset]
        counts = self._counts(labels)
        majority_label = max(counts, key=counts.get)

        if depth >= self.max_depth or len(dataset) < self.min_samples_split or len(counts) == 1:
            return TreeNode(label=majority_label, counts=counts)

        split = self._best_split(dataset)
        if split is None:
            return TreeNode(label=majority_label, counts=counts)

        feature, threshold, left_rows, right_rows = split
        return TreeNode(
            feature=feature,
            threshold=threshold,
            left=self._build(left_rows, depth + 1),
            right=self._build(right_rows, depth + 1),
            counts=counts,
        )

    def _best_split(self, dataset: List[Dict[str, float]]):
        base_impurity = self._gini([row["_label"] for row in dataset])
        best_gain = 0.0
        best = None

        for feature in FEATURE_ORDER:
            values = sorted({row[feature] for row in dataset})
            if len(values) < 2:
                continue
            thresholds = self._candidate_thresholds(values)
            for threshold in thresholds:
                left_rows = [row for row in dataset if row[feature] <= threshold]
                right_rows = [row for row in dataset if row[feature] > threshold]
                if not left_rows or not right_rows:
                    continue
                weighted = (
                    len(left_rows) / len(dataset) * self._gini([row["_label"] for row in left_rows])
                    + len(right_rows) / len(dataset) * self._gini([row["_label"] for row in right_rows])
                )
                gain = base_impurity - weighted
                if gain > best_gain:
                    best_gain = gain
                    best = (feature, threshold, left_rows, right_rows)
        return best

    @staticmethod
    def _candidate_thresholds(values: List[float]) -> List[float]:
        if len(values) <= 14:
            return [(values[idx] + values[idx + 1]) / 2.0 for idx in range(len(values) - 1)]
        step = max(1, len(values) // 12)
        picked = []
        for idx in range(step, len(values) - 1, step):
            picked.append((values[idx] + values[idx + 1]) / 2.0)
        return picked or [(values[0] + values[-1]) / 2.0]

    @staticmethod
    def _gini(labels: List[str]) -> float:
        counts = DecisionTreeClassifier._counts(labels)
        total = len(labels) or 1
        return 1.0 - sum((count / total) ** 2 for count in counts.values())

    @staticmethod
    def _counts(labels: List[str]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for label in labels:
            counts[label] = counts.get(label, 0) + 1
        return counts


def _generate_sample(rng: random.Random) -> Dict[str, float]:
    batt_v = rng.uniform(10.8, 13.1)
    current = rng.uniform(0.15, 3.2)
    light = rng.uniform(35, 990)
    return {
        "battPct": rng.uniform(12, 98),
        "battV": batt_v,
        "tempC": rng.uniform(23, 44),
        "humidity": rng.uniform(28, 88),
        "currentA": current,
        "loadW": batt_v * current,
        "ambientLight": light,
        "motionDetected": float(rng.choice([0, 0, 0, 1, 1])),
    }


def _operational_label(sample: Dict[str, float]) -> str:
    stress = 0
    stress += 2 if sample["battPct"] < 28 else 1 if sample["battPct"] < 50 else 0
    stress += 2 if sample["tempC"] > 39 else 1 if sample["tempC"] > 34 else 0
    stress += 1 if sample["humidity"] > 75 else 0
    stress += 2 if sample["loadW"] > 26 else 1 if sample["loadW"] > 18 else 0
    stress += 2 if sample["motionDetected"] > 0 and sample["ambientLight"] < 240 else 1 if sample["motionDetected"] > 0 else 0
    if stress >= 7:
        return "COMPROMISED"
    if stress >= 3:
        return "STRAINED"
    return "STABLE"


def _fault_label(sample: Dict[str, float]) -> str:
    if sample["motionDetected"] > 0 and sample["ambientLight"] < 220:
        return "INTRUSION_ALERT"
    if sample["tempC"] > 40:
        return "THERMAL_FAULT"
    if sample["battPct"] < 25 or sample["loadW"] > 28:
        return "POWER_FAULT"
    if sample["ambientLight"] < 60 and sample["motionDetected"] == 0 and sample["battPct"] > 40:
        return "LOW_VISIBILITY_WATCH"
    return "NO_FAULT"


def train_models(seed: int = 7) -> Dict[str, object]:
    rng = random.Random(seed)
    samples = [_generate_sample(rng) for _ in range(320)]
    operational_labels = [_operational_label(sample) for sample in samples]
    fault_labels = [_fault_label(sample) for sample in samples]

    operational_tree = DecisionTreeClassifier(max_depth=5, min_samples_split=18)
    operational_tree.fit(samples, operational_labels)

    fault_tree = DecisionTreeClassifier(max_depth=5, min_samples_split=18)
    fault_tree.fit(samples, fault_labels)

    return {
        "training": {
            "type": "synthetic_random",
            "seed": seed,
            "samples": len(samples),
            "features": FEATURE_ORDER,
        },
        "operational_tree": operational_tree,
        "fault_tree": fault_tree,
    }
