"""Small pairwise linear ranker; trained scores are not probabilities."""
from __future__ import annotations

import json
import math
import random
from pathlib import Path

from .corpus import duplicate_groups, fingerprint


FEATURES = ("primary_msc", "secondary_msc", "lexical", "semantic", "abstract_support", "technical_depth", "audience_breadth")
DEFAULT_WEIGHTS = dict(zip(FEATURES, (.32, .08, .40, 0., .05, .03, .02)))
FOCUS_FEATURES = FEATURES + ("primary_focus", "secondary_focus")
FOCUS_WEIGHTS = dict(zip(FOCUS_FEATURES, (.12, .03, .25, 0., .02, .05, .03, .42, .08)))
FEATURE_SCHEMAS = {1: FEATURES, 2: FOCUS_FEATURES}


def schema_weights(version):
    if version not in FEATURE_SCHEMAS:
        raise ValueError("Unsupported feature schema version")
    return dict(FOCUS_WEIGHTS if version == 2 else DEFAULT_WEIGHTS)


def default_contributions(features):
    focused = bool(features.get("focus_available"))
    weights = schema_weights(2 if focused else 1)
    if features.get("semantic_available"):
        weights.update(lexical=.11 if focused else .25, semantic=.14 if focused else .15)
    return {name: weight * features.get(name, 0) for name, weight in weights.items()}


def feature_vector(values, features=FEATURES):
    result = [float(values.get(name, 0)) for name in features]
    if not all(math.isfinite(v) and 0 <= v <= 1 for v in result):
        raise ValueError("Ranker features must be finite values between zero and one")
    return result


class LinearReranker:
    def __init__(self, weights=None, metadata=None, feature_schema_version=1):
        self.feature_schema_version = feature_schema_version
        defaults = schema_weights(feature_schema_version)
        self.features = FEATURE_SCHEMAS[feature_schema_version]
        self.weights = dict(defaults if weights is None else weights)
        self.metadata = metadata or {}
        if set(self.weights) != set(self.features) or not all(math.isfinite(float(w)) for w in self.weights.values()):
            raise ValueError("Ranker feature schema or weights are invalid")

    def contributions(self, features):
        vector = feature_vector(features, self.features)
        return {name: self.weights[name] * value for name, value in zip(self.features, vector)}

    def score(self, features):
        return sum(self.contributions(features).values())

    def save(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps({"schema_version": self.feature_schema_version, "features": list(self.features), "weights": self.weights,
                                         "metadata": self.metadata, "score_semantics": "relative preference; not calibrated probability"}, indent=2) + "\n")

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text())
        version = data.get("schema_version")
        if version not in FEATURE_SCHEMAS or data.get("features") != list(FEATURE_SCHEMAS[version]):
            raise ValueError("Unsupported ranker schema; regenerate candidate features and retrain with the current matcher")
        return cls(data["weights"], data.get("metadata"), version)


def validate_dataset(data):
    version = data.get("feature_schema_version", 1)
    schema_weights(version)
    features = FEATURE_SCHEMAS[version]
    train, validation = data.get("train", []), data.get("validation", [])
    if not train or not validation:
        raise ValueError("Training requires separate nonempty train and validation sets")
    all_rows = train + validation
    ids = [row.get("paper_id") for row in all_rows]
    if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        raise ValueError("Training and validation paper IDs must be unique")
    for group in duplicate_groups(all_rows):
        if any(i < len(train) for i in group) and any(i >= len(train) for i in group):
            raise ValueError("A paper/version appears in both training and validation")
    for split, rows in (("train", train), ("validation", validation)):
        for row in rows:
            if row.get("split") != split:
                raise ValueError("Explicit split field must match the dataset partition")
            candidates = row.get("candidates", [])
            journal_ids = [c.get("journal_id") for c in candidates]
            if len(journal_ids) != len(set(journal_ids)) or any(not i for i in journal_ids):
                raise ValueError("Candidate journal IDs must be unique and nonempty")
            for candidate in candidates:
                values = candidate["features"]
                if version == 1 and any(name in values for name in ("primary_focus", "secondary_focus")):
                    raise ValueError("Focused features require feature_schema_version 2")
                if version == 2 and not all(name in values for name in ("primary_focus", "secondary_focus")):
                    raise ValueError("Focused training requires both focus features; regenerate the annotation export")
                feature_vector(values, features)
                if candidate.get("judged") is True:
                    relevance = candidate.get("relevance")
                    if isinstance(relevance, bool) or not isinstance(relevance, (int, float)) or not math.isfinite(relevance) or not 0 <= relevance <= 3:
                        raise ValueError("Explicit judgments require relevance from 0 to 3")
    return train, validation


