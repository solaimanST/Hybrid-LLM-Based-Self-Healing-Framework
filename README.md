# Hybrid LLM-Based Self-Healing Framework for Web UI Testing

A research-oriented hybrid framework for automatic repair of broken web UI test locators using a combination of heuristic DOM analysis, memory, and intent-aware validation.

---

## 🚀 Key Features

- Hybrid healing pipeline (Heuristic + LLM + Memory)
- Intent-aware action validation (Add, Remove, Continue, Checkout, etc.)
- Precision-first click repair (prevents wrong element interactions)
- Post-action state verification (ensures correct UI behavior)
- Supports:
  - click
  - fill
  - select_option
  - expect_visible
- Handles real-world UI break types:
  - ID changes
  - class changes
  - attribute removal
  - DOM restructuring
  - nested layout changes

---

## 📊 Results

| Metric | Value |
|------|------|
| Total Tests | 45 |
| Passed | 45 |
| Success Rate | 100% |
| False Repairs | 0 |

✔ Verified across:
- Registration workflow (form + checkbox + submit)
- E-commerce workflow (cart, checkout, sorting, navigation)

---

## 🧠 Core Idea

Traditional self-healing frameworks often select **wrong but similar elements**.

This framework solves that by:

- enforcing **semantic intent matching**
- requiring **unique element resolution**
- validating **post-action state change**

A repair is accepted **only if the UI actually changes as expected**.

---

## 🏗️ Architecture
Test → SelfHealer → Heuristic Engine → Candidate Filtering
→ Intent Validation → Action Execution
→ State Verification → Final Decision

---

## 🛠️ Tech Stack

- Python
- Playwright
- Pytest

---

## ⚙️ Setup

```bash
pip install -r requirements.txt
python -m playwright install

## ⚙️ Run Test

pytest tests/test_registration_healing.py tests/ecommerce_suite -s

## ⚙️ Project Structure

engine/        → core healing logic
validator/     → action + result validation
dom/           → DOM extraction & analysis
llm/           → LLM-based repair
tests/         → evaluation suites

## ⚙️ Status

Research-ready prototype.

Designed for:

academic research
experimentation with UI test robustness
extension into larger datasets
