# ADR-0005: Exact branch-and-bound order sequencing on Nav2 path lengths

**Status:** accepted · 27 Nov 2026

## Context
Multi-item requests need an order of pick and drop stops. Straight-line distance is misleading in racked aisles; requests are small (2–7 orders).

## Decision
Pickup-and-delivery with capacity and precedence, solved exactly by depth-first branch-and-bound with state-dominance pruning for ≤ 7 orders (verified against brute force in tests), greedy plus local search beyond that. Distances are lengths of Nav2 global plans between stations, cached.

## Consequences
Measured 22–51 % less driving than one-at-a-time on live requests, in about 0.3 s. Exponential worst case is bounded by the 7-order limit.
