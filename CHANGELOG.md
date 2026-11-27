# Changelog

## v1.0.0 — 27 Nov 2026

First complete release: racked warehouse, on-device agentic layer with verifiers, live operations dashboard, CI.

### Added
- Racked warehouse generated from one layout script (6 bays, 1.8 m aisles, packing, shipping, charging); SLAM map v4.
- Live operations dashboard (map, robot, Nav2 plan, activity feed, KPIs, command box) on http://localhost:8765.
- Grounding verifiers for products, destinations and charge commands; held-out v2 benchmark set.
- Demo recorder and GIF renderer; architecture, safety case, ADRs and runbook; Apache-2.0 licence.
- CI: unit tests and ROS 2 Jazzy colcon build on every push; `scripts/setup.sh`.

### Results
- Hybrid on-device agent: dev 11/12, held-out v1 9/10, held-out v2 10/10, 0 unsafe actions.
- Route optimiser: 22–51 % less driving than one-at-a-time on live requests.

## v0.5 — speed
- Nav2 cruise 0.2 → 0.45 m/s; time-to-collision braking; model kept resident and warmed up.
- Same delivery 97 s → 45 s; agent overhead ≈ 51 s cold → 2–5 s.

## v0.4 — on-device agent
- Ollama backend (Qwen 2.5 3B on a 4 GB GPU); hybrid intent agent with constrained decoding and a product verifier.
- Benchmark with dev and held-out sets and an unsafe-action metric.

## v0.3 — agentic layer
- `amr_interfaces`, `amr_tasks` (mission executor, exact order scheduler on Nav2 path lengths),
  `amr_agent` (Claude tool-use agent, rule fallback, chat CLI, ROS topic node).

## v0.2 — mapping, localization, navigation
- Odometry calibrated (`wheel_separation_multiplier` 1.096; drift 1.3 m → 3 cm per lap).
- SLAM map, AMCL, Nav2 with footprint, collision monitor; obstacle avoidance verified.

## v0.1 — controllers
- Fixed controllers not activating on Jazzy (controller manager received an empty `/robot_description`).
