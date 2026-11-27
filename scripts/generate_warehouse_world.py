#!/usr/bin/env python3
"""Generate the Webots warehouse world and the matching station file from ONE layout definition.

    python3 scripts/generate_warehouse_world.py

Writes src/amr_simulation/worlds/warehouse.wbt (keeping the robot definition from the existing file)
and src/amr_tasks/config/stations.yaml. World frame = map frame: the robot spawns at the origin
facing +x, and SLAM/AMCL put the map origin at the spawn pose.

Layout (metres), 12 x 10 m building, walls at x = +-6, y = +-5:

    y=5  ┌──────────────────────────────────────────────┐
         │  [ rack_A1 ]      [ rack_A2 ]       ▣ pillar │
         │   aisle A (y=2.6)                  packing ■ │
         │  [ rack_B1 ]      [ rack_B2 ]                │
         │   aisle B (y=0)   ● robot spawn              │
         │  [ rack_C1 ]      [ rack_C2 ]                │
         │ ⚡   south cross area (y=-3.4)      shipping ■│
    y=-5 └──────────────────────────────────────────────┘
        x=-6   W bays x[-4.4,-1.6]  E bays x[0,2.8]     x=6
"""
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORLD = ROOT / 'src/amr_simulation/worlds/warehouse.wbt'
STATIONS = ROOT / 'src/amr_tasks/config/stations.yaml'

HALF_X, HALF_Y, WALL_T, WALL_H = 6.0, 5.0, 0.15, 1.2
RACK_LEN, RACK_DEPTH, RACK_H = 2.8, 0.8, 1.8
BAYS_X = {'1': -3.0, '2': 1.4}                    # west / east bay centres
ROWS_Y = {'A': 3.9, 'B': 1.3, 'C': -1.3}          # rack row centres -> aisles at y = 2.6, 0.0 and south area
PICK_Y = {'A': 2.6, 'B': 0.0, 'C': -2.6}          # robot pick pose: aisle centre, facing the rack (north)
INVENTORY = {
    'rack_A1': ['bolts_m8', 'nuts_m8', 'washers_m8'],
    'rack_A2': ['bearings_6204', 'oil_seals', 'circlips'],
    'rack_B1': ['cable_ties', 'wiring_harness', 'connectors'],
    'rack_B2': ['motor_controller', 'hall_sensors', 'bms_board'],
    'rack_C1': ['brake_pads', 'disc_rotors', 'brake_fluid'],
    'rack_C2': ['battery_cells', 'cell_holders', 'nickel_strips'],
}
# (name, type, pose x, y, yaw_deg, fixture centre x, y, size x, y, z, colour)
FIXTURES = [
    ('packing_station', 'packing', 4.0, 2.6, 0, 5.3, 2.6, 0.8, 1.4, 0.9, (0.15, 0.6, 0.3)),
    ('shipping_dock', 'shipping', 4.0, -3.4, 0, 5.3, -3.4, 0.8, 1.4, 0.9, (0.2, 0.45, 0.75)),
    ('charging_dock', 'charger', -4.7, -3.4, 180, -5.7, -3.4, 0.3, 0.6, 0.5, (0.95, 0.8, 0.1)),
]
PILLARS = [(3.6, 4.2), (-2.4, -4.1)]


def box_solid(name, x, y, sx, sy, sz, rgb, z0=0.0, rough=0.7):
    r, g, b = rgb
    return f'''Solid {{
  translation {x:.3f} {y:.3f} {z0 + sz / 2:.3f}
  children [
    Shape {{
      appearance PBRAppearance {{ baseColor {r} {g} {b} roughness {rough} metalness 0 }}
      geometry Box {{ size {sx:.3f} {sy:.3f} {sz:.3f} }}
    }}
  ]
  name "{name}"
  boundingObject Box {{ size {sx:.3f} {sy:.3f} {sz:.3f} }}
}}
'''


