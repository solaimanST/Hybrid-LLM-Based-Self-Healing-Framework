# 🚀 Hybrid LLM-Based Self-Healing Framework for Web UI Testing

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-blue.svg" />
  <img src="https://img.shields.io/badge/Playwright-Automation-green.svg" />
  <img src="https://img.shields.io/badge/Pytest-Testing-orange.svg" />
  <img src="https://img.shields.io/badge/Status-Research--Ready-success.svg" />
  <img src="https://img.shields.io/badge/License-MIT-yellow.svg" />
</p>

<p align="center">
  <b>Precision-first self-healing framework for automated UI testing</b><br />
  Combining heuristics, memory, and LLM reasoning to eliminate false repairs.
</p>

---

## ✨ Overview

Modern UI tests frequently break due to minor DOM changes.  
Traditional self-healing systems often **repair incorrectly**, which can hide real application bugs.

This framework introduces a **precision-first hybrid approach** that:

- Repairs broken locators intelligently
- Ensures actions are **semantically correct**
- Validates that the repaired element matches the original user intent
- Verifies that the UI **state actually changes** after execution

> ✅ A repair is accepted only if it produces a **verified outcome**.

---

## 🧠 Research Contribution

This framework introduces a new direction for **self-healing UI testing**:

- Intent-aware locator repair instead of simple similarity matching
- Hybrid healing using heuristics, memory, and LLM reasoning
- Post-action verification to confirm behavioral correctness
- Precision-first decision strategy
- False repair prevention through state validation

> ❌ Traditional approach: “Find a similar element”  
> ✅ This framework: “Find the correct element and verify the correct behavior”

---

## 📊 Experimental Results

| Metric | Value |
|---|---:|
| Total Tests | 45 |
| Passed | 45 |
| Success Rate | 100% |
| False Repairs | 0 |

---

## 🌍 Validated Domains

### 🧾 Registration Workflow

- Form filling
- Checkbox interaction
- Submit validation

### 🛒 E-commerce Workflow
- Add to cart
- Remove item
- Checkout process
- Continue shopping
- Sorting functionality

---

## 🔧 Break Types Covered

The framework has been evaluated against common UI locator failures, including:

- ID changes
- Class changes
- Attribute removal
- DOM restructuring
- Nested layout changes
- Sibling insertion
- Element relocation

---

## ⚙️ Tech Stack

- 🐍 Python
- 🎭 Playwright
- 🧪 Pytest
- 🤖 LLM Integration

---

## 🚀 Setup

Install project dependencies:

```bash
pip install -r requirements.txt
```

Install Playwright browsers:

```bash
python -m playwright install
```

---

## ▶️ Run Tests

Run the registration and e-commerce healing test suites:

```bash
pytest tests/test_registration_healing.py tests/ecommerce_suite -s
```

---

## 📁 Project Structure

```text
engine/        → Core self-healing logic
validator/     → Action and locator validation
dom/           → DOM extraction and analysis
llm/           → LLM-based repair components
tests/         → Evaluation suites
utils/         → Logging and metrics
```

---

## 🧩 Framework Flow

```text
Original selector
      ↓
Generate repair candidates
      ↓
Score candidates
      ↓
Validate locator and action compatibility
      ↓
Execute healed action
      ↓
Verify UI state change
      ↓
Log repair result
```

---

## 🛡️ Precision-First Validation

The framework avoids unsafe repairs by rejecting candidates when:

- The element tag is incompatible with the intended action
- Multiple elements match the repaired locator
- The element is hidden or disabled
- The confidence score is too low
- The score margin between candidates is too small
- The action does not produce the expected UI state change

This ensures that the framework prefers **failure over incorrect healing**.

---

## 📦 Release

### v0.1.0 — Initial Research Release

- 45/45 tests passed
- Zero false repairs
- Multi-domain validation completed
- Precision-first healing strategy implemented
- Post-action verification supported

---

## 📌 Status

- 🟢 Research-ready prototype
- 🟢 Suitable for academic publication
- 🟢 Extendable for large-scale datasets
- 🟢 Designed for precision-first UI test repair

---

## 🔮 Future Work

- Expand dataset to 100+ real-world test cases
- Benchmark against existing self-healing frameworks
- Integrate advanced LLM reasoning strategies
- Add CI/CD integration support
- Build a UI dashboard for repair visualization
- Optimize performance for large-scale test suites

---

## 📄 License

This project is licensed under the **MIT License**.

---

## 👨‍💻 Author

**Muhammad Solaiman**
