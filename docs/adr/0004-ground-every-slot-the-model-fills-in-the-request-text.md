# ADR-0004: Ground every slot the model fills in the request text

**Status:** accepted · 27 Nov 2026

## Context
Constrained decoding guarantees a *valid* answer, not the *right* one. Live failures: a hallucinated two-item delivery from "top it up", a wrong destination ("to shipping" went to packing), and invented destinations and a charge command after a harmless change to the station list.

## Decision
Code verifies each slot: every product must share a word stem with the request (one retry with the error explained, then refuse and ask); a destination stated after to/at/into/for overrides the model and unstated destinations are dropped; a charge command needs charging words and must not be a question.

## Consequences
0 unsafe actions on all 32 benchmark requests. Failures now end in a refusal instead of a wrong mission. Lexical checks refuse some valid paraphrases (safe failure). Every live failure became a regression test.
