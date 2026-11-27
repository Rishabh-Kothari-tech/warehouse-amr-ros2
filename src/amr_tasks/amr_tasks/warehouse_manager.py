"""Warehouse task layer for the AMR.

Sits between Nav2 and higher-level planners (the AI agent, a WMS, a human). Exposes:

  action  /warehouse/execute_mission  (amr_interfaces/ExecuteMission)
  service /warehouse/list_stations    (amr_interfaces/ListStations)
  service /warehouse/get_status       (amr_interfaces/GetRobotStatus)
  service /warehouse/plan_orders      (amr_interfaces/PlanOrders)
  topic   /warehouse/status           (std_msgs/String, JSON, 1 Hz)
  topic   /warehouse/station_markers  (visualization_msgs/MarkerArray, for RViz)

A mission is a list of (station, action, item) steps. For each step the manager drives to
the station with Nav2's NavigateToPose and then performs the action. Pick/drop are
simulated with a dwell time and a cargo manifest; charging is simulated on a battery model
that drains with distance driven (from /odom). Every step is validated before the robot
moves, so an upstream planner (including an LLM) cannot command an unknown station, an
item that is not stocked there, an over-capacity load, or a long trip on a critical battery.
"""
import json
import math
import threading
import time
from typing import Dict, List, Optional

import rclpy
import yaml
from action_msgs.msg import GoalStatus
from ament_index_python.packages import get_package_share_directory
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import ComputePathToPose, NavigateToPose
from nav_msgs.msg import Odometry
from rclpy.action import ActionClient, ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile
from std_msgs.msg import String
from tf2_ros import Buffer, TransformListener
from visualization_msgs.msg import Marker, MarkerArray

from amr_interfaces.action import ExecuteMission
from amr_interfaces.msg import MissionStep, Station
from amr_interfaces.srv import GetRobotStatus, ListStations, PlanOrders
from amr_tasks.scheduler import Order, naive_plan, optimal_plan

ACTIONS = ('goto', 'pick', 'drop', 'charge')
STATION_COLORS = {'shelf': (0.85, 0.45, 0.1), 'packing': (0.1, 0.7, 0.3), 'charger': (0.95, 0.85, 0.1),
                  'home': (0.3, 0.5, 0.95)}


def yaw_to_quat(yaw):
    return 0.0, 0.0, math.sin(yaw / 2.0), math.cos(yaw / 2.0)


def quat_to_yaw(q):
    return math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))


