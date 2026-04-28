"""
utils/evaluation_summary.py

Reads the experiment log produced by append_experiment_log() and prints
a clean evaluation summary for self-healing runs.

Usage:
    python utils/evaluation_summary.py

Optional:
    python utils/evaluation_summary.py --log logs/experiment_log.json
    python utils/evaluation_summary.py --log logs/experiment_log.json --save
    python utils/evaluation_summary.py --log logs/experiment_log.json --save --out logs/evaluation_summary.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from typing import Any

import config

# ---------------------------------------------------------------------
# Thresholds — sourced from config so they stay consistent with the
# values the healer uses at runtime.
# ---------------------------------------------------------------------
LOW_MARGIN_THRESHOLD: float = config.LOW_MARGIN_THRESHOLD
LOW_SCORE_THRESHOLD: float = config.LOW_SCORE_THRESHOLD
SLOW_REPAIR_THRESHOLD_SEC: float = config.SLOW_REPAIR_THRESHOLD_SEC


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_mean(values: list[float]) -> float:
    return round(mean(values), 4) if values else 0.0


def load_entries(log_path: str) -> list[dict]:
    path = Path(log_path)
    if not path.exists():
        raise FileNotFoundError(f"Log file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError("Experiment log must be a JSON list of entries.")

    return data


def classify_risk_flags(entry: dict) -> list[str]:
    flags: list[str] = []

    source = str(entry.get("source", ""))
    if source == "original":
        return flags

    winning_score = safe_float(entry.get("winning_score"))
    score_margin = safe_float(entry.get("score_margin"))
    repair_time = safe_float(entry.get("repair_time_sec"))

    if winning_score < LOW_SCORE_THRESHOLD:
        flags.append("low_score")

    if score_margin < LOW_MARGIN_THRESHOLD:
        flags.append("low_margin")

    if repair_time > SLOW_REPAIR_THRESHOLD_SEC:
        flags.append("slow_repair")

    return flags


def build_case_view(entry: dict) -> dict:
    return {
        "action": entry.get("action", ""),
        "description": entry.get("description", ""),
        "original_selector": entry.get("original_selector", ""),
        "healed_selector": entry.get("healed_selector"),
        "source": entry.get("source", ""),
        "success": bool(entry.get("success", False)),
        "winning_score": round(safe_float(entry.get("winning_score")), 4),
        "top_score": round(safe_float(entry.get("top_score")), 4),
        "second_score": round(safe_float(entry.get("second_score")), 4),
        "score_margin": round(safe_float(entry.get("score_margin")), 4),
        "repair_time_sec": round(safe_float(entry.get("repair_time_sec")), 4),
        "risk_flags": classify_risk_flags(entry),
        "page_url": entry.get("page_url", ""),
        "timestamp": entry.get("timestamp", ""),
    }


# ---------------------------------------------------------------------
# Summary logic
# ---------------------------------------------------------------------
def summarize(entries: list[dict]) -> tuple[dict, list[dict]]:
    total_actions = len(entries)

    original_entries = [e for e in entries if e.get("source") == "original"]
    healed_entries = [e for e in entries if e.get("source") not in ("original", "", None)]
    failed_entries = [e for e in entries if not bool(e.get("success", False))]
    success_entries = [e for e in entries if bool(e.get("success", False))]

    healed_success_entries = [
        e for e in healed_entries if bool(e.get("success", False))
    ]

    repair_times_all = [safe_float(e.get("repair_time_sec")) for e in entries]
    repair_times_original = [safe_float(e.get("repair_time_sec")) for e in original_entries]
    repair_times_healed = [safe_float(e.get("repair_time_sec")) for e in healed_success_entries]

    winning_scores = [safe_float(e.get("winning_score")) for e in healed_success_entries]
    score_margins = [safe_float(e.get("score_margin")) for e in healed_success_entries]

    low_margin_cases = [
        build_case_view(e)
        for e in healed_success_entries
        if safe_float(e.get("score_margin")) < LOW_MARGIN_THRESHOLD
    ]

    low_score_cases = [
        build_case_view(e)
        for e in healed_success_entries
        if safe_float(e.get("winning_score")) < LOW_SCORE_THRESHOLD
    ]

    risky_cases = [
        build_case_view(e)
        for e in healed_success_entries
        if classify_risk_flags(e)
    ]

    risky_cases_sorted = sorted(
        risky_cases,
        key=lambda x: (
            len(x["risk_flags"]) == 0,
            x["winning_score"],
            x["score_margin"],
            -x["repair_time_sec"],
        ),
    )

    weakest_by_score = sorted(
        [build_case_view(e) for e in healed_success_entries],
        key=lambda x: x["winning_score"],
    )[:5]

    weakest_by_margin = sorted(
        [build_case_view(e) for e in healed_success_entries],
        key=lambda x: x["score_margin"],
    )[:5]

    slowest_repairs = sorted(
        [build_case_view(e) for e in healed_success_entries],
        key=lambda x: x["repair_time_sec"],
        reverse=True,
    )[:5]

    summary = {
        "thresholds": {
            "low_score_threshold": LOW_SCORE_THRESHOLD,
            "low_margin_threshold": LOW_MARGIN_THRESHOLD,
            "slow_repair_threshold_sec": SLOW_REPAIR_THRESHOLD_SEC,
        },
        "totals": {
            "total_actions": total_actions,
            "successful_actions": len(success_entries),
            "failed_actions": len(failed_entries),
            "original_successes": len(original_entries),
            "healed_attempts": len(healed_entries),
            "healed_successes": len(healed_success_entries),
        },
        "rates": {
            "overall_success_rate_pct": round(
                (len(success_entries) / total_actions) * 100, 2
            ) if total_actions else 0.0,
            "heal_success_rate_pct": round(
                (len(healed_success_entries) / len(healed_entries)) * 100, 2
            ) if healed_entries else 0.0,
        },
        "timing": {
            "avg_repair_time_sec": safe_mean(repair_times_all),
            "avg_original_time_sec": safe_mean(repair_times_original),
            "avg_healed_time_sec": safe_mean(repair_times_healed),
            "max_healed_time_sec": round(max(repair_times_healed), 4) if repair_times_healed else 0.0,
            "min_healed_time_sec": round(min(repair_times_healed), 4) if repair_times_healed else 0.0,
        },
        "scores": {
            "avg_winning_score": safe_mean(winning_scores),
            "min_winning_score": round(min(winning_scores), 4) if winning_scores else 0.0,
            "max_winning_score": round(max(winning_scores), 4) if winning_scores else 0.0,
            "avg_score_margin": safe_mean(score_margins),
            "min_score_margin": round(min(score_margins), 4) if score_margins else 0.0,
            "max_score_margin": round(max(score_margins), 4) if score_margins else 0.0,
        },
        "risk_counts": {
            "low_score_case_count": len(low_score_cases),
            "low_margin_case_count": len(low_margin_cases),
            "risky_case_count": len(risky_cases_sorted),
        },
        "weakest_cases_by_score": weakest_by_score,
        "weakest_cases_by_margin": weakest_by_margin,
        "slowest_healed_cases": slowest_repairs,
    }

    return summary, risky_cases_sorted


# ---------------------------------------------------------------------
# Printing
# ---------------------------------------------------------------------
def print_summary(summary: dict, risky_cases: list[dict]) -> None:
    totals = summary["totals"]
    rates = summary["rates"]
    timing = summary["timing"]
    scores = summary["scores"]
    risk_counts = summary["risk_counts"]
    thresholds = summary["thresholds"]

    print("\n===== Evaluation Summary =====")
    print(f"Total actions              : {totals['total_actions']}")
    print(f"Successful actions         : {totals['successful_actions']}")
    print(f"Failed actions             : {totals['failed_actions']}")
    print(f"Original successes         : {totals['original_successes']}")
    print(f"Healed attempts            : {totals['healed_attempts']}")
    print(f"Healed successes           : {totals['healed_successes']}")
    print(f"Overall success rate       : {rates['overall_success_rate_pct']}%")
    print(f"Heal success rate          : {rates['heal_success_rate_pct']}%")

    print("\n----- Timing -----")
    print(f"Average repair time        : {timing['avg_repair_time_sec']} sec")
    print(f"Average original time      : {timing['avg_original_time_sec']} sec")
    print(f"Average healed time        : {timing['avg_healed_time_sec']} sec")
    print(f"Fastest healed case        : {timing['min_healed_time_sec']} sec")
    print(f"Slowest healed case        : {timing['max_healed_time_sec']} sec")

    print("\n----- Scores -----")
    print(f"Average winning score      : {scores['avg_winning_score']}")
    print(f"Minimum winning score      : {scores['min_winning_score']}")
    print(f"Maximum winning score      : {scores['max_winning_score']}")
    print(f"Average score margin       : {scores['avg_score_margin']}")
    print(f"Minimum score margin       : {scores['min_score_margin']}")
    print(f"Maximum score margin       : {scores['max_score_margin']}")

    print("\n----- Risk Counts -----")
    print(f"Low-score cases            : {risk_counts['low_score_case_count']}")
    print(f"Low-margin cases           : {risk_counts['low_margin_case_count']}")
    print(f"Risky healed cases         : {risk_counts['risky_case_count']}")

    print("\n----- Thresholds -----")
    print(f"Low score threshold        : {thresholds['low_score_threshold']}")
    print(f"Low margin threshold       : {thresholds['low_margin_threshold']}")
    print(f"Slow repair threshold      : {thresholds['slow_repair_threshold_sec']} sec")

    if risky_cases:
        print("\n===== Risky Healed Cases =====")
        for i, case in enumerate(risky_cases, start=1):
            print(
                f"{i}. action={case['action']} | "
                f"description={case['description']} | "
                f"original={case['original_selector']} | "
                f"healed={case['healed_selector']} | "
                f"score={case['winning_score']:.4f} | "
                f"margin={case['score_margin']:.4f} | "
                f"time={case['repair_time_sec']:.4f}s | "
                f"flags={','.join(case['risk_flags']) if case['risk_flags'] else 'none'}"
            )
    else:
        print("\nNo risky healed cases found.")

    print("\n===== Weakest Cases by Score =====")
    for i, case in enumerate(summary["weakest_cases_by_score"], start=1):
        print(
            f"{i}. {case['description']} | {case['original_selector']} -> {case['healed_selector']} | "
            f"score={case['winning_score']:.4f} | margin={case['score_margin']:.4f}"
        )

    print("\n===== Weakest Cases by Margin =====")
    for i, case in enumerate(summary["weakest_cases_by_margin"], start=1):
        print(
            f"{i}. {case['description']} | {case['original_selector']} -> {case['healed_selector']} | "
            f"score={case['winning_score']:.4f} | margin={case['score_margin']:.4f}"
        )

    print("\n===== Slowest Healed Cases =====")
    for i, case in enumerate(summary["slowest_healed_cases"], start=1):
        print(
            f"{i}. {case['description']} | {case['original_selector']} -> {case['healed_selector']} | "
            f"time={case['repair_time_sec']:.4f}s | score={case['winning_score']:.4f}"
        )


# ---------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------
def save_summary(summary: dict, risky_cases: list[dict], out_path: str) -> None:
    payload = {
        "summary": summary,
        "risky_cases": risky_cases,
    }

    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize self-healing experiment logs.")
    parser.add_argument(
        "--log",
        default="logs/experiment_log.json",
        help="Path to the experiment log JSON file.",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save summary to JSON file.",
    )
    parser.add_argument(
        "--out",
        default="logs/evaluation_summary.json",
        help="Output path for saved summary JSON.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    entries = load_entries(args.log)
    summary, risky_cases = summarize(entries)
    print_summary(summary, risky_cases)

    if args.save:
        save_summary(summary, risky_cases, args.out)
        print(f"\nSaved summary to: {args.out}")


if __name__ == "__main__":
    main()