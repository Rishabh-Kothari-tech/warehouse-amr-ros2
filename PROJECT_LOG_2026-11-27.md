# Warehouse AMR — session log, 27 Nov 2026

## Working (verified)
- diffdrive_controller + joint_state_broadcaster **active**; wheel velocity interfaces claimed
- Robot drives on `/cmd_vel` (`geometry_msgs/TwistStamped` — Jazzy always uses stamped; `use_stamped_vel` no longer exists)
- Odometry calibrated: drift after a 30 m mapping loop = 3 cm / 0.8 deg (was 1.3 m / 51 deg)
- SLAM Toolbox mapping: `maps/warehouse_map_v3.{pgm,yaml}` (4 shelves, clean). Original `warehouse_map.*` untouched
- AMCL localization from saved map, auto initial pose at spawn (0,0,0)
- Nav2: 3/3 station goals succeeded; dynamic obstacle (unmapped box) avoided, plan detoured ~1 m

## Root causes found and fixed
1. **Controllers never activated**: in Jazzy the controller_manager builds its hardware from the FIRST `/robot_description`
   message; robot_state_publisher was publishing an empty placeholder (driver's async URDF push never landed).
   -> `warehouse_simulation.launch.py`: RSP publishes the real URDF; `set_robot_state_publisher: False`;
      removed duplicate base_footprint->base_link static TF (URDF already has it).
   -> `warehouse_amr_webots.urdf`: `laser_link` renamed `amr_lidar` (matches the /scan frame_id).
2. **Odometry heading error ~9.6% per turn**: Webots tyre contact sits near the outer wheel edge (effective track ~0.44 m).
   -> `controllers.yaml`: `wheel_separation_multiplier: 1.096`; also added accel limits (0.4 m/s^2, 1.0 rad/s^2).
3. **Stale Webots instances**: stopping a launch from WSL leaves Windows `webots-bin.exe` alive on port 1234, so the
   next launch silently connects to the OLD world. Always close Webots fully between runs (bridge `scripts/stop_all.sh` does it).
4. Nav2 params: map -> v3, footprint 0.52 x 0.46 m (was radius 0.27), inflation 0.55, collision StopZone 0.40 m,
   AMCL `set_initial_pose: true`. `setup.py` now installs `config/`. New `launch/amr_navigation.launch.py`.
5. World: added frictionless front/rear ball casters (two-wheel robot had no third support). Physically correct,
   but NOT what fixed the odometry (that was #2).

Backups of every edited file: `*.bak_20261127`.

## How to run
    # Terminal A
    ros2 launch amr_simulation warehouse_simulation.launch.py
    # Terminal B — mapping mode
    ros2 launch amr_simulation amr_slam.launch.py
    # ...or Terminal B — navigation mode (never both at once: both publish map->odom)
    ros2 launch amr_simulation amr_navigation.launch.py

## Remaining / next
- World has no perimeter walls; add walls + aisles for a realistic warehouse (Phase E)
- SLAM launch opens RViz with an empty default config — add a saved RViz config with Map/LaserScan/TF
- Spawner remap deprecation warning (use `--controller-ros-args`); TexturedBackgroundLight EXTERNPROTO warning
- Waypoint/multi-station task layer, then AI/agentic task allocation (Phase E/F)
