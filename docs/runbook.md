# Operations runbook

How to start, check, operate and recover the warehouse AMR stack. Every terminal first runs:

```bash
source /opt/ros/jazzy/setup.bash && source ~/warehouse_amr_ws/install/setup.bash
```

## 1. Start (operation mode)

| Step | Command | Ready when |
|---|---|---|
| 1 Simulation | `ros2 launch amr_simulation warehouse_simulation.launch.py` | log shows `Configured and activated diffdrive_controller` and `joint_state_broadcaster` |
| 2 Localization + Nav2 | `ros2 launch amr_simulation amr_navigation.launch.py` | two `Managed nodes are active` lines (localization, navigation) |
| 3 Mission layer | `ros2 launch amr_tasks warehouse_tasks.launch.py` | `Warehouse manager ready: 10 stations, capacity 2` |
| 4 Agent + dashboard | `ros2 launch amr_dashboard ops.launch.py` | `Agent ready (local hybrid intent agent ...)` and `AMR dashboard on http://localhost:8765` |

The robot must be at its spawn pose (origin) when AMCL starts: AMCL is initialised there. Restarting step 2 alone
after the robot has moved needs a new initial pose (RViz "2D Pose Estimate").

## 2. Health checks

| Check | Command | Expected |
|---|---|---|
| Controllers active | `ros2 service call /controller_manager/list_controllers controller_manager_msgs/srv/ListControllers {}` | both `state='active'` |
| Command interface | `ros2 topic info /cmd_vel --verbose` | `TwistStamped`, 1 subscriber (`diffdrive_controller`) |
| LiDAR | `ros2 topic hz /scan` | ≈ 10 Hz |
| Localization | `ros2 run tf2_ros tf2_echo map base_footprint` | pose updates, matches the robot in Webots |
| Mission layer | `ros2 service call /warehouse/get_status amr_interfaces/srv/GetRobotStatus` | `state='idle'`, battery, nearest station |
| Local model | `ollama ps` | `qwen2.5:3b ... 100% GPU` |
| Dashboard | open http://localhost:8765 | `live` indicator green, robot on the map |
| Only one Webots | `netstat.exe -ano \| grep -E ":123[4-9] " \| grep -i listen` | exactly one listener, on 1234 |

## 3. Operate

- **Dashboard:** type an order in the command box, or click an example. Watch the activity feed: `intent` is what the
  model understood, `verifier` lines are corrections, `plan` is the optimiser result.
- **Terminal:** `ros2 run amr_agent chat` (add `--backend local|claude|rule`).
- **Other systems:** publish to `/agent/command`, read `/agent/response`.
- **Cancel:** say "cancel" / "stop", or Ctrl+C in `chat` while a mission runs.
- **Mapping mode** (after a layout change): stop step 2, run `ros2 launch amr_simulation amr_slam.launch.py`, then
  `python3 scripts/mapping_drive.py`, then
  `ros2 run nav2_map_server map_saver_cli -f maps/warehouse_map_vN --ros-args -p use_sim_time:=true`.

## 4. Stop

Ctrl+C each launch in reverse order, then make sure the Windows Webots process is gone (`stop_sim.sh`, or close
Webots). A surviving Webots keeps port 1234 and the next launch silently connects to the old world.

## 5. Known failure modes

| Symptom | Likely cause | Fix |
|---|---|---|
| Controllers fail to activate, `no 'ros2_control' tag found` | `robot_state_publisher` published a URDF without `<ros2_control>` | launch file must give RSP the full URDF (fixed in v0.1) |
| Robot ignores `/cmd_vel` | wrong message type | Jazzy diff drive takes `TwistStamped` only |
| Results identical after a world change | stale Webots on port 1234 | close all Webots processes, relaunch |
| Map shows racks as dots | LiDAR sees through racking at scan height | keep the pallet faces in the world (ADR-0007) |
| `Failed to make progress`, aborts near shelves | a fixed slowdown zone or too-slow approach | keep the TTC `approach` polygon (ADR-0006) |
| Navigation aborts with `Timed out ... compute_path_to_pose` | BT server timeout too short under WSL load | `bt_navigator.default_server_timeout: 200` |
| Robot drives the wrong way after a restart | AMCL initialised at origin, robot elsewhere | restart the simulation, or set the initial pose in RViz |
| First request takes ~45 s | model unloaded by Ollama | warm-up and `keep_alive` handle this; check `ollama ps` |
| Dashboard shows another app's page | port in use on Windows | default is 8765; `ros2 launch amr_dashboard ops.launch.py port:=8790` |
| Agent says it is in rule-based mode | Ollama not running and no usable API key | `ollama serve` / `ollama pull qwen2.5:3b` |

## 6. Logs and data

| What | Where |
|---|---|
| Agent decisions (request, intent, tool calls, results, timing) | `~/.ros/amr_agent/decisions.jsonl` |
| ROS node logs | `~/.ros/log/` |
| Benchmark results | `ros2 run amr_agent evaluate --json out.json`; published runs in `docs/eval/` |
| Demo recording | `python3 scripts/record_demo.py "<order>" demo.jsonl`, render with `scripts/render_demo_gif.py` |