def preference_pairs(rows, features=FEATURES):
    pairs = []
    for row in rows:
        # Omitted journals and unjudged candidates never become negatives.
        judged = [c for c in row["candidates"] if c.get("judged") is True]
        local = []
        for positive in judged:
            for negative in judged:
                if positive["relevance"] > negative["relevance"]:
                    high, low = feature_vector(positive["features"], features), feature_vector(negative["features"], features)
                    local.append([a - b for a, b in zip(high, low)])
        # Normalize each manuscript's contribution instead of overweighting
        # papers with many labeled candidate pairs.
        pairs.extend((delta, 1 / len(local)) for delta in local)
    return pairs


def pairwise_accuracy(model, rows):
    pairs = preference_pairs(rows, model.features)
    denominator = sum(weight for _, weight in pairs)
    return sum(weight * (1 if sum(model.weights[f] * d for f, d in zip(model.features, delta)) > 0 else .5
                         if sum(model.weights[f] * d for f, d in zip(model.features, delta)) == 0 else 0)
               for delta, weight in pairs) / denominator if denominator else None


def train_ranker(data, epochs=200, learning_rate=.2, l2=.01, seed=0):
    if epochs <= 0 or not math.isfinite(learning_rate) or learning_rate <= 0 or not math.isfinite(l2) or l2 < 0:
        raise ValueError("Invalid training hyperparameters")
    train, validation = validate_dataset(data)
    version = data.get("feature_schema_version", 1)
    features = FEATURE_SCHEMAS[version]
    defaults = schema_weights(version)
    pairs = preference_pairs(train, features)
    if not pairs or not preference_pairs(validation, features):
        raise ValueError("Train and validation need explicit unequal-relevance judgments; unlabeled venues are not negatives")
    weights = [defaults[name] for name in features]
    rng = random.Random(seed)
    for _ in range(epochs):
        rng.shuffle(pairs)
        gradient = [0.0] * len(features)
        total = sum(weight for _, weight in pairs)
        for delta, weight in pairs:
            margin = sum(w * d for w, d in zip(weights, delta))
            factor = 1 / (1 + math.exp(max(-40, min(40, margin))))
            for i, d in enumerate(delta):
                gradient[i] += weight * factor * d / total
        weights = [w + learning_rate * (g - l2 * w) for w, g in zip(weights, gradient)]
    metadata = {"training_sha256": fingerprint(train), "validation_sha256": fingerprint(validation),
                "training_papers": len(train), "validation_papers": len(validation), "training_pairs": len(pairs),
                "epochs": epochs, "learning_rate": learning_rate, "l2": l2, "seed": seed,
                "label_policy": "explicit judged relevance only; unjudged candidates excluded",
                "label_provenance": data.get("label_provenance", "unspecified; inspect before deployment")}
    metadata["feature_schema_version"] = version
    model = LinearReranker(dict(zip(features, weights)), metadata, version)
    metadata["validation_pairwise_accuracy"] = pairwise_accuracy(model, validation)
    metadata["baseline_validation_pairwise_accuracy"] = pairwise_accuracy(LinearReranker(feature_schema_version=version), validation)
    return model