def rack(name, x, y):
    """Collision box for the whole rack, plus visual uprights and shelf beams."""
    beams = ''.join(f'''    Pose {{ translation 0 0 {h - RACK_H / 2:.2f} children [ Shape {{ appearance PBRAppearance {{ baseColor 0.9 0.45 0.1 roughness 0.5 }} geometry Box {{ size {RACK_LEN:.2f} {RACK_DEPTH + 0.02:.2f} 0.05 }} }} ] }}
''' for h in (0.35, 0.9, 1.45, 1.78))
    uprights = ''.join(f'''    Pose {{ translation {dx:.2f} {dy:.2f} 0 children [ Shape {{ appearance PBRAppearance {{ baseColor 0.1 0.25 0.6 roughness 0.4 }} geometry Box {{ size 0.08 0.08 {RACK_H:.2f} }} }} ] }}
''' for dx in (-RACK_LEN / 2 + 0.04, 0, RACK_LEN / 2 - 0.04) for dy in (-RACK_DEPTH / 2 + 0.04, RACK_DEPTH / 2 - 0.04))
    cartons = ''.join(f'''    Pose {{ translation {dx:.2f} 0 {h - RACK_H / 2 + 0.2:.2f} children [ Shape {{ appearance PBRAppearance {{ baseColor 0.72 0.55 0.35 roughness 0.9 }} geometry Box {{ size 0.5 0.55 0.35 }} }} ] }}
''' for dx in (-0.9, 0.0, 0.9) for h in (0.35, 0.9, 1.45))
    # Floor-level pallet loads: a solid face from 0 to 0.45 m. Webots' LiDAR ray-casts against visible geometry,
    # and at the scanner height (0.27 m) an empty rack is only thin uprights, so SLAM mapped racks as dots and
    # Nav2 would plan through them. Real racked warehouses have the same 2D-LiDAR blind spot.
    pallets = f'''    Pose {{ translation 0 0 {0.225 - RACK_H / 2:.3f} children [ Shape {{ appearance PBRAppearance {{ baseColor 0.6 0.45 0.28 roughness 0.9 }} geometry Box {{ size {RACK_LEN - 0.06:.2f} {RACK_DEPTH - 0.04:.2f} 0.45 }} }} ] }}
'''
    return f'''Solid {{
  translation {x:.3f} {y:.3f} {RACK_H / 2:.3f}
  children [
{pallets}{beams}{uprights}{cartons}  ]
  name "{name}"
  boundingObject Box {{ size {RACK_LEN:.2f} {RACK_DEPTH:.2f} {RACK_H:.2f} }}
}}
'''


def floor_patch(x, y, sx, sy, rgb):
    r, g, b = rgb
    return f'''Pose {{
  translation {x:.3f} {y:.3f} 0.002
  children [ Shape {{ appearance PBRAppearance {{ baseColor {r} {g} {b} roughness 1 }} geometry Plane {{ size {sx:.2f} {sy:.2f} }} }} ]
}}
'''


def viewpoint():
    # camera at (0, -10.5, 13) looking at (0, 0.5, 0): yaw +90 deg then pitch down
    pitch, yaw = math.atan2(13, 11.0), math.pi / 2
    # rotation R = Rz(yaw) * Ry(pitch) as axis-angle
    cy, sy, cp, sp = math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch)
    R = [[cy * cp, -sy, cy * sp], [sy * cp, cy, sy * sp], [-sp, 0, cp]]
    ang = math.acos(max(-1, min(1, (R[0][0] + R[1][1] + R[2][2] - 1) / 2)))
    ax = [R[2][1] - R[1][2], R[0][2] - R[2][0], R[1][0] - R[0][1]]
    n = math.sqrt(sum(a * a for a in ax))
    ax = [a / n for a in ax]
    return f'''Viewpoint {{
  orientation {ax[0]:.4f} {ax[1]:.4f} {ax[2]:.4f} {ang:.4f}
  position 0 -10.5 13
}}
'''


