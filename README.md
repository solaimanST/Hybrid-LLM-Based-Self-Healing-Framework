# 🚀 Hybrid LLM-Based Self-Healing Framework for Web UI Testing

<p align="center">
<b>Precision-First Hybrid Approach for Reliable UI Test Self-Healing</b><br />
</p>

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

## ⚡ Quick Start

```bash
git clone https://github.com/solaimanST/Hybrid-LLM-Based-Self-Healing-Framework
cd Hybrid-LLM-Based-Self-Healing-Framework
pip install -r requirements.txt
python -m playwright install
pytest tests/test_registration_healing.py tests/ecommerce_suite tests/selene_converted -s
```

---

## ✨ Overview

This work focuses on eliminating false repairs in automated UI testing by ensuring that every healed action produces a verifiable and correct behavioral outcome.
Modern UI tests frequently break due to minor DOM changes.
Traditional self-healing systems often **repair incorrectly**, hiding real application bugs.

This framework introduces a **precision-first hybrid approach** that:

* Repairs broken locators intelligently
* Ensures actions are **semantically correct**
* Validates user intent
* Verifies that UI **state actually changes**

> ✅ A repair is accepted only if it produces a **verified outcome**

---

## 🧠 Research Contribution

This framework introduces a new direction for **self-healing UI testing**:

* Intent-aware locator repair (beyond similarity matching)
* Hybrid healing using heuristics + memory + LLM reasoning
* Post-action verification to confirm behavioral correctness
* Precision-first decision strategy
* Elimination of false repairs

> ❌ Traditional: “Find similar element”  
> ✅ This work: “Find correct element and verify correct behavior”

---

## 📊 Experimental Results

| Dataset | Tests | Result |
|---|---:|---|
| Registration suite | 5 | 5 passed |
| E-commerce suite | 60 | 60 passed |
| Selene-converted suite | 39 | 39 passed |
| **Combined evaluation** | **104** | **104 passed (100%)** |

---

## 🧪 Evaluation Setup

The evaluation dataset consists of:

- 5 registration tests
- 60 e-commerce workflow tests
- 39 converted real-world tests

All tests include both normal and broken locator scenarios to evaluate self-healing robustness under realistic UI changes.

---

## 🌍 Validated Domains

### 🧾 Registration Workflow

* Form filling
* Checkbox interaction
* Submit validation

### 🛒 E-commerce Workflow

* Add to cart
* Remove item
* Checkout process
* Continue shopping
* Sorting functionality

### 🔄 Converted Real-World Tests

* Element finding
* Collections handling
* Visibility validation
* Form interactions

---

## 🔧 Break Types Covered

* ID changes
* Class changes
* Attribute removal
* DOM restructuring
* Nested layout changes
* Sibling insertion
* Element relocation
* Text ambiguity
* Role/semantic mismatches

---

## ⚙️ Tech Stack

* 🐍 Python
* 🎭 Playwright
* 🧪 Pytest
* 🤖 LLM Integration

---

## 🚀 Setup

Install dependencies:

```bash
pip install -r requirements.txt
```

Install Playwright browsers:

```bash
python -m playwright install
```

---

## ▶️ Run Tests

Run full evaluation:

```bash
pytest tests/test_registration_healing.py tests/ecommerce_suite tests/selene_converted -s
```

Run only official evaluation:

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
tests/
  ├── test_registration_healing.py
  ├── ecommerce_suite/
  └── selene_converted/
utils/         → Logging and metrics
```

---

## 🧩 Framework Flow

```text
Original Selector
      ↓
Generate Candidates
      ↓
Score & Rank Candidates
      ↓
Intent-Aware Validation
      ↓
Execute Action
      ↓
Verify UI State Change
      ↓
Accept or Reject Repair
```

---

## 🛡️ Precision-First Validation

The framework rejects unsafe repairs when:

* Element type does not match intended action
* Multiple elements match the selector
* Element is hidden or disabled
* Confidence score is too low
* Score margin is too small
* No observable UI state change occurs

👉 The system prefers **failure over incorrect healing**

---

## 🎬 Demo

*(Add screenshot or GIF of test execution here)*

---

## 📦 Release

### v0.2.0 — Expanded Research Evaluation

* Expanded dataset from 45 → 104 tests
* Achieved 104/104 passing tests
* Stabilized converted real-world dataset
* Maintained zero false-repair principle
* Improved evaluation coverage and robustness

---

## 📌 Status

* 🟢 Research-ready
* 🟢 Suitable for academic publication
* 🟢 High-precision self-healing framework
* 🟢 Scalable evaluation dataset

---

## 🔮 Future Work

* Expand dataset to 150+ tests
* Benchmark against baseline methods
* Add CI/CD integration
* Improve LLM reasoning strategies
* Build UI dashboard for repair visualization
* Optimize runtime performance

---

## 📄 License

MIT License

---

## 👨‍💻 Author

**Muhammad Solaiman**

---

## ⭐ Support

If you find this work useful, consider giving it a ⭐
to support research in AI-driven software testing.
