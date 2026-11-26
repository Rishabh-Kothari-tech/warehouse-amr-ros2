# Autonomous Warehouse AMR — ROS 2 Jazzy + Webots

A differential-drive warehouse robot simulated in Webots, with SLAM mapping, AMCL localization and Nav2 autonomous
navigation. Built as part of the IIT Gandhinagar PG Diploma (AI-ML & Agentic AI Engineering) Forward Deployed
Engineering track.

## Stack
ROS 2 Jazzy · Webots R2025a (`webots_ros2`) · ros2_control (`diff_drive_controller`) · SLAM Toolbox · Nav2 (AMCL,
NavFn, Regulated Pure Pursuit, collision monitor) · RViz2 · Windows + WSL2 (Ubuntu 24.04)

## Packages
| Package | Contents |
|---|---|
| `amr_simulation` | Webots world, robot URDF + ros2_control, controller/SLAM/Nav2 configs, launch files |
| `amr_description` | Standalone URDF + RViz display launch |
| `amr_bringup` | Status and velocity helper nodes |

## Results
- Wheel odometry calibrated: drift after a 30 m mapping loop is 3 cm / 0.8°
- SLAM map of the warehouse: `maps/warehouse_map_v3.{pgm,yaml}`
- Nav2: shelf pick-face and home goals reached; an unmapped obstacle is detected and planned around

## Build
```bash
source /opt/ros/jazzy/setup.bash
cd ~/warehouse_amr_ws
colcon build
source install/setup.bash
```

## Run
```bash
# Terminal A — simulation
ros2 launch amr_simulation warehouse_simulation.launch.py

# Terminal B — EITHER mapping mode...
ros2 launch amr_simulation amr_slam.launch.py
# ...OR navigation mode on the saved map (never both: each publishes map->odom)
ros2 launch amr_simulation amr_navigation.launch.py
```
On WSL, stopping a launch can leave the Windows Webots process running; close it before relaunching
(`stop_sim.sh` does this), otherwise the next launch connects to the stale instance.

## Engineering log
See [`PROJECT_LOG_2026-11-27.md`](PROJECT_LOG_2026-11-27.md) for root causes found and fixed (Jazzy
`/robot_description` timing, wheel-separation calibration, stale Webots instances, Nav2 footprint).

## Roadmap
Warehouse walls and aisles · multi-station waypoint tasks · AI/agentic task allocation and natural-language commands
