"""
utils/metrics.py

Compute precision, recall, F1, and latency statistics from the experiment log.

A "healed" event is a true positive if success=True and source != "original".
A false positive is any healed result flagged false_repair=True.
A false negative is any result where success=False.

Usage:
    from utils.metrics import compute_metrics
    report = compute_metrics()
    print(report)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import config

_LOG_PATH = Path(config.EXPERIMENT_LOG_PATH).with_suffix(".jsonl")


def compute_metrics(log_path: Path | None = None) -> dict[str, Any]:
    records = _load(log_path or _LOG_PATH)
    if not records:
        return {"error": "no records found"}

    healed      = [r for r in records if r.get("success") and r.get("source") != "original"]
    original_ok = [r for r in records if r.get("source") == "original"]
    failed      = [r for r in records if not r.get("success")]
    false_pos   = [r for r in healed if r.get("false_repair")]
    ambiguous   = [
        r for r in healed
        if r.get("score_margin", 1.0) < config.LOW_MARGIN_THRESHOLD
    ]
    low_score   = [
        r for r in healed
        if r.get("winning_score", 1.0) < config.LOW_SCORE_THRESHOLD
    ]

    total       = len(records)
    tp          = len(healed) - len(false_pos)
    fp          = len(false_pos)
    fn          = len(failed)

    precision   = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall      = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1          = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0 else 0.0
    )

    latencies = [r["repair_time_sec"] for r in healed if "repair_time_sec" in r]
    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
    p95_latency = _percentile(latencies, 95) if latencies else 0.0

    by_source: dict[str, int] = {}
    for r in healed:
        src = r.get("source", "unknown")
        by_source[src] = by_source.get(src, 0) + 1

    by_stage: dict[str, dict] = {}
    for r in records:
        stage = _infer_stage(r)
        entry = by_stage.setdefault(stage, {"total": 0, "success": 0})
        entry["total"] += 1
        if r.get("success"):
            entry["success"] += 1

    return {
        "total_actions":      total,
        "original_success":   len(original_ok),
        "healed":             len(healed),
        "failed":             len(failed),
        "false_positives":    fp,
        "ambiguous_heals":    len(ambiguous),
        "low_score_heals":    len(low_score),
        "precision":          round(precision, 4),
        "recall":             round(recall, 4),
        "f1":                 round(f1, 4),
        "avg_heal_latency_s": round(avg_latency, 4),
        "p95_heal_latency_s": round(p95_latency, 4),
        "by_source":          by_source,
        "by_stage":           by_stage,
    }


def print_metrics_report(log_path: Path | None = None) -> None:
    m = compute_metrics(log_path)
    if "error" in m:
        print(f"Metrics: {m['error']}")
        return
    print(f"\n{'='*50}")
    print(f"  Healing Framework — Evaluation Metrics")
    print(f"{'='*50}")
    print(f"  Total actions:        {m['total_actions']}")
    print(f"  Passed originally:    {m['original_success']}")
    print(f"  Healed successfully:  {m['healed']}")
    print(f"  Failed:               {m['failed']}")
    print(f"  False positives:      {m['false_positives']}")
    print(f"  Ambiguous heals:      {m['ambiguous_heals']}  (margin < {config.LOW_MARGIN_THRESHOLD})")
    print(f"  Low-score heals:      {m['low_score_heals']}  (score < {config.LOW_SCORE_THRESHOLD})")
    print(f"{'='*50}")
    print(f"  Precision:            {m['precision']:.4f}")
    print(f"  Recall:               {m['recall']:.4f}")
    print(f"  F1:                   {m['f1']:.4f}")
    print(f"  Avg heal latency:     {m['avg_heal_latency_s']:.3f}s")
    print(f"  P95 heal latency:     {m['p95_heal_latency_s']:.3f}s")
    print(f"\n  By source:  {m['by_source']}")
    print(f"  By stage:   {m['by_stage']}")
    print(f"{'='*50}\n")


def _load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records


def _percentile(data: list[float], p: int) -> float:
    if not data:
        return 0.0
    sorted_data = sorted(data)
    idx = max(0, int(len(sorted_data) * p / 100) - 1)
    return sorted_data[idx]


def _infer_stage(record: dict) -> str:
    source = record.get("source", "")
    if source == "original":
        return "stage_0"
    if source in {"heuristic", "memory"}:
        return "stage_1"
    if source == "llm":
        return "stage_2"
    return "failed"
