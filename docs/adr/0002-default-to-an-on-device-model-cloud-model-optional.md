# ADR-0002: Default to an on-device model; cloud model optional

**Status:** accepted · 27 Nov 2026

## Context
The target is a laptop with a 4 GB GTX 1650 and 3.7 GB of WSL memory. The Anthropic API account had no credits, and a warehouse should not stop working when the internet does.

## Decision
Qwen 2.5 3B via Ollama on the GPU is the default backend (1.9 GB, fully on GPU, kept resident for 60 min, warmed up at start). Claude is used only if a real test call succeeds; a rule-based agent is the last fallback. Selection is automatic (`AMR_AGENT_BACKEND=auto`).

## Consequences
Free, offline, about 1–2 s per request. A 3B model is too weak for a free-form tool loop (2–5/10 on held-out requests, with unsafe actions), which forced ADR-0003.
