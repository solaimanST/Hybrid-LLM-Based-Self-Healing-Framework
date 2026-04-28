---
name: hybrid-self-healing
description: Build, debug, and document a precision-first self-healing framework
allowed-tools: Bash(pytest:*) Bash(python:*)
---

# MODE DETECTION

Detect user intent:

- "fix", "error", "failed", "pytest" → DEBUG MODE
- "write", "paper", "thesis", "method", "evaluation" → PAPER MODE
- otherwise → DEV MODE

---

# GLOBAL RULES

- Precision > Recall  
- Never accept wrong healing  
- No site-specific hacks  
- Prefer failure over incorrect action  

---

# CORE FILES

- engine/self_healer.py  
- engine/heuristic_engine.py  
- engine/heuristic_generator.py  
- validator/locator_validator.py  
- dom/dom_analyzer.py  

---

# DEV MODE (default)

## Flow

1. original selector  
2. generate candidates  
3. score  
4. validate  
5. execute  
6. verify  
7. log  

---

## Action Rules

- fill → input, textarea  
- select → select  
- click → button, input[type=submit], a, label  

Reject:
- large div/span  
- non-interactive  
- long text containers  

---

## Scoring

Must satisfy:

- perfect → 1.0  
- zero → 0.0  
- balanced → ~0.5  

Priority:

- attribute (HIGH)  
- tag (HIGH)  
- structure (HIGH)  
- text (LOW)  

---

## Context (CRITICAL)

Use:
- parent tag  
- sibling overlap  

---

## Validation

Reject if:

- wrong tag  
- multiple matches  
- hidden/disabled  
- low score / low margin  

---

## Ranking

Sort by:

1. final_score  
2. uniqueness  
3. confidence  

---

## False Repair

- fill → value must match  
- click → URL or DOM must change  

---

# DEBUG MODE

## Goal

Fix all failing tests.

---

## Steps

1. run pytest  
2. find failure  
3. identify cause  
4. fix logic  
5. repeat  

---

## Fix Priority

1. scoring  
2. wrong element selection  
3. validation  
4. ranking  
5. missing functions  

---

## Key Fixes

- correct scoring math  
- ensure best candidate is used  
- prevent container selection  
- penalize wrong links (<a>)  
- restore missing APIs  

---

## Rules

- no hardcoding  
- no bypassing validation  
- keep system generic  

---

# PAPER MODE

## Structure

1. Introduction  
2. Related Work  
3. Method  
4. Evaluation  
5. Conclusion  

---

## Method

Explain:

- hybrid healing (heuristic + LLM)  
- candidate generation  
- scoring system  
- validation rules  
- false repair detection  

---

## Evaluation

Include:

- total cases  
- broken selectors  
- success rate  
- false repair rate  
- repair time  

Compare:

- rule-based vs hybrid  

---

## Writing Rules

- clear and simple  
- technical, no fluff  
- focus on contribution  

---

# LOGGING

Always log:

- original + healed selector  
- score  
- margin  
- candidate count  
- false_repair  
- time  

---

# PERFORMANCE

- extract DOM once  
- limit candidates  
- avoid repeated parsing  

---

# DO NOT

- ❌ hardcode sites  
- ❌ trust text only  
- ❌ accept low margin  
- ❌ prioritize recall  