class WarehouseManager(Node):

    def __init__(self):
        super().__init__('warehouse_manager')
        default_stations = get_package_share_directory('amr_tasks') + '/config/stations.yaml'
        self.declare_parameter('stations_file', default_stations)
        self.declare_parameter('initial_battery_pct', 100.0)
        self.declare_parameter('battery_drain_pct_per_m', 1.5)
        self.declare_parameter('charge_rate_pct_per_s', 8.0)
        self.declare_parameter('critical_battery_pct', 10.0)
        self.declare_parameter('dwell_s', 3.0)
        self.declare_parameter('arrive_tolerance_m', 0.25)
        self.declare_parameter('nav_attempts', 2)

        self.cb = ReentrantCallbackGroup()
        self.lock = threading.Lock()
        self._load_stations(self.get_parameter('stations_file').value)

        self.battery = float(self.get_parameter('initial_battery_pct').value)
        self.drain = float(self.get_parameter('battery_drain_pct_per_m').value)
        self.charge_rate = float(self.get_parameter('charge_rate_pct_per_s').value)
        self.critical = float(self.get_parameter('critical_battery_pct').value)
        self.dwell = float(self.get_parameter('dwell_s').value)
        self.arrive_tol = float(self.get_parameter('arrive_tolerance_m').value)
        self.state, self.mission_id, self.last_message = 'idle', '', 'ready'
        self.carrying: List[str] = []
        self.odometer = 0.0
        self._last_odom_xy = None
        self._path_cache: Dict[tuple, float] = {}

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.create_subscription(Odometry, '/odom', self._on_odom, 20, callback_group=self.cb)

        self.nav = ActionClient(self, NavigateToPose, 'navigate_to_pose', callback_group=self.cb)
        self.planner = ActionClient(self, ComputePathToPose, 'compute_path_to_pose', callback_group=self.cb)

        self.create_service(ListStations, '/warehouse/list_stations', self._srv_list, callback_group=self.cb)
        self.create_service(GetRobotStatus, '/warehouse/get_status', self._srv_status, callback_group=self.cb)
        self.create_service(PlanOrders, '/warehouse/plan_orders', self._srv_plan, callback_group=self.cb)
        self.mission_server = ActionServer(
            self, ExecuteMission, '/warehouse/execute_mission', execute_callback=self._execute,
            goal_callback=self._on_goal, cancel_callback=lambda _: CancelResponse.ACCEPT, callback_group=self.cb)

        self.status_pub = self.create_publisher(String, '/warehouse/status', 10)
        latched = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.marker_pub = self.create_publisher(MarkerArray, '/warehouse/station_markers', latched)
        self.create_timer(1.0, self._publish_status, callback_group=self.cb)
        self._publish_markers()
        self.get_logger().info(f'Warehouse manager ready: {len(self.stations)} stations, capacity {self.capacity}')

    # ------------------------------------------------------------------ setup / state
    def _load_stations(self, path):
        with open(path) as f:
            cfg = yaml.safe_load(f)
        self.capacity = int(cfg.get('capacity', 2))
        self.stations: Dict[str, dict] = {}
        for s in cfg['stations']:
            self.stations[s['name']] = {'name': s['name'], 'type': s['type'], 'x': float(s['x']),
                                        'y': float(s['y']), 'yaw': math.radians(float(s.get('yaw_deg', 0.0))),
                                        'items': list(s.get('items', []))}

    def _on_odom(self, msg: Odometry):
        p = msg.pose.pose.position
        if self._last_odom_xy is not None:
            d = math.hypot(p.x - self._last_odom_xy[0], p.y - self._last_odom_xy[1])
            if d < 0.5:  # ignore jumps (sim reset)
                with self.lock:
                    self.odometer += d
                    self.battery = max(0.0, self.battery - d * self.drain)
        self._last_odom_xy = (p.x, p.y)

    def robot_pose(self):
        try:
            t = self.tf_buffer.lookup_transform('map', 'base_footprint', rclpy.time.Time())
        except Exception:
            return None
        return t.transform.translation.x, t.transform.translation.y, quat_to_yaw(t.transform.rotation)

    def nearest_station(self, pose):
        if pose is None:
            return ''
        name, d = min(((n, math.hypot(s['x'] - pose[0], s['y'] - pose[1])) for n, s in self.stations.items()),
                      key=lambda t: t[1])
        return name if d <= self.arrive_tol * 2 else f'near {name} ({d:.1f} m)'

    def _status_dict(self):
        pose = self.robot_pose()
        with self.lock:
            return {'x': pose[0] if pose else None, 'y': pose[1] if pose else None,
                    'yaw_deg': math.degrees(pose[2]) if pose else None,
                    'battery_pct': round(self.battery, 1), 'state': self.state, 'mission': self.mission_id,
                    'carrying': list(self.carrying), 'capacity': self.capacity,
                    'nearest_station': self.nearest_station(pose), 'odometer_m': round(self.odometer, 2),
                    'last_message': self.last_message}

    def _publish_status(self):
        self.status_pub.publish(String(data=json.dumps(self._status_dict())))

    def _publish_markers(self):
        arr = MarkerArray()
        for i, s in enumerate(self.stations.values()):
            r, g, b = STATION_COLORS.get(s['type'], (0.7, 0.7, 0.7))
            for k, kind in enumerate((Marker.CYLINDER, Marker.TEXT_VIEW_FACING)):
                m = Marker()
                m.header.frame_id = 'map'
                m.ns, m.id, m.type, m.action = 'stations', i * 2 + k, kind, Marker.ADD
                m.pose.position.x, m.pose.position.y = s['x'], s['y']
                m.pose.orientation.w = 1.0
                m.color.r, m.color.g, m.color.b, m.color.a = r, g, b, 0.6 if kind == Marker.CYLINDER else 1.0
                if kind == Marker.CYLINDER:
                    m.scale.x = m.scale.y = 0.3
                    m.scale.z = 0.02
                else:
                    m.pose.position.z, m.scale.z, m.text = 0.4, 0.22, s['name']
                arr.markers.append(m)
        self.marker_pub.publish(arr)

    # ------------------------------------------------------------------ services
    def _srv_list(self, _req, res):
        for s in self.stations.values():
            res.stations.append(Station(name=s['name'], type=s['type'], x=s['x'], y=s['y'], yaw=s['yaw'],
                                        items=s['items']))
        return res

    def _srv_status(self, _req, res):
        st = self._status_dict()
        res.x = st['x'] or 0.0
        res.y = st['y'] or 0.0
        res.yaw = math.radians(st['yaw_deg'] or 0.0)
        res.battery_pct = float(st['battery_pct'])
        res.state, res.nearest_station, res.current_mission = st['state'], st['nearest_station'], st['mission']
        res.carrying, res.capacity, res.odometer_m = st['carrying'], self.capacity, st['odometer_m']
        res.last_message = st['last_message']
        return res

    def _pose_msg(self, x, y, yaw):
        p = PoseStamped()
        p.header.frame_id = 'map'
        p.header.stamp = self.get_clock().now().to_msg()
        p.pose.position.x, p.pose.position.y = x, y
        _, _, p.pose.orientation.z, p.pose.orientation.w = yaw_to_quat(yaw)
        return p

    @staticmethod
    def _wait(future, timeout_s):
        end = time.monotonic() + timeout_s
        while not future.done():
            if time.monotonic() > end:
                return False
            time.sleep(0.02)
        return True

    def _path_length(self, a, b, poses):
        """Length of the Nav2 global plan from location a to b (cached, symmetric)."""
        if a == b:
            return 0.0
        key = tuple(sorted((a, b)))
        if key in self._path_cache and '__robot__' not in key:
            return self._path_cache[key]
        (ax, ay, ayaw), (bx, by, byaw) = poses[a], poses[b]
        euclid = math.hypot(bx - ax, by - ay)
        if not self.planner.wait_for_server(timeout_sec=2.0):
            return euclid * 1.3
        goal = ComputePathToPose.Goal()
        goal.start, goal.goal, goal.use_start = self._pose_msg(ax, ay, ayaw), self._pose_msg(bx, by, byaw), True
        fut = self.planner.send_goal_async(goal)
        if not self._wait(fut, 5.0) or not fut.result().accepted:
            return euclid * 1.3
        rf = fut.result().get_result_async()
        if not self._wait(rf, 10.0) or not rf.result().result.path.poses:
            return euclid * 1.3
        pts = [(p.pose.position.x, p.pose.position.y) for p in rf.result().result.path.poses]
        length = sum(math.hypot(x2 - x1, y2 - y1) for (x1, y1), (x2, y2) in zip(pts, pts[1:]))
        self._path_cache[key] = length
        return length

    def _srv_plan(self, req, res):
        orders = [Order(o.order_id or f'order_{i + 1}', o.item, o.pickup, o.dropoff) for i, o in enumerate(req.orders)]
        errors = []
        for o in orders:
            for st in (o.pickup, o.dropoff):
                if st not in self.stations:
                    errors.append(f'unknown station "{st}"')
            if o.pickup in self.stations and o.item and o.item not in self.stations[o.pickup]['items']:
                errors.append(f'"{o.item}" is not stocked at {o.pickup}')
        for st in (req.start_station, req.end_station):
            if st and st not in self.stations:
                errors.append(f'unknown station "{st}"')
        if errors:
            res.success, res.message = False, '; '.join(sorted(set(errors)))
            return res
        poses = {n: (s['x'], s['y'], s['yaw']) for n, s in self.stations.items()}
        start = req.start_station
        if not start:
            pose = self.robot_pose()
            if pose is None:
                res.success, res.message = False, 'robot pose unknown (is localization running?)'
                return res
            poses['__robot__'], start = pose, '__robot__'
        end = req.end_station or None

        def dist(a, b):
            return self._path_length(a, b, poses)

        steps, cost, method = optimal_plan(orders, start, end, dist, capacity=self.capacity)
        _, naive = naive_plan(orders, start, end, dist)
        res.steps = [MissionStep(station=s.station, action=s.action, item=s.item) for s in steps]
        res.planned_distance_m, res.naive_distance_m, res.success = cost, naive, True
        saving = (1 - cost / naive) * 100 if naive > 0 else 0.0
        res.message = (f'{len(orders)} orders, {len(steps)} steps via {method} on Nav2 path lengths: '
                       f'{cost:.1f} m vs {naive:.1f} m one-at-a-time ({saving:.0f}% shorter)')
        self.get_logger().info(res.message)
        return res

    # ------------------------------------------------------------------ missions
    def _on_goal(self, goal):
        with self.lock:
            busy = self.state not in ('idle', 'error')
        if busy:
            self.get_logger().warn('Rejecting mission: robot busy')
            return GoalResponse.REJECT
        return GoalResponse.ACCEPT

    def validate(self, steps) -> Optional[str]:
        carrying = list(self.carrying)
        for i, s in enumerate(steps, 1):
            if s.station not in self.stations:
                return f'step {i}: unknown station "{s.station}" (known: {", ".join(self.stations)})'
            if s.action not in ACTIONS:
                return f'step {i}: unknown action "{s.action}" (use {", ".join(ACTIONS)})'
            st = self.stations[s.station]
            if s.action == 'pick':
                if s.item not in st['items']:
                    return f'step {i}: "{s.item}" is not stocked at {s.station} (stocked: {", ".join(st["items"]) or "nothing"})'
                if len(carrying) >= self.capacity:
                    return f'step {i}: over capacity ({self.capacity} items)'
                carrying.append(s.item)
            elif s.action == 'drop':
                if s.item not in carrying:
                    return f'step {i}: cannot drop "{s.item}", robot would not be carrying it'
                carrying.remove(s.item)
            elif s.action == 'charge' and st['type'] != 'charger':
                return f'step {i}: {s.station} is not a charging station'
        return None

    def _set(self, state, msg=None):
        with self.lock:
            self.state = state
            if msg:
                self.last_message = msg
        if msg:
            self.get_logger().info(msg)

    def _feedback(self, gh, idx, total, step, state):
        fb = ExecuteMission.Feedback()
        fb.step_index, fb.total_steps, fb.station, fb.action = idx, total, step.station, step.action
        fb.state, fb.battery_pct = state, float(self.battery)
        gh.publish_feedback(fb)

    def _navigate(self, gh, station) -> str:
        """Drive to a station, retrying a failed Nav2 goal. Returns 'ok', 'canceled' or an error message."""
        attempts = int(self.get_parameter('nav_attempts').value)
        outcome = ''
        for attempt in range(1, attempts + 1):
            outcome = self._navigate_once(gh, station)
            if outcome in ('ok', 'canceled'):
                return outcome
            if attempt < attempts:
                self._set('navigating', f'{outcome}; retrying ({attempt + 1}/{attempts})')
                time.sleep(1.0)
        return outcome

    def _navigate_once(self, gh, station) -> str:
        pose = self.robot_pose()
        if pose and math.hypot(pose[0] - station['x'], pose[1] - station['y']) < self.arrive_tol:
            return 'ok'
        if not self.nav.wait_for_server(timeout_sec=5.0):
            return 'Nav2 navigate_to_pose server not available'
        goal = NavigateToPose.Goal()
        goal.pose = self._pose_msg(station['x'], station['y'], station['yaw'])
        fut = self.nav.send_goal_async(goal)
        if not self._wait(fut, 10.0) or not fut.result().accepted:
            return 'Nav2 rejected the goal'
        nav_gh = fut.result()
        rf = nav_gh.get_result_async()
        while not rf.done():
            if gh.is_cancel_requested:
                nav_gh.cancel_goal_async()
                return 'canceled'
            time.sleep(0.1)
        status = rf.result().status
        return 'ok' if status == GoalStatus.STATUS_SUCCEEDED else f'navigation to {station["name"]} failed (status {status})'

    def _execute(self, gh):
        steps, t0, odo0 = list(gh.request.steps), time.monotonic(), self.odometer
        result = ExecuteMission.Result()
        with self.lock:
            self.mission_id = gh.request.mission_id or f'mission_{int(time.time())}'

        def finish(success, msg, done, state='idle'):
            self._set(state, msg)
            result.success, result.message, result.steps_completed = success, msg, done
            result.distance_m, result.duration_s = self.odometer - odo0, time.monotonic() - t0
            result.battery_pct = float(self.battery)
            with self.lock:
                self.mission_id = ''
            return result

        err = self.validate(steps)
        if err:
            gh.abort()
            return finish(False, f'Mission rejected: {err}', 0)
        self._set('navigating', f'{self.mission_id}: starting {len(steps)} steps')
        for i, step in enumerate(steps):
            st = self.stations[step.station]
            if self.battery <= self.critical and st['type'] != 'charger':
                gh.abort()
                return finish(False, f'Battery critical ({self.battery:.0f}%): aborting before step {i + 1}; send the robot to charge', i, 'error')
            self._set('navigating', f'step {i + 1}/{len(steps)}: driving to {step.station}')
            self._feedback(gh, i + 1, len(steps), step, 'navigating')
            nav = self._navigate(gh, st)
            if nav == 'canceled':
                gh.canceled()
                return finish(False, f'Mission canceled during step {i + 1}', i)
            if nav != 'ok':
                gh.abort()
                return finish(False, nav, i, 'error')
            if step.action in ('pick', 'drop'):
                self._set('picking' if step.action == 'pick' else 'dropping',
                          f'step {i + 1}/{len(steps)}: {step.action} {step.item} at {step.station}')
                self._feedback(gh, i + 1, len(steps), step, self.state)
                time.sleep(self.dwell)
                with self.lock:
                    if step.action == 'pick':
                        self.carrying.append(step.item)
                    else:
                        self.carrying.remove(step.item)
            elif step.action == 'charge':
                self._set('charging', f'charging at {step.station} from {self.battery:.0f}%')
                while self.battery < 100.0:
                    if gh.is_cancel_requested:
                        gh.canceled()
                        return finish(False, 'Mission canceled while charging', i)
                    time.sleep(0.5)
                    with self.lock:
                        self.battery = min(100.0, self.battery + self.charge_rate * 0.5)
                    self._feedback(gh, i + 1, len(steps), step, 'charging')
        gh.succeed()
        return finish(True, f'{self.mission_id} complete: {len(steps)} steps', len(steps))


def main():
    rclpy.init()
    node = WarehouseManager()
    executor = MultiThreadedExecutor(num_threads=6)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