def main():
    old = WORLD.read_text()
    robot = old[old.index('# Warehouse AMR'):]
    contact = re.search(r'  contactProperties \[.*?\n  \]\n', old, re.S).group(0)
    parts = ['''#VRML_SIM R2025a utf8

EXTERNPROTO "https://raw.githubusercontent.com/cyberbotics/webots/R2025a/projects/objects/backgrounds/protos/TexturedBackground.proto"
EXTERNPROTO "https://raw.githubusercontent.com/cyberbotics/webots/R2025a/projects/objects/backgrounds/protos/TexturedBackgroundLight.proto"

WorldInfo {
  title "IITGN Warehouse AMR Simulation - racked warehouse"
  basicTimeStep 20
''' + contact + '}\n\n', viewpoint(), '\nTexturedBackground {\n}\n\nTexturedBackgroundLight {\n}\n\n']
    parts.append('# ---------------- building ----------------\n')
    parts.append(box_solid('warehouse_floor', 0, 0, 2 * HALF_X + 1, 2 * HALF_Y + 1, 0.1, (0.62, 0.63, 0.6), z0=-0.1, rough=1))
    for name, x, y, sx, sy in [('wall_north', 0, HALF_Y, 2 * HALF_X + WALL_T, WALL_T),
                               ('wall_south', 0, -HALF_Y, 2 * HALF_X + WALL_T, WALL_T),
                               ('wall_east', HALF_X, 0, WALL_T, 2 * HALF_Y), ('wall_west', -HALF_X, 0, WALL_T, 2 * HALF_Y)]:
        parts.append(box_solid(name, x, y, sx, sy, WALL_H, (0.82, 0.82, 0.78), rough=0.9))
    for i, (x, y) in enumerate(PILLARS, 1):
        parts.append(box_solid(f'pillar_{i}', x, y, 0.35, 0.35, 3.0, (0.75, 0.75, 0.75)))
    parts.append('\n# ---------------- racking ----------------\n')
    for row, ry in ROWS_Y.items():
        for bay, bx in BAYS_X.items():
            parts.append(rack(f'rack_{row}{bay}', bx, ry))
    parts.append('\n# ---------------- stations ----------------\n')
    for name, _t, px, py, _yaw, fx, fy, sx, sy, sz, rgb in FIXTURES:
        parts.append(box_solid(name + '_fixture', fx, fy, sx, sy, sz, rgb))
        parts.append(floor_patch(px, py, 0.9, 0.9, tuple(min(1, c + 0.25) for c in rgb)))
    for row in ROWS_Y:  # pick-face floor markings
        for bx in BAYS_X.values():
            parts.append(floor_patch(bx, PICK_Y[row], 0.7, 0.5, (0.95, 0.75, 0.2)))
    parts.append('\n')
    WORLD.write_text(''.join(parts) + robot)

    lines = ['# GENERATED by scripts/generate_warehouse_world.py - edit the layout there, not here.',
             '# Warehouse stations in the `map` frame (= world frame; robot spawn at the origin).',
             '# Rack poses are the pick faces: aisle centre in front of the bay, facing the rack.',
             'capacity: 2', 'stations:', '  - {name: home, type: home, x: 0.0, y: 0.0, yaw_deg: 0}']
    for row in ROWS_Y:
        for bay, bx in BAYS_X.items():
            n = f'rack_{row}{bay}'
            lines.append(f'  - {{name: {n}, type: shelf, x: {bx:.1f}, y: {PICK_Y[row]:.1f}, yaw_deg: 90, '
                         f'items: [{", ".join(INVENTORY[n])}]}}')
    for name, typ, px, py, yaw, *_ in FIXTURES:
        lines.append(f'  - {{name: {name}, type: {typ}, x: {px:.1f}, y: {py:.1f}, yaw_deg: {yaw}}}')
    STATIONS.write_text('\n'.join(lines) + '\n')
    print(f'wrote {WORLD.relative_to(ROOT)} and {STATIONS.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
