# ADR-0006: Time-to-collision braking instead of a fixed slowdown zone

**Status:** accepted · 27 Nov 2026

## Context
Raising cruise speed from 0.2 to 0.45 m/s needs earlier braking (≈ 0.25 m at 0.4 m/s²). A fixed 0.8 m slowdown circle made the robot crawl at every pick face (≈ 0.45 m from shelves) and trip the progress checker: 122 s missions and two aborts.

## Decision
Nav2 collision monitor `approach` action on the robot footprint with a 1.2 s time-to-collision horizon, plus the 0.40 m stop zone.

## Consequences
Full speed in open aisles, normal docking at shelves: the same delivery went from 97 s to 45 s with 0 aborts; obstacle test at speed kept ≈ 0.38 m bumper clearance.
