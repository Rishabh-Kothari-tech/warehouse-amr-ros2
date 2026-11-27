# ADR-0007: Generate the world and the station list from one layout

**Status:** accepted · 27 Nov 2026

## Context
Hand-editing the Webots world and `stations.yaml` separately lets pick poses drift away from racks.

## Decision
`scripts/generate_warehouse_world.py` holds the layout (walls, rack bays, aisles, fixtures, inventory) and writes both files. Rack bays include floor-level pallet faces so the 2D LiDAR maps them as solid.

## Consequences
Layout changes are one edit plus a re-map. Generated files are marked as generated.
