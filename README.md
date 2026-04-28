# Hybrid LLM-Based Self-Healing Framework for Web UI Testing

A research-oriented hybrid framework for automatic repair of broken web UI test locators using heuristic DOM analysis, memory, and intent-aware validation.

## Key Features

- Hybrid healing pipeline: Heuristic + LLM + Memory
- Intent-aware action validation for Add, Remove, Continue, Checkout, and sorting actions
- Precision-first click repair to prevent wrong element interactions
- Post-action state verification to confirm correct UI behavior
- Supports `click`, `fill`, `select_option`, and `expect_visible`
- Handles real-world UI break types:
  - ID changes
  - Class changes
  - Attribute removal
  - DOM restructuring
  - Nested layout changes

## Results

| Metric | Value |
|---|---:|
| Total Tests | 45 |
| Passed | 45 |
| Success Rate | 100% |
| False Repair Failures | 0 |

Verified across:

- Registration workflow: form filling, checkbox, submit
- E-commerce workflow: add/remove cart, checkout, continue shopping, sorting

## Core Idea

Traditional self-healing test frameworks can select elements that look similar but perform the wrong action.

This framework accepts a repaired action only when it satisfies:

1. Unique element resolution
2. Action compatibility
3. Semantic intent matching
4. Verified post-action state change

## Architecture

```text
Test
  ↓
SelfHealer
  ↓
Candidate Generation
  ↓
Intent-Aware Validation
  ↓
Action Execution
  ↓
Post-Action State Verification
  ↓
Final Decision
