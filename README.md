# Hybrid-LLM-Based-Self-Healing-Framework
A hybrid LLM-based self-healing framework for automated web UI testing, combining heuristic DOM analysis, memory, and intent-aware validation to achieve high-precision locator repair.

## Evaluation Suites

- Official controlled evaluation: `pytest tests/test_registration_healing.py tests/ecommerce_suite -s` (45 tests).
- Extended real-world converted dataset: `tests/selene_converted`, kept separate for scalability and generalization experiments.
