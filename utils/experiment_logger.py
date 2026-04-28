"""
utils/experiment_logger.py

Append-only JSON Lines (JSONL) logger for healing experiment events.

Each call to append_experiment_log() writes exactly ONE line to the log file
(a JSON-encoded dict followed by a newline). This is O(1) per write regardless
of how many entries already exist — no full-file reads, no full-file rewrites.

To load all entries for analysis:
    import json
    records = [json.loads(l) for l in open(path) if l.strip()]
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config

_lock = threading.Lock()
_log_path = Path(config.EXPERIMENT_LOG_PATH).with_suffix(".jsonl")


def append_experiment_log(entry: dict[str, Any]) -> None:
    """
    Append one healing event to the JSONL log.

    Thread-safe. Does nothing when experiment logging is disabled or
    when LOG_ONLY_FAILURES=True and the entry succeeded.
    """
    if not config.ENABLE_EXPERIMENT_LOGGING:
        return
    if config.LOG_ONLY_FAILURES and entry.get("success", False):
        return

    record = {**entry, "timestamp": _now()}

    _log_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False) + "\n"

    with _lock:
        with _log_path.open("a", encoding="utf-8") as fh:
            fh.write(line)


def load_experiment_log() -> list[dict[str, Any]]:
    """Return all persisted records as a list of dicts."""
    if not _log_path.exists():
        return []
    records: list[dict[str, Any]] = []
    with _log_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
