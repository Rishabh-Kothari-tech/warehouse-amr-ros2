# ADR-0001: Put a mission layer between the AI and the robot

**Status:** accepted · 27 Nov 2026

## Context
An LLM agent could in principle call Nav2 or publish velocities directly. Language models make confident mistakes, and robot motion is the expensive place to discover them.

## Decision
The agent only calls `amr_tasks` services and the `ExecuteMission` action. `warehouse_manager` validates every mission (stock at that shelf, capacity, drop only what is carried, charger only, battery floor) before the robot moves, and owns all Nav2 interaction.

## Consequences
The agent can be swapped (Claude, local model, rules) without touching navigation. Validation lives in one place and is unit-tested. Cost: one more node and a custom interface package (`amr_interfaces`).
