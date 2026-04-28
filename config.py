"""
config.py

Central configuration for the Hybrid LLM-Based Self-Healing Framework.
All values are read from environment variables / .env file with safe defaults.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# LLM provider
# ---------------------------------------------------------------------------

# "openai" or "anthropic"
LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "openai")

OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

# Model IDs — override per provider if needed
OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o")
ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

# ---------------------------------------------------------------------------
# Playwright browser settings
# ---------------------------------------------------------------------------

# chromium | firefox | webkit
BROWSER: str = os.getenv("BROWSER", "chromium")
HEADLESS: bool = os.getenv("HEADLESS", "true").lower() == "true"
SLOW_MO: int = int(os.getenv("SLOW_MO", "0"))
DEFAULT_TIMEOUT: int = int(os.getenv("DEFAULT_TIMEOUT", "10000"))

# ---------------------------------------------------------------------------
# Self-healing pipeline
# ---------------------------------------------------------------------------

# Healing strategy: none | heuristic | llm_only | hybrid
HEALING_MODE: str = os.getenv("HEALING_MODE", "heuristic")

# Maximum total LLM-backed healing attempts per action
MAX_HEAL_ATTEMPTS: int = int(os.getenv("MAX_HEAL_ATTEMPTS", "3"))

# Maximum number of LLM-generated candidates to validate and try
MAX_LLM_CANDIDATES: int = int(os.getenv("MAX_LLM_CANDIDATES", "5"))

# Minimum DOM-similarity score to accept a candidate
MIN_SIMILARITY_SCORE: float = float(os.getenv("MIN_SIMILARITY_SCORE", "0.35"))

# Whether to persist successful repairs
ENABLE_REPAIR_MEMORY: bool = os.getenv("ENABLE_REPAIR_MEMORY", "true").lower() == "true"

# Save screenshot on failure
CAPTURE_SCREENSHOT_ON_FAILURE: bool = (
    os.getenv("CAPTURE_SCREENSHOT_ON_FAILURE", "false").lower() == "true"
)

# ---------------------------------------------------------------------------
# Heuristic engine tuning
# ---------------------------------------------------------------------------

# Number of ranked heuristic candidates to validate on live page
MAX_HEURISTIC_VALIDATE: int = int(os.getenv("MAX_HEURISTIC_VALIDATE", "12"))

# Number of validated heuristic candidates to actually try
MAX_HEURISTIC_TRY: int = int(os.getenv("MAX_HEURISTIC_TRY", "4"))

# Timeout used while validating heuristic candidates
HEURISTIC_VALIDATE_TIMEOUT: int = int(os.getenv("HEURISTIC_VALIDATE_TIMEOUT", "1500"))

# Minimum final score required for heuristic acceptance
MIN_HEURISTIC_SCORE: float = float(os.getenv("MIN_HEURISTIC_SCORE", "0.45"))

# ---------------------------------------------------------------------------
# Risk / evaluation thresholds
# ---------------------------------------------------------------------------

# Minimum acceptable winning score for a healed candidate
LOW_SCORE_THRESHOLD: float = float(os.getenv("LOW_SCORE_THRESHOLD", "0.85"))

# Minimum acceptable margin between top and second candidate scores
LOW_MARGIN_THRESHOLD: float = float(os.getenv("LOW_MARGIN_THRESHOLD", "0.03"))

# Repairs that take longer than this are flagged as slow
SLOW_REPAIR_THRESHOLD_SEC: float = float(os.getenv("SLOW_REPAIR_THRESHOLD_SEC", "3.0"))

# ---------------------------------------------------------------------------
# Evaluation / experiment logging
# ---------------------------------------------------------------------------

# Save per-action healing results
ENABLE_EXPERIMENT_LOGGING: bool = (
    os.getenv("ENABLE_EXPERIMENT_LOGGING", "true").lower() == "true"
)

# Save only failed repairs
LOG_ONLY_FAILURES: bool = os.getenv("LOG_ONLY_FAILURES", "false").lower() == "true"

# ---------------------------------------------------------------------------
# Filesystem paths
# ---------------------------------------------------------------------------

BASE_DIR: str = os.path.dirname(os.path.abspath(__file__))
LOG_DIR: str = os.path.join(BASE_DIR, "logs")
DATA_DIR: str = os.path.join(BASE_DIR, "data")

RESULTS_PATH: str = os.path.join(LOG_DIR, "results.json")
REPAIR_MEMORY_PATH: str = os.path.join(LOG_DIR, "repair_memory.json")
EXPERIMENT_LOG_PATH: str = os.path.join(LOG_DIR, "experiment_log.json")

# Ensure required directories exist
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)