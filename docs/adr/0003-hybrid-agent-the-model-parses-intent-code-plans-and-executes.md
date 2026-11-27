# ADR-0003: Hybrid agent: the model parses intent, code plans and executes

**Status:** accepted · 27 Nov 2026

## Context
In a free-form tool loop the 3B model described plans without calling `execute_mission`, claimed deliveries that never happened, and executed wrong missions.

## Decision
One model call per request returns a JSON intent (deliver / goto / charge / status / inventory / cancel) under Ollama's grammar-constrained decoding, with a schema generated from the live inventory so SKUs and stations are enums. Planning, the battery rule and execution are deterministic code.

## Consequences
Held-out accuracy went from 2/10 (free-form) to 9–10/10, 4–8 model calls per request became one. Less flexible than a free-form agent for open-ended requests; new task types need a new intent. Claude still uses the full tool loop.